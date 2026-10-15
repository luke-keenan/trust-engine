import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, AsyncGenerator
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import models
from audit import record
from models import Evaluation, PolicyRule, System, User, init_db
from policy_engine import RULES, evaluate, pass_rate
from risk_classifier import RiskEnsemble
from trust_scorer import score

from trust_engine.auth import verify_token

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./governance.db")
MODEL_PATH = Path(__file__).with_name("ensemble.pt")
engine = models.engine
sessions = models.async_session
users: dict[str, str] = {} 



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

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value


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
    async with sessions() as session, session.begin():
        for rule in RULES:
            if await session.get(PolicyRule, rule.id) is None:
                session.add(PolicyRule(
                    id=rule.id, sutra=rule.sutra, rule_name=rule.rule_name,
                    description=rule.description, severity=rule.severity,
                    nist_ref=rule.nist_ref, nist_characteristic=rule.nist_characteristic,
                ))


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


@app.get("/", response_class=HTMLResponse)
async def home_page() -> str:
    return """
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Governance Trust Engine</title>
        <style>
          :root {
            --bg: #0b1020;
            --panel: #121a2b;
            --panel-2: #1a243a;
            --text: #e5ecff;
            --muted: #9cb2d1;
            --accent: #6ee7b7;
            --accent-2: #7dd3fc;
            --warning: #fbbf24;
            --danger: #f87171;
            --shadow: rgba(15, 23, 42, 0.4);
          }
          * { box-sizing: border-box; }
          body {
            margin: 0;
            font-family: Arial, Helvetica, sans-serif;
            background: linear-gradient(180deg, #0b1020 0%, #0f172a 100%);
            color: var(--text);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
          }
          .shell {
            width: min(1100px, 90vw);
            background: rgba(18, 26, 43, 0.94);
            border: 1px solid rgba(125, 211, 252, 0.2);
            border-radius: 18px;
            box-shadow: 0 20px 40px var(--shadow);
            overflow: hidden;
          }
          .topbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.2rem 1.6rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            background: rgba(26, 36, 58, 0.8);
          }
          .brand {
            font-size: 1.2rem;
            font-weight: 700;
            letter-spacing: 0.04em;
          }
          .status {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.45rem 0.8rem;
            border-radius: 999px;
            background: rgba(110, 231, 183, 0.12);
            color: var(--accent);
            font-size: 0.85rem;
            font-weight: 600;
          }
          .dot {
            width: 9px;
            height: 9px;
            border-radius: 50%;
            background: var(--accent);
            box-shadow: 0 0 10px rgba(110, 231, 183, 0.9);
          }
          .content {
            display: grid;
            grid-template-columns: 1.4fr 1fr;
            gap: 2rem;
            padding: 2rem;
          }
          .hero {
            padding: 1rem 0.5rem 0.5rem;
          }
          h1 {
            margin: 0 0 1rem;
            font-size: clamp(2.1rem, 4vw, 4rem);
            line-height: 1.08;
          }
          .subtitle {
            margin: 0 0 1.5rem;
            color: var(--muted);
            font-size: 1.05rem;
            line-height: 1.7;
            max-width: 56ch;
          }
          .actions {
            display: flex;
            flex-wrap: wrap;
            gap: 0.9rem;
            margin-bottom: 2rem;
          }
          .btn {
            display: inline-block;
            padding: 0.9rem 1.2rem;
            border-radius: 10px;
            text-decoration: none;
            font-weight: 700;
            transition: transform 0.2s ease, opacity 0.2s ease;
          }
          .btn:hover { transform: translateY(-1px); }
          .btn.primary {
            background: linear-gradient(135deg, var(--accent) 0%, var(--accent-2) 100%);
            color: #08111d;
          }
          .btn.secondary {
            color: var(--text);
            border: 1px solid rgba(125, 211, 252, 0.45);
            background: rgba(125, 211, 252, 0.05);
          }
          .stats {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 1rem;
          }
          .stat {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 14px;
            padding: 1rem;
          }
          .stat .label {
            color: var(--muted);
            font-size: 0.8rem;
            margin-bottom: 0.45rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
          }
          .stat .value {
            font-size: 1.6rem;
            font-weight: 800;
          }
          .panel {
            background: linear-gradient(180deg, var(--panel-2), rgba(18, 26, 43, 0.9));
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 16px;
            padding: 1.2rem;
          }
          .panel h2 {
            margin: 0 0 1rem;
            font-size: 1.1rem;
          }
          .endpoint-list {
            list-style: none;
            margin: 0;
            padding: 0;
            display: grid;
            gap: 0.8rem;
          }
          .endpoint-list li {
            background: rgba(255, 255, 255, 0.02);
            border-radius: 10px;
            padding: 0.75rem 0.8rem;
            border: 1px solid rgba(255, 255, 255, 0.04);
          }
          .method {
            display: inline-block;
            min-width: 52px;
            padding: 0.2rem 0.45rem;
            border-radius: 6px;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            margin-right: 0.7rem;
            background: rgba(110, 231, 183, 0.12);
            color: var(--accent);
          }
          .path {
            font-family: monospace;
            color: var(--text);
          }
          .note {
            margin-top: 1rem;
            color: var(--muted);
            font-size: 0.9rem;
            line-height: 1.6;
          }
          @media (max-width: 800px) {
            .content {
              grid-template-columns: 1fr;
            }
            .stats {
              grid-template-columns: 1fr;
            }
            .topbar {
              flex-direction: column;
              gap: 0.85rem;
            }
          }
        </style>
      </head>
      <body>
        <main class="shell">
          <div class="topbar">
            <div class="brand">Governance Trust Engine</div>
            <div class="status"><span class="dot"></span> System Online</div>
          </div>
          <div class="content">
            <section class="hero">
              <h1>Measure trust before systems become liabilities.</h1>
              <p class="subtitle">
                Evaluate AI and operational systems against governance policies,
                risk signals, and trust posture outputs in a single, auditable workflow.
              </p>

              <div class="actions">
                <a class="btn primary" href="/docs">Open API Docs</a>
                <a class="btn secondary" href="/health">Health Check</a>
              </div>

              <div class="stats">
                <div class="stat">
                  <div class="label">Policies</div>
                  <div class="value">7</div>
                </div>
                <div class="stat">
                  <div class="label">Risk Tiers</div>
                  <div class="value">4</div>
                </div>
                <div class="stat">
                  <div class="label">Trust Score</div>
                  <div class="value">0-1000</div>
                </div>
              </div>
            </section>

            <aside class="panel">
              <h2>Core endpoints</h2>
              <ul class="endpoint-list">
                <li><span class="method">GET</span><span class="path">/health</span></li>
                <li><span class="method">POST</span><span class="path">/evaluate</span></li>
                <li><span class="method">GET</span><span class="path">/trust/{system_id}</span></li>
                <li><span class="method">GET</span><span class="path">/audit/{system_id}</span></li>
                <li><span class="method">POST</span><span class="path">/users</span></li>
              </ul>
              <p class="note">
                This service combines policy evaluation, calibrated risk classification,
                and trust scoring into a single governance-grade decision endpoint.
              </p>
            </aside>
          </div>
        </main>
      </body>
    </html>
    """


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/users", status_code=201)
async def create_user(request: CreateUserRequest) -> dict[str, Any]:
    insert_user = sqlite_insert if engine.dialect.name == "sqlite" else pg_insert
    async with sessions() as session, session.begin():
        result = await session.execute(
            insert_user(User)
            .values(
                id=str(uuid4()),
                name=request.name,
                email=request.email.lower(),
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
    signals = request.signals.model_dump()
    results = evaluate(signals)
    tier, risk_probability, uncertainty = classifier().predict(signals)
    trust_score, maturity, trusted = score(pass_rate(results), risk_probability, uncertainty)
    async with sessions() as session, session.begin():
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
    async with sessions() as session:
        rows = (await session.scalars(
            select(Evaluation).where(Evaluation.system_id == system_id)
            .order_by(Evaluation.timestamp.desc()).limit(10)
        )).all()
        if not rows:
            raise HTTPException(status_code=404, detail="No evaluations for system")
        return {"system_id": system_id, "current": evaluation_json(rows[0]),
                "evaluations": [evaluation_json(row) for row in rows]}


@app.get("/audit/{system_id}")
async def audit_trail(
    system_id: str, _current_user: Annotated[User, Depends(verify_token)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    async with sessions() as session:
        rows = (await session.scalars(
            select(Evaluation).where(Evaluation.system_id == system_id)
            .order_by(Evaluation.timestamp.desc()).offset(offset).limit(limit)
        )).all()
        return {"system_id": system_id, "offset": offset, "limit": limit,
                "evaluations": [evaluation_json(row) for row in rows]}



# @app.on_event("startup")
# async def startup():
#     if not os.environ.get("TESTING"):
#         await init_db()
