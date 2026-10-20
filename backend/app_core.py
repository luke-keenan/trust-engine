"""FastAPI application implementation."""

import os
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, AsyncGenerator, Literal
from uuid import uuid4
import math
from datetime import datetime, timedelta, timezone


from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import models
from audit import record
from models import (
    Collab, CollabMember, Community, CommunityInvite, Evaluation,
    Opportunity, OpportunityApplication, PolicyOverride, PolicyRule, System,
    User, Vote, init_db, engine, AsyncSession, async_session,
)
from policy_engine import RULES, evaluate, pass_rate
from risk_classifier import RiskEnsemble
from trust_scorer import score
from datetime import timedelta
from auth import verify_token, user_from_token, hash_password, verify_password, create_token
import re
from scorechart import router as chart_router



DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./governance.db")
MODEL_PATH = Path(__file__).with_name("ensemble.pt")
engine = models.engine
sessions = models.async_session
users: dict[str, str] = {} 


def _session_factory():
    import app

    return app.async_session


def _staleness_factor(ts: datetime) -> float:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    days_since_ts = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
    return math.exp(-math.log(2) / 30 * days_since_ts)


def _utc_datetime(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


class PolicyOverrideRequest(BaseModel):
    rule_id: str = Field(min_length=1, max_length=16)
    threshold: float = Field(allow_inf_nan=False)
    severity: Literal["pass", "warn", "fail"]


class OpportunityRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    scope: Literal["local", "state", "national", "remote"] = "remote"
    city: str = Field(default="", max_length=100)
    state: str = Field(default="", max_length=100)
    min_trust_score: float = Field(default=500, ge=0)
    required_rules: list[str] = Field(default_factory=list)
    domain: str = Field(default="general", max_length=32)
    expires_at: datetime | None = None


class Signals(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_drift: float = Field(ge=0, le=1, allow_inf_nan=False)
    data_quality: float = Field(ge=0, le=1, allow_inf_nan=False)
    access_anomaly_count: int = Field(ge=0, strict=True)
    output_variance: float = Field(ge=0, allow_inf_nan=False)
    fairness_metric: float = Field(ge=0, le=1, allow_inf_nan=False)
    human_oversight: bool
    bias_audit_done: bool
    data_lineage_documented: bool
    explanation_available: bool | None = None


class EvaluateRequest(BaseModel):
    system_id: str = Field(min_length=1, max_length=128)
    signals: Signals


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(
        min_length=6,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod    
    def strip_name(cls, value: str) -> str:
            value = value.strip()
            if not value:
                raise ValueError("Name cannot be blank")
            return value

    @field_validator("password")
    @classmethod    
    def validate_password_strength(cls, v: str) -> str:
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one number")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", v):
            raise ValueError("Password must contain at least one special character")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        return v

class CreateCollabRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    focus: Literal["research", "policy", "industry", "academic", "general"]

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value

class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=6, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RecallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_role: str = Field(pattern="^(admin|moderator)$")


class KickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str


class UpdateCommunityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=500)


class FlagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str
    reason: str = Field(min_length=5, max_length=500)   

class VoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    role: str = Field(pattern="^(admin|moderator)$")   


async def initialize() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(init_db)
        if engine.dialect.name == "sqlite":
            await connection.execute(text(
                "CREATE TRIGGER IF NOT EXISTS evaluations_no_update BEFORE UPDATE ON evaluations "
                "BEGIN SELECT RAISE(ABORT, 'evaluations are append-only'); END"
            ))
            await connection.execute(text(
                "CREATE TRIGGER IF NOT EXISTS evaluations_no_delete BEFORE DELETE ON evaluations "
                "BEGIN SELECT RAISE(ABORT, 'evaluations are append-only'); END"
            ))
        elif engine.dialect.name == "postgresql":
            await connection.execute(text(
                "CREATE OR REPLACE FUNCTION reject_evaluation_mutation() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'evaluations are append-only'; END; $$"
            ))
            for operation in ("UPDATE", "DELETE"):
                await connection.execute(text(
                    f"DROP TRIGGER IF EXISTS evaluations_no_{operation.lower()} ON evaluations"
                ))
                await connection.execute(text(
                    f"CREATE TRIGGER evaluations_no_{operation.lower()} BEFORE {operation} "
                    "ON evaluations FOR EACH ROW EXECUTE FUNCTION reject_evaluation_mutation()"
                ))
    async with _session_factory()() as session, session.begin():
        for rule in RULES:
            if await session.get(PolicyRule, rule.id) is None:
                session.add(PolicyRule(
                    id=rule.id, sutra=rule.sutra, rule_name=rule.rule_name,
                    description=rule.description, severity=rule.severity,
                    nist_ref=rule.nist_ref, nist_characteristic=rule.nist_characteristic,
                ))

class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    password: str

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    await initialize()
    yield
    await engine.dispose()


app = FastAPI(title="Governance Trust Engine", lifespan=lifespan)


@lru_cache(maxsize=1)
def classifier() -> RiskEnsemble:
    if not MODEL_PATH.is_file():
        raise HTTPException(status_code=503, detail="Risk model unavailable; run train.py")
    return RiskEnsemble.load(MODEL_PATH)

@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "Governance Trust Engine", "docs": "/docs", "health": "/health"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/users", status_code=201)
async def create_user(request: CreateUserRequest) -> dict[str, Any]:
    insert_user = sqlite_insert if engine.dialect.name == "sqlite" else pg_insert
    async with _session_factory()() as session, session.begin():
        result = await session.execute(
            insert_user(User)
            .values(
                id=str(uuid4()),
                name=request.name,
                email=request.email.lower(),
                password_hash=hash_password(request.password),
                created_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(index_elements=[User.email])
            .returning(User.id, User.name, User.email, User.created_at)
        )
        user = result.mappings().one_or_none()
        if user is None:
            raise HTTPException(status_code=409, detail="A user with this email already exists")
        return dict(user)


@app.post("/evaluate")
async def evaluate_system(
    request: EvaluateRequest, _current_user: Annotated[User, Depends(verify_token)]
) -> dict[str, Any]:
    return await evaluate_request(request)


async def evaluate_request(request: EvaluateRequest) -> dict[str, Any]:
    signals = request.signals.model_dump()
    results = evaluate(signals)
    tier, risk_probability, uncertainty = classifier().predict(signals)
    trust_score, maturity, trusted = score(pass_rate(results), risk_probability, uncertainty)
    async with _session_factory()() as session, session.begin():
        insert_system = sqlite_insert if engine.dialect.name == "sqlite" else pg_insert
        await session.execute(insert_system(System).values(
            id=request.system_id, name=request.system_id, description="",
            created_at=datetime.now(timezone.utc),
        ).on_conflict_do_nothing(index_elements=[System.id]))
        entry = record(request.system_id, signals, results, tier, trust_score, uncertainty, trusted)
        session.add(entry)
        await session.flush()
        return {
            "trust_score": trust_score, "maturity": maturity, "risk_tier": tier,
            "policy_results": results, "uncertainty": uncertainty,
            "trusted": trusted, "audit_id": entry.id,
        }


@app.websocket("/ws/evaluate")
async def websocket_evaluate(websocket: WebSocket) -> None:
    authorization = websocket.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        await websocket.close(code=1008, reason="Authentication required")
        return

    try:
        await user_from_token(token)
    except HTTPException:
        await websocket.close(code=1008, reason="Authentication required")
        return

    await websocket.accept()
    while True:
        try:
            message = await websocket.receive_text()
        except WebSocketDisconnect:
            break

        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            await websocket.send_json({"error": "invalid_json"})
            continue

        try:
            request = EvaluateRequest.model_validate(payload)
        except ValidationError as error:
            await websocket.send_json({
                "error": "invalid_request",
                "detail": jsonable_encoder(error.errors(include_input=False)),
            })
            continue

        try:
            result = await evaluate_request(request)
        except HTTPException as error:
            await websocket.send_json({
                "error": "evaluation_failed",
                "detail": error.detail,
            })
            continue

        await websocket.send_json(result)


def evaluation_json(row: Evaluation) -> dict[str, Any]:
    return {
        "audit_id": row.id, "timestamp": row.timestamp, "signals": row.signals_json,
        "policy_results": row.policy_results_json, "risk_tier": row.risk_tier,
        "trust_score": row.trust_score, "uncertainty": row.uncertainty, "trusted": row.trusted,
    }


@app.get("/trust/{system_id}")
async def trust_posture(
    system_id: str, _current_user: Annotated[User, Depends(verify_token)]
) -> dict[str, Any]:
    async with _session_factory()() as session:
        rows = (await session.scalars(
            select(Evaluation).where(Evaluation.system_id == system_id)
            .order_by(Evaluation.timestamp.desc()).limit(10)
        )).all()
        if not rows:
            raise HTTPException(status_code=404, detail="No evaluations for system")
        return {"system_id": system_id, "current": evaluation_json(rows[0]),
                "effective_score": rows[0].trust_score * _staleness_factor(rows[0].timestamp),
                "evaluations": [evaluation_json(row) for row in rows]}


@app.get("/audit/{system_id}")
async def audit_trail(
    system_id: str, _current_user: Annotated[User, Depends(verify_token)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    async with _session_factory()() as session:
        rows = (await session.scalars(
            select(Evaluation).where(Evaluation.system_id == system_id)
            .order_by(Evaluation.timestamp.desc()).offset(offset).limit(limit)
        )).all()
        return {"system_id": system_id, "offset": offset, "limit": limit,
                "evaluations": [evaluation_json(row) for row in rows]}

@app.post("/users/login")
async def login(request: LoginRequest) -> dict[str, str]:
    async with _session_factory()() as session:
        user = (await session.scalars(
            select(User).where(User.email == request.email.lower())
        )).first()
    if user is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": create_token(user.email), "token_type": "bearer"}


@app.get("/collabs")
async def list_collabs(
    _user: User = Depends(verify_token),
) -> list[dict[str, Any]]:
    async with _session_factory()() as session:
        collabs = (await session.scalars(
            select(Collab).order_by(Collab.created_at.desc())
        )).all()
        return [
            {
                "id": collab.id,
                "name": collab.name,
                "focus": collab.focus,
                "member_count": collab.member_count,
                "status": collab.status,
            }
            for collab in collabs
        ]


@app.post("/collabs", status_code=201)
async def create_collab(
    request: CreateCollabRequest,
    user: User = Depends(verify_token),
) -> dict[str, Any]:
    collab = Collab(
        id=str(uuid4()),
        name=request.name,
        focus=request.focus,
        description="",
        member_count=1,
        status="active",
        community_id=None,
        created_by=user.id,
        created_at=datetime.now(timezone.utc),
    )
    member = CollabMember(
        id=str(uuid4()),
        collab_id=collab.id,
        user_id=user.id,
        role="admin",
        joined_at=datetime.now(timezone.utc),
        left_at=None,
    )
    async with _session_factory()() as session, session.begin():
        session.add_all([collab, member])

    return {
        "id": collab.id,
        "name": collab.name,
        "focus": collab.focus,
        "member_count": collab.member_count,
        "status": collab.status,
    }



@app.post("/collabs/{collab_id}/form-community")
async def form_community(
    collab_id: str,
    user: User = Depends(verify_token),
) -> dict[str, Any]:
    async with _session_factory()() as session, session.begin():
        collab = (await session.scalars(select(Collab).where(Collab.id == collab_id))).first()
        if collab is None:
            raise HTTPException(404, "Collab not found")
        if collab.member_count < 3:
            raise HTTPException(400, f"Need at least 3 members (has {collab.member_count})")
        if collab.status == "community":
            raise HTTPException(409, "Already a community")


        ALLOWED_TYPES = {"research", "policy", "industry", "academic", "general"}
        if collab.focus not in ALLOWED_TYPES:
            raise HTTPException(400, f"focus must be one of {ALLOWED_TYPES}")   

        # Trusted member check
        latest = (await session.scalars(
            select(Evaluation)
            .where(Evaluation.system_id == user.id)
            .order_by(Evaluation.timestamp.desc())
            .limit(1)
        )).first()
        if not latest or not latest.trusted:
            raise HTTPException(403, "Only trusted members (score ≥ 700) can form communities")

        # Max 3 communities per user
        user_communities = (await session.scalars(
            select(CollabMember).join(Collab).where(
                CollabMember.user_id == user.id,
                Collab.status == "community",
            )
        )).all()
        if len(user_communities) >= 3:
            raise HTTPException(403, "Max 3 communities per user")

        community = Community(
            id=str(uuid4()),
            name=f"{collab.name} Community",
            focus=collab.focus,
            min_members=10,
            phase="growing",
            created_at=datetime.now(timezone.utc),
        )
        session.add(community)
        await session.flush()

        collab.status = "community"
        collab.community_id = community.id
        await session.flush()

        return {
            "community_id": community.id,
            "name": community.name,
            "phase": "growing",
            "min_members_required": 10,
            "current_members": collab.member_count,
        }


# ── Join Community (admin approves after 10) ──

@app.post("/communities/{community_id}/request-join")
async def request_join(
    community_id: str,
    user: User = Depends(verify_token),
) -> dict[str, str]:
    async with _session_factory()() as session, session.begin():
        collab = (await session.scalars(
            select(Collab).where(Collab.community_id == community_id)
        )).first()
        if collab is None:
            raise HTTPException(404, "Community not found")

        # Max 3 communities per user
        user_communities = (await session.scalars(
            select(CollabMember).join(Collab).where(
                CollabMember.user_id == user.id,
                Collab.status == "community",
            )
        )).all()
        if len(user_communities) >= 3:
            raise HTTPException(403, "Max 3 communities per user")

        if collab.member_count < 10:
            # Growing phase: auto-join
            session.add(CollabMember(
                id=str(uuid4()), collab_id=collab.id,
                user_id=user.id, role="member",
                joined_at=datetime.now(timezone.utc),
            ))
            collab.member_count += 1
            await session.flush()
            return {"status": "joined", "phase": "growing"}
        else:
            # Active phase: admin must approve via invite
            raise HTTPException(403, "Community is full. Request an invite from the admin.")


@app.post("/communities/{community_id}/invite")
async def invite_member(
    community_id: str,
    request: InviteRequest,  # {email: str}
    user: User = Depends(verify_token),
) -> dict[str, str]:
    """Admin-only: invite a new member after community is active."""
    async with _session_factory()() as session, session.begin():
        collab = (await session.scalars(
            select(Collab).where(Collab.community_id == community_id)
        )).first()
        if collab is None:
            raise HTTPException(404, "Community not found")

        # Only admin can invite
        is_admin = (await session.scalars(
            select(CollabMember).where(
                CollabMember.collab_id == collab.id,
                CollabMember.user_id == user.id,
                CollabMember.role == "admin",
            )
        )).first()
        if not is_admin:
            raise HTTPException(403, "Only admin can invite")

        invite = CommunityInvite(
            id=str(uuid4()),
            community_id=community_id,
            email=request.email.lower(),
            invited_by=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=72),
            created_at=datetime.now(timezone.utc),
        )
        session.add(invite)
        await session.flush()

        return {"status": "invite sent", "expires_in": "72h"}


@app.post("/communities/{community_id}/accept-invite")
async def accept_invite(
    community_id: str,
    user: User = Depends(verify_token),
) -> dict[str, str]:
    async with _session_factory()() as session, session.begin():
        invite = (await session.scalars(
            select(CommunityInvite).where(
                CommunityInvite.community_id == community_id,
                CommunityInvite.email == user.email,
                CommunityInvite.accepted == False,
                CommunityInvite.expires_at > datetime.now(timezone.utc),
            )
        )).first()
        if invite is None:
            raise HTTPException(404, "No valid invite found")

        invite.accepted = True
        collab = (await session.scalars(
            select(Collab).where(Collab.community_id == community_id)
        )).first()
        session.add(CollabMember(
            id=str(uuid4()), collab_id=collab.id,
            user_id=user.id, role="member",
            joined_at=datetime.now(timezone.utc),
        ))
        collab.member_count += 1
        await session.flush()

        return {"status": "joined"}


# ── Leave Community (free exit) ──

@app.post("/communities/{community_id}/leave")
async def leave_community(
    community_id: str,
    user: User = Depends(verify_token),
) -> dict[str, str]:
    async with _session_factory()() as session, session.begin():
        collab = (await session.scalars(
            select(Collab).where(Collab.community_id == community_id)
        )).first()
        if collab is None:
            raise HTTPException(404, "Community not found")

        membership = (await session.scalars(
            select(CollabMember).where(
                CollabMember.collab_id == collab.id,
                CollabMember.user_id == user.id,
                CollabMember.left_at == None,
            )
        )).first()
        if membership is None:
            raise HTTPException(404, "Not a member")

        # Admin can't leave (must transfer first)
        if membership.role == "admin":
            raise HTTPException(400, "Admin must transfer role before leaving")

        membership.left_at = datetime.now(timezone.utc)
        collab.member_count -= 1
        await session.flush()

        return {"status": "left"}


# ── Voting (72h window, auto-resolve) ──

@app.post("/communities/{community_id}/vote")
async def cast_vote(
    community_id: str,
    request: VoteRequest,
    user: User = Depends(verify_token),
) -> dict[str, str]:
    async with _session_factory()() as session, session.begin():
        community = (await session.scalars(
            select(Community).where(Community.id == community_id)
        )).first()
        if community is None:
            raise HTTPException(404, "Community not found")

        # Check voting window
        if community.phase == "active":
            raise HTTPException(400, "Voting already resolved")
        if community.voting_deadline and datetime.now(timezone.utc) > community.voting_deadline:
            # Auto-resolve expired votes
            await _resolve_votes(session, community)
            raise HTTPException(400, "Voting window closed")

        collab = (await session.scalars(
            select(Collab).where(Collab.community_id == community_id)
        )).first()
        if collab.member_count < 10:
            raise HTTPException(400, f"Need 10+ members to vote (has {collab.member_count})")

        # Verify member
        is_member = (await session.scalars(
            select(CollabMember).where(
                CollabMember.collab_id == collab.id,
                CollabMember.user_id == user.id,
                CollabMember.left_at == None,
            )
        )).first()
        if not is_member:
            raise HTTPException(403, "Not a member")

        # Set deadline on first vote
        if community.voting_deadline is None:
            community.voting_deadline = datetime.now(timezone.utc) + timedelta(hours=72)
            community.phase = "voting"

        session.add(Vote(
            id=str(uuid4()),
            community_id=community_id,
            voter_id=user.id,
            candidate_id=request.candidate_id,
            role=request.role,
            cast_at=datetime.now(timezone.utc),
        ))
        await session.flush()

        return {"status": "vote recorded", "deadline": community.voting_deadline.isoformat()}



async def _resolve_votes(session: AsyncSession, community: Community):
    """Auto-resolve: majority wins, assign roles, set phase to active."""
    votes = (await session.scalars(
        select(Vote).where(Vote.community_id == community.id)
    )).all()

    tally: dict[str, dict[str, int]] = {}
    for v in votes:
        tally.setdefault(v.candidate_id, {"admin": 0, "moderator": 0})
        tally[v.candidate_id][v.role] += 1

    for role in ("admin", "moderator"):
        candidates = {cid: t[role] for cid, t in tally.items() if t[role] > 0}
        if candidates:
            winner = max(candidates, key=candidates.get)
            if role == "admin":
                community.admin_id = winner
            else:
                community.moderator_id = winner

    community.phase = "active"
    community.last_review_at = datetime.now(timezone.utc)


@app.get("/communities/{community_id}/status")
async def community_status(
    community_id: str,
    user: User = Depends(verify_token),
) -> dict[str, Any]:
    async with _session_factory()() as session:
        community = (await session.scalars(
            select(Community).where(Community.id == community_id)
        )).first()
        if community is None:
            raise HTTPException(404, "Community not found")

        collab = (await session.scalars(
            select(Collab).where(Collab.community_id == community_id)
        )).first()

        # Check if voting deadline passed → auto-resolve
        if community.phase == "voting" and community.voting_deadline:
            if datetime.now(timezone.utc) > community.voting_deadline:
                await _resolve_votes(session, community)
                await session.commit()

        return {
            "community_id": community_id,
            "phase": community.phase,
            "members": collab.member_count,
            "min_required": community.min_members,
            "admin": community.admin_id,
            "moderator": community.moderator_id,
            "voting_deadline": community.voting_deadline.isoformat() if community.voting_deadline else None,
            "last_review": community.last_review_at.isoformat() if community.last_review_at else None,
        }


# ── Admin Recall (90-day review + majority) ──

@app.post("/communities/{community_id}/recall")
async def recall_admin(
    community_id: str,
    request: RecallRequest,  # {target_role: "admin"|"moderator"}
    user: User = Depends(verify_token),
) -> dict[str, str]:
    """Majority vote to remove admin/moderator. Only after 90 days."""
    async with _session_factory()() as session, session.begin():
        community = (await session.scalars(
            select(Community).where(Community.id == community_id)
        )).first()
        if community is None:
            raise HTTPException(404, "Community not found")

        if community.last_review_at is None:
            raise HTTPException(400, "No prior review date")
        if datetime.now(timezone.utc) - community.last_review_at < timedelta(days=90):
            raise HTTPException(400, "90-day review period not elapsed")

        # Trigger a new vote for the same role
        community.phase = "voting"
        community.voting_deadline = datetime.now(timezone.utc) + timedelta(hours=72)
        await session.flush()

        return {"status": "recall vote initiated", "deadline": community.voting_deadline.isoformat()}


# ── Admin Powers ──

@app.post("/communities/{community_id}/kick")
async def kick_member(
    community_id: str,
    request: KickRequest,  # {user_id: str}
    user: User = Depends(verify_token),
) -> dict[str, str]:
    """Admin can kick a member."""
    async with _session_factory()() as session, session.begin():
        community = (await session.scalars(
            select(Community).where(Community.id == community_id)
        )).first()
        if community is None or community.admin_id != user.id:
            raise HTTPException(403, "Only admin can kick")

        collab = (await session.scalars(
            select(Collab).where(Collab.community_id == community_id)
        )).first()
        membership = (await session.scalars(
            select(CollabMember).where(
                CollabMember.collab_id == collab.id,
                CollabMember.user_id == request.user_id,
                CollabMember.left_at == None,
            )
        )).first()
        if membership is None:
            raise HTTPException(404, "Member not found")
        if membership.role == "admin":
            raise HTTPException(400, "Cannot kick admin (use recall)")

        membership.left_at = datetime.now(timezone.utc)
        collab.member_count -= 1
        await session.flush()

        return {"status": "kicked"}


@app.put("/communities/{community_id}")
async def update_community(
    community_id: str,
    request: UpdateCommunityRequest,  # {name?, description?}
    user: User = Depends(verify_token),
) -> dict[str, str]:
    """Admin can change name/description."""
    async with _session_factory()() as session, session.begin():
        community = (await session.scalars(
            select(Community).where(Community.id == community_id)
        )).first()
        if community is None or community.admin_id != user.id:
            raise HTTPException(403, "Only admin can update")

        if request.name:
            community.name = request.name
        await session.flush()
        return {"status": "updated"}


# ── Moderator Powers ──

@app.post("/communities/{community_id}/flag")
async def flag_content(
    community_id: str,
    request: FlagRequest,  # {target_id: str, reason: str}
    user: User = Depends(verify_token),
) -> dict[str, str]:
    """Moderator or admin can flag content."""
    async with _session_factory()() as session, session.begin():
        community = (await session.scalars(
            select(Community).where(Community.id == community_id)
        )).first()
        if community is None:
            raise HTTPException(404, "Community not found")
        if user.id not in (community.admin_id, community.moderator_id):
            raise HTTPException(403, "Only admin/moderator can flag")

        # Store flag (add a Flags model or log to audit)
        return {"status": "flagged", "reason": request.reason}


# ── Community Trust Score (recency-weighted) ──

@app.get("/communities/{community_id}/trust")
async def community_trust(
    community_id: str,
    user: User = Depends(verify_token),
) -> dict[str, Any]:
    """Exponential decay, 30-day half-life."""
    import math
    async with _session_factory()() as session:
        collab = (await session.scalars(
            select(Collab).where(Collab.community_id == community_id)
        )).first()
        if collab is None:
            raise HTTPException(404, "Community not found")

        members = (await session.scalars(
            select(CollabMember).where(
                CollabMember.collab_id == collab.id,
                CollabMember.left_at == None,
            )
        )).all()

        member_ids = [m.user_id for m in members]
        evals = (await session.scalars(
            select(Evaluation)
            .where(Evaluation.system_id.in_(member_ids))
            .order_by(Evaluation.timestamp.desc())
            .limit(200)
        )).all()

        now = datetime.now(timezone.utc)
        weighted_sum = 0.0
        weight_total = 0.0
        for e in evals:
            age_days = (now - e.timestamp).total_seconds() / 86400
            weight = math.exp(-0.693 * age_days / 30)  # 30-day half-life
            weighted_sum += e.trust_score * weight
            weight_total += weight

        avg = weighted_sum / weight_total if weight_total > 0 else 0

        return {
            "community_id": community_id,
            "weighted_score": round(avg, 1),
            "maturity": "Kernel" if avg >= 900 else "Supervisor" if avg >= 700
                       else "User" if avg >= 400 else "Untrusted",
            "evaluations_counted": len(evals),
            "members": len(member_ids),
        }


async def _community_collab(
    session: AsyncSession, community_id: str
) -> tuple[Community, Collab | None]:
    community = await session.get(Community, community_id)
    if community is None:
        raise HTTPException(status_code=404, detail="Community not found")
    collab = (await session.scalars(
        select(Collab).where(Collab.community_id == community_id)
    )).first()
    return community, collab


async def _require_community_moderator(
    session: AsyncSession, community_id: str, user: User
) -> tuple[Community, Collab | None]:
    community, collab = await _community_collab(session, community_id)
    if user.id in (community.admin_id, community.moderator_id):
        return community, collab
    membership = None
    if collab is not None:
        membership = (await session.scalars(
            select(CollabMember).where(
                CollabMember.collab_id == collab.id,
                CollabMember.user_id == user.id,
                CollabMember.role.in_(("admin", "moderator")),
                CollabMember.left_at.is_(None),
            )
        )).first()
    if membership is None:
        raise HTTPException(status_code=403, detail="Only community admins or moderators")
    return community, collab


@app.post("/communities/{community_id}/policy-overrides", status_code=201)
async def create_policy_override(
    community_id: str,
    request: PolicyOverrideRequest,
    user: User = Depends(verify_token),
) -> dict[str, Any]:
    async with _session_factory()() as session, session.begin():
        await _require_community_moderator(session, community_id, user)
        override = PolicyOverride(
            id=str(uuid4()),
            community_id=community_id,
            rule_id=request.rule_id,
            threshold=request.threshold,
            severity=request.severity,
        )
        session.add(override)
        await session.flush()
        return {
            "id": override.id,
            "rule_id": override.rule_id,
            "threshold": override.threshold,
            "severity": override.severity,
        }


@app.get("/communities/{community_id}/policy-overrides")
async def list_policy_overrides(
    community_id: str,
    _current_user: User = Depends(verify_token),
) -> list[dict[str, Any]]:
    async with _session_factory()() as session:
        await _community_collab(session, community_id)
        overrides = (await session.scalars(
            select(PolicyOverride).where(
                PolicyOverride.community_id == community_id
            )
        )).all()
        return [
            {
                "rule_id": override.rule_id,
                "threshold": override.threshold,
                "severity": override.severity,
            }
            for override in overrides
        ]


@app.post("/communities/{community_id}/opportunities", status_code=201)
async def create_opportunity(
    community_id: str,
    request: OpportunityRequest,
    user: User = Depends(verify_token),
) -> dict[str, str]:
    async with _session_factory()() as session, session.begin():
        await _require_community_moderator(session, community_id, user)
        opportunity = Opportunity(
            id=str(uuid4()),
            community_id=community_id,
            title=request.title,
            description=request.description,
            scope=request.scope,
            city=request.city,
            state=request.state,
            min_trust_score=request.min_trust_score,
            required_rules=request.required_rules,
            domain=request.domain,
            created_by=user.id,
            created_at=datetime.now(timezone.utc),
            expires_at=request.expires_at,
            status="open",
        )
        session.add(opportunity)
        await session.flush()
        return {
            "id": opportunity.id,
            "title": opportunity.title,
            "scope": opportunity.scope,
            "status": opportunity.status,
        }


@app.get("/opportunities")
async def list_opportunities(
    scope: Literal["all", "local", "state", "national", "remote"] = "all",
    state: str = "",
    _current_user: User = Depends(verify_token),
) -> list[dict[str, Any]]:
    async with _session_factory()() as session:
        query = select(Opportunity).where(Opportunity.status == "open")
        if scope != "all":
            query = query.where(Opportunity.scope == scope)
        if state:
            query = query.where(Opportunity.state == state)
        opportunities = (await session.scalars(query)).all()
        return [
            {
                "id": opportunity.id,
                "title": opportunity.title,
                "scope": opportunity.scope,
                "state": opportunity.state,
                "city": opportunity.city,
                "min_trust_score": opportunity.min_trust_score,
                "required_rules": opportunity.required_rules,
                "expires_at": (
                    opportunity.expires_at.isoformat()
                    if opportunity.expires_at is not None else None
                ),
            }
            for opportunity in opportunities
        ]


@app.post("/opportunities/{opportunity_id}/apply")
async def apply_to_opportunity(
    opportunity_id: str,
    user: User = Depends(verify_token),
) -> dict[str, str]:
    async with _session_factory()() as session, session.begin():
        opportunity = await session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        if opportunity.status != "open":
            raise HTTPException(status_code=400, detail="Opportunity is not open")
        now = datetime.now(timezone.utc)
        if (
            opportunity.expires_at is not None
            and _utc_datetime(opportunity.expires_at) <= now
        ):
            raise HTTPException(status_code=400, detail="Opportunity has expired")
        membership = (await session.scalars(
            select(CollabMember)
            .join(Collab, CollabMember.collab_id == Collab.id)
            .where(
                Collab.community_id == opportunity.community_id,
                CollabMember.user_id == user.id,
                CollabMember.left_at.is_(None),
            )
        )).first()
        if membership is None:
            raise HTTPException(status_code=403, detail="Community membership required")
        latest = (await session.scalars(
            select(Evaluation)
            .where(Evaluation.system_id == user.id)
            .order_by(Evaluation.timestamp.desc())
            .limit(1)
        )).first()
        if latest is None:
            raise HTTPException(status_code=400, detail="At least one evaluation is required")
        effective_score = latest.trust_score * _staleness_factor(latest.timestamp)
        if effective_score < opportunity.min_trust_score:
            raise HTTPException(status_code=403, detail="Trust score below opportunity minimum")
        passing_rules = {
            result.get("rule_id")
            for result in latest.policy_results_json
            if result.get("result") == "pass"
        }
        if not set(opportunity.required_rules).issubset(passing_rules):
            raise HTTPException(status_code=400, detail="Required policy rules must pass")
        session.add(OpportunityApplication(
            id=str(uuid4()),
            opportunity_id=opportunity.id,
            user_id=user.id,
            applied_at=now,
            status="pending",
        ))
        await session.flush()
        return {"status": "applied"}


@app.get("/communities/{community_id}/members")
async def community_members_leaderboard(
    community_id: str,
    _current_user: User = Depends(verify_token),
) -> list[dict[str, Any]]:
    async with _session_factory()() as session:
        _, collab = await _community_collab(session, community_id)
        if collab is None:
            raise HTTPException(status_code=404, detail="Community not found")
        members = (await session.scalars(
            select(CollabMember).where(
                CollabMember.collab_id == collab.id,
                CollabMember.left_at.is_(None),
            )
        )).all()
        leaderboard = []
        for member in members:
            latest = (await session.scalars(
                select(Evaluation)
                .where(Evaluation.system_id == member.user_id)
                .order_by(Evaluation.timestamp.desc())
                .limit(1)
            )).first()
            leaderboard.append({
                "user_id": member.user_id,
                "role": member.role,
                "effective_score": (
                    latest.trust_score * _staleness_factor(latest.timestamp)
                    if latest is not None else 0.0
                ),
                "last_evaluated": (
                    latest.timestamp.isoformat() if latest is not None else None
                ),
            })
        leaderboard.sort(key=lambda item: item["effective_score"], reverse=True)
        for rank, entry in enumerate(leaderboard, start=1):
            entry["rank"] = rank
        return leaderboard


app.include_router(chart_router)