import pytest_asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from starlette.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from datetime import datetime, timezone
from datetime import timedelta
import uuid
import models
import bcrypt
from models import (
    CollabMember, Collab, Community, Evaluation, Opportunity,
)
import app as app_module
import auth
import scorechart
from sqlalchemy import select


# Create an isolated database for each test.
test_engine = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

app = app_module.app
from models import Base, User  # noqa: F401
from auth import create_token


@pytest_asyncio.fixture(autouse=True)
async def setup_db(monkeypatch):
    monkeypatch.setattr(models, "async_session", TestSession)
    monkeypatch.setattr(auth, "async_session", TestSession)
    monkeypatch.setattr(app_module, "async_session", TestSession)
    monkeypatch.setattr(app_module, "sessions", TestSession)
    monkeypatch.setattr(app_module, "engine", test_engine)
    monkeypatch.setattr(scorechart, "async_session", TestSession)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    email = "test@example.com"
    async with TestSession() as session:
        session.add(User(
            id="test-user",
            name="Test User",
            email=email,
            password_hash="",
            created_at=datetime.now(timezone.utc),
        ))
        await session.commit()
    headers = {"Authorization": f"Bearer {create_token(email)}"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as c:
        yield c

async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_create_and_list_collabs(client, db):
    response = await client.post("/collabs", json={
        "name": "Responsible AI",
        "focus": "research",
    })

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["name"] == "Responsible AI"
    assert created["focus"] == "research"
    assert created["member_count"] == 1
    assert created["status"] == "active"

    listed = await client.get("/collabs")
    assert listed.status_code == 200, listed.text
    assert listed.json() == [created]

    member = (await db.scalars(
        select(CollabMember).where(CollabMember.collab_id == created["id"])
    )).one()
    assert member.user_id == "test-user"
    assert member.role == "admin"


async def test_create_collab_rejects_invalid_input(client):
    response = await client.post("/collabs", json={
        "name": "   ",
        "focus": "unknown",
    })

    assert response.status_code == 422


async def test_protected_endpoint_rejects_missing_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as unauthenticated:
        r = await unauthenticated.get("/trust/nonexistent-system")
    assert r.status_code == 401


async def test_create_user(client):
    r = await client.post("/users", json={
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "password": "Secure@Pass123",
    })

    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Ada Lovelace"
    assert data["email"] == "ada@example.com"
    assert data["id"]
    assert data["created_at"]


async def test_create_user_rejects_duplicate_email(client):
    first = await client.post("/users", json={
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "password": "Another@Pass456",
        
    })
    duplicate = await client.post("/users", json={
        "name": "Another User",
        "email": "ada@example.com",
        "password": "Another@Pass456", 
    })

    assert first.status_code == 201
    assert duplicate.status_code == 409


async def test_create_user_rejects_invalid_email(client):
    r = await client.post("/users", json={
        "name": "Ada Lovelace",
        "email": "not-an-email",
        "password": "What@Ever789",
    })

    assert r.status_code == 422


async def test_evaluate_trusted(client):
    r = await client.post("/evaluate", json={
        "system_id": "test-system-1",
        "signals": {
            "model_drift": 0.05, "data_quality": 0.95,
            "access_anomaly_count": 0, "output_variance": 0.1,
            "fairness_metric": 0.95, "human_oversight": True,
            "bias_audit_done": True, "data_lineage_documented": True
        }
    })
    assert r.status_code == 200
    data = r.json()
    assert data["trust_score"] >= 700
    assert data["trusted"] is True
    assert data["audit_id"] is not None


async def test_websocket_evaluate(client):
    token = create_token("test@example.com")
    with TestClient(app) as websocket_client:
        with websocket_client.websocket_connect(
            "/ws/evaluate",
            headers={"Authorization": f"Bearer {token}"},
        ) as websocket:
            websocket.send_text("{invalid json")
            assert websocket.receive_json() == {"error": "invalid_json"}
            websocket.send_json({"system_id": "invalid", "signals": {}})
            assert websocket.receive_json()["error"] == "invalid_request"

            websocket.send_json({
                "system_id": "websocket-system",
                "signals": {
                    "model_drift": 0.05, "data_quality": 0.95,
                    "access_anomaly_count": 0, "output_variance": 0.1,
                    "fairness_metric": 0.95, "human_oversight": True,
                    "bias_audit_done": True, "data_lineage_documented": True,
                },
            })
            result = websocket.receive_json()
            assert result["trust_score"] >= 700
            assert result["audit_id"]


async def test_evaluate_untrusted(client):
    r = await client.post("/evaluate", json={
        "system_id": "test-system-2",
        "signals": {
            "model_drift": 0.9, "data_quality": 0.2,
            "access_anomaly_count": 20, "output_variance": 0.95,
            "fairness_metric": 0.3, "human_oversight": False,
            "bias_audit_done": False, "data_lineage_documented": False
        }
    })
    assert r.status_code == 200
    data = r.json()
    assert data["trust_score"] < 400
    assert data["trusted"] is False


async def test_trust_posture(client):
    await client.post("/evaluate", json={
        "system_id": "test-system-3",
        "signals": {
            "model_drift": 0.1, "data_quality": 0.9,
            "access_anomaly_count": 1, "output_variance": 0.2,
            "fairness_metric": 0.9, "human_oversight": True,
            "bias_audit_done": True, "data_lineage_documented": True
        }
    })
    r = await client.get("/trust/test-system-3")
    assert r.status_code == 200
    data = r.json()
    assert data["system_id"] == "test-system-3"
    assert len(data["evaluations"]) == 1  


async def test_audit_trail(client):
    for _ in range(3):
        await client.post("/evaluate", json={
            "system_id": "test-system-4",
            "signals": {
                "model_drift": 0.2, "data_quality": 0.8,
                "access_anomaly_count": 2, "output_variance": 0.3,
                "fairness_metric": 0.85, "human_oversight": True,
                "bias_audit_done": True, "data_lineage_documented": True
            }
        })
    r = await client.get("/audit/test-system-4")
    assert r.status_code == 200
    data = r.json()
    assert len(data["evaluations"]) == 3  


async def test_trust_not_found(client):
    r = await client.get("/trust/nonexistent-system")
    assert r.status_code == 404


async def test_policy_results_structure(client):
    r = await client.post("/evaluate", json={
        "system_id": "test-system-5",
        "signals": {
            "model_drift": 0.1, "data_quality": 0.8,
            "access_anomaly_count": 0, "output_variance": 0.2,
            "fairness_metric": 0.9, "human_oversight": True,
            "bias_audit_done": False, "data_lineage_documented": True
        }
    })
    data = r.json()
    assert len(data["policy_results"]) == 7
    for pr in data["policy_results"]:
        assert "rule_name" in pr       # was "rule"
        assert "sutra" in pr
        assert "result" in pr          # was "status"
        assert pr["result"] in ("pass", "fail", "warn")
    failed = [p for p in data["policy_results"] if p["result"] == "fail"]
    assert any("bias" in p["rule_name"].lower() or "bias" in p["rule_id"].lower() for p in failed)   

async def test_score_chart(client):
    for i in range(3):
        await client.post("/evaluate", json={
            "system_id": "chart-test",
            "signals": {
                "model_drift": 0.1, "data_quality": 0.9,
                "access_anomaly_count": 0, "output_variance": 0.2,
                "fairness_metric": 0.9, "human_oversight": True,
                "bias_audit_done": True, "data_lineage_documented": True
            }
        })
    r = await client.get("/chart/chart-test")
    assert r.status_code == 200
    data = r.json()
    assert data["system_id"] == "chart-test"
    assert len(data["points"]) == 3
    assert data["summary"]["count"] == 3
    assert data["summary"]["trend"] in ("up", "down")
    assert all("trust_score" in p for p in data["points"])


# ─── Community Tests ───────────────────────────────────────────────────────────

async def _create_users(db, count: int) -> list:
    users = []
    for i in range(count):
        u = User(
            id=str(uuid.uuid4()),
            name=f"User {i:02d}",
            email=f"u{i:02d}@t.io",
            password_hash=bcrypt.hashpw(b"pass", bcrypt.gensalt()).decode(),
            created_at=datetime.now(timezone.utc),
        )
        db.add(u)
        users.append(u)
    await db.flush()
    return users


@pytest_asyncio.fixture
async def db():
    async with TestSession() as session:
        yield session


async def test_full_community_flow(db):
    users = await _create_users(db, 12)

    # 1) u0 creates a Collab
    collab = Collab(
        id=str(uuid.uuid4()),
        name="Test Collab",
        focus="research",
        description="",
        member_count=3,
        status="active",
        community_id=None,
        created_by=users[0].id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(collab)
    await db.flush()

    # 2) u1, u2 join
    for u in users[1:3]:
        db.add(CollabMember(
            id=str(uuid.uuid4()),
            collab_id=collab.id,
            user_id=u.id,
            role="member",
            joined_at=datetime.now(timezone.utc),
            left_at=None,
        ))
    await db.flush()

    # 3) u0 (trusted) forms community via API
    await _seed_trusted_eval(db, users[0].id)
    await db.commit()

    token = create_token(users[0].email)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            f"/collabs/{collab.id}/form-community",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["phase"] == "growing"
        assert data["min_members_required"] == 10

    # 4) Idempotency — second call should 409
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r2 = await c.post(
            f"/collabs/{collab.id}/form-community",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 409


async def test_form_requires_3_members(db):
    users = await _create_users(db, 2)

    collab = Collab(
        id=str(uuid.uuid4()),
        name="Small Collab",
        focus="research",
        description="",
        member_count=2,
        status="active",
        community_id=None,
        created_by=users[0].id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(collab)
    await db.flush()
    await _seed_trusted_eval(db, users[0].id)
    await db.commit()

    token = create_token(users[0].email)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            f"/collabs/{collab.id}/form-community",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400
        assert "3 members" in r.json()["detail"]


async def test_form_requires_trusted(db):
    users = await _create_users(db, 3)

    collab = Collab(
        id=str(uuid.uuid4()),
        name="Untrusted Collab",
        focus="research",
        description="",
        member_count=3,
        status="active",
        community_id=None,
        created_by=users[0].id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(collab)
    await db.flush()
    # No trusted evaluation seeded
    await db.commit()

    token = create_token(users[0].email)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            f"/collabs/{collab.id}/form-community",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403
        assert "trusted" in r.json()["detail"].lower()


async def test_max_3_communities(client, db):
    user = await db.get(User, "test-user")
    assert user is not None

    for index in range(3):
        community = Community(
            id=str(uuid.uuid4()),
            name=f"Existing {index}",
            focus="research",
            created_at=datetime.now(timezone.utc),
        )
        db.add(community)
        await db.flush()
        collab = Collab(
            id=str(uuid.uuid4()),
            name=f"Existing {index}",
            focus="research",
            member_count=3,
            status="community",
            community_id=community.id,
            created_by=user.id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(collab)
        db.add(CollabMember(
            id=str(uuid.uuid4()),
            collab_id=collab.id,
            user_id=user.id,
            role="member",
            joined_at=datetime.now(timezone.utc),
        ))

    collab = Collab(
        id=str(uuid.uuid4()),
        name="Fourth",
        focus="research",
        member_count=3,
        status="active",
        created_by=user.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(collab)
    await _seed_trusted_eval(db, user.id)
    await db.commit()

    response = await client.post(f"/collabs/{collab.id}/form-community")
    assert response.status_code == 403, response.text
    assert "Max 3" in response.json()["detail"]


# async def test_max_3_communities(db):
#     users = await _create_users(db, 4)

#     # Seed 3 existing communities the user belongs to
#     # Replace the fake collab_id strings with real Collab rows:
#     for i in range(3):
#         fake_collab_id = str(uuid.uuid4())
#         db.add(Collab(
#             id=fake_collab_id,
#             name=f"Existing {i}",
#             focus="research",
#             member_count=3,
#             status="community",  # ← must be "community"
#             community_id=str(uuid.uuid4()),
#             created_by=users[0].id,
#             created_at=datetime.now(timezone.utc),
#         ))
#         db.add(CollabMember(
#             id=str(uuid.uuid4()),
#             collab_id=fake_collab_id,
#             user_id=users[0].id,
#             role="member",
#             joined_at=datetime.now(timezone.utc),
#             left_at=None,
#         ))   
#     await db.commit()

#     # Create a 4th collab with 3 members + trusted
#     collab = Collab(
#         id=str(uuid.uuid4()),
#         name="Fourth",
#         focus="research",
#         description="",
#         member_count=3,
#         status="active",
#         community_id=None,
#         created_by=users[0].id,
#         created_at=datetime.now(timezone.utc),
#     )
#     db.add(collab)
#     await db.flush()
#     await _seed_trusted_eval(db, users[0].id)
#     await db.commit()

#     token = create_token(users[0].email)
#     transport = ASGITransport(app=app)
#     async with AsyncClient(transport=transport, base_url="http://test") as c:
#         r = await c.post(
#             f"/collabs/{collab.id}/form-community",
#             headers={"Authorization": f"Bearer {token}"},
#         )
#         assert r.status_code == 403
#         assert "Max 3" in r.json()["detail"]   

async def _seed_trusted_eval(db, user_id: str):
    
    db.add(Evaluation(
        id=str(uuid.uuid4()),
        system_id=user_id,
        timestamp=datetime.now(timezone.utc),
        signals_json={},
        policy_results_json=[],
        risk_tier="low",
        trust_score=850.0,
        uncertainty=0.1,
        trusted=True,
    ))
    await db.flush()   


async def _setup_community(db, admin_user, member_count):
    community_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    community = Community(
        id=community_id,
        name="Test Community",
        focus="research",
        admin_id=admin_user.id,
        created_at=now,
    )
    collab = Collab(
        id=str(uuid.uuid4()),
        name="Test Community Collab",
        focus="research",
        member_count=member_count,
        status="community",
        community_id=community_id,
        created_by=admin_user.id,
        created_at=now,
    )
    db.add_all((community, collab))
    await db.flush()

    users = (await db.scalars(
        select(User).where(User.id != admin_user.id).order_by(User.id)
    )).all()
    if len(users) < member_count - 1:
        raise AssertionError("Create enough users before setting up the community")
    db.add(CollabMember(
        id=str(uuid.uuid4()),
        collab_id=collab.id,
        user_id=admin_user.id,
        role="admin",
        joined_at=now,
    ))
    for member in users[:member_count - 1]:
        db.add(CollabMember(
            id=str(uuid.uuid4()),
            collab_id=collab.id,
            user_id=member.id,
            role="member",
            joined_at=now,
        ))
    await db.flush()
    return collab, community


def _auth_headers(user):
    return {"Authorization": f"Bearer {create_token(user.email)}"}


def _api_client(user):
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=_auth_headers(user),
    )


async def test_staleness_decay(db):
    user = (await _create_users(db, 1))[0]
    db.add(Evaluation(
        id=str(uuid.uuid4()),
        system_id=user.id,
        timestamp=datetime.now(timezone.utc) - timedelta(days=30),
        signals_json={},
        policy_results_json=[],
        risk_tier="low",
        trust_score=800,
        uncertainty=0.1,
        trusted=True,
    ))
    await db.commit()
    await db.close()

    async with _api_client(user) as client:
        response = await client.get(f"/trust/{user.id}")
    assert response.status_code == 200, response.text
    assert response.json()["effective_score"] == pytest.approx(400, abs=1)


async def test_create_policy_override(db):
    admin, _member = await _create_users(db, 2)
    _collab, community = await _setup_community(db, admin, 2)
    await db.commit()
    await db.close()

    async with _api_client(admin) as client:
        created = await client.post(
            f"/communities/{community.id}/policy-overrides",
            json={"rule_id": "S1", "threshold": 0.75, "severity": "warn"},
        )
        listed = await client.get(f"/communities/{community.id}/policy-overrides")
    assert created.status_code == 201, created.text
    assert created.json()["rule_id"] == "S1"
    assert listed.status_code == 200, listed.text
    assert listed.json() == [
        {"rule_id": "S1", "threshold": 0.75, "severity": "warn"}
    ]


async def test_policy_override_requires_admin(db):
    admin, member = await _create_users(db, 2)
    _collab, community = await _setup_community(db, admin, 2)
    await db.commit()
    await db.close()

    async with _api_client(member) as client:
        response = await client.post(
            f"/communities/{community.id}/policy-overrides",
            json={"rule_id": "S1", "threshold": 0.75, "severity": "warn"},
        )
    assert response.status_code == 403


async def test_create_and_list_opportunity(db):
    admin, _member = await _create_users(db, 2)
    _collab, community = await _setup_community(db, admin, 2)
    await db.commit()
    await db.close()

    async with _api_client(admin) as client:
        california = await client.post(
            f"/communities/{community.id}/opportunities",
            json={"title": "California role", "state": "CA"},
        )
        await client.post(
            f"/communities/{community.id}/opportunities",
            json={"title": "New York role", "state": "NY"},
        )
        listed = await client.get("/opportunities?state=CA")
    assert california.status_code == 201, california.text
    assert california.json()["status"] == "open"
    assert listed.status_code == 200, listed.text
    assert [item["title"] for item in listed.json()] == ["California role"]


async def test_apply_opportunity_score_gate(db):
    user, _member = await _create_users(db, 2)
    _collab, community = await _setup_community(db, user, 2)
    opportunity = Opportunity(
        id=str(uuid.uuid4()),
        community_id=community.id,
        title="High-trust role",
        created_by=user.id,
        created_at=datetime.now(timezone.utc),
        min_trust_score=700,
    )
    db.add(opportunity)
    db.add(Evaluation(
        id=str(uuid.uuid4()),
        system_id=user.id,
        timestamp=datetime.now(timezone.utc),
        signals_json={},
        policy_results_json=[],
        risk_tier="high",
        trust_score=350,
        uncertainty=0.1,
        trusted=False,
    ))
    await db.commit()
    await db.close()

    async with _api_client(user) as client:
        response = await client.post(f"/opportunities/{opportunity.id}/apply")
    assert response.status_code == 403


async def test_apply_opportunity_success(db):
    user, _member = await _create_users(db, 2)
    _collab, community = await _setup_community(db, user, 2)
    opportunity = Opportunity(
        id=str(uuid.uuid4()),
        community_id=community.id,
        title="Policy-compliant role",
        created_by=user.id,
        created_at=datetime.now(timezone.utc),
        min_trust_score=700,
        required_rules=["S1", "S2"],
    )
    db.add(opportunity)
    db.add(Evaluation(
        id=str(uuid.uuid4()),
        system_id=user.id,
        timestamp=datetime.now(timezone.utc),
        signals_json={},
        policy_results_json=[
            {"rule_id": "S1", "result": "pass"},
            {"rule_id": "S2", "result": "pass"},
        ],
        risk_tier="low",
        trust_score=850,
        uncertainty=0.1,
        trusted=True,
    ))
    await db.commit()
    opportunity_id = opportunity.id
    await db.close()

    async with _api_client(user) as client:
        response = await client.post(f"/opportunities/{opportunity_id}/apply")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "applied"}


async def test_community_members_leaderboard(db):
    users = await _create_users(db, 3)
    _collab, community = await _setup_community(db, users[0], 3)
    for user, score in zip(users, (900, 400, 0), strict=True):
        db.add(Evaluation(
            id=str(uuid.uuid4()),
            system_id=user.id,
            timestamp=datetime.now(timezone.utc),
            signals_json={},
            policy_results_json=[],
            risk_tier="low",
            trust_score=score,
            uncertainty=0.1,
            trusted=score >= 700,
        ))
    await db.commit()
    await db.close()

    async with _api_client(users[0]) as client:
        response = await client.get(f"/communities/{community.id}/members")
    assert response.status_code == 200, response.text
    leaderboard = response.json()
    assert [entry["user_id"] for entry in leaderboard] == [
        users[0].id, users[1].id, users[2].id
    ]
    assert [entry["rank"] for entry in leaderboard] == [1, 2, 3]
    assert [entry["effective_score"] for entry in leaderboard] == pytest.approx(
        [900, 400, 0], abs=0.1
    )


async def test_score_chart_not_found(client):
    r = await client.get("/chart/nonexistent")
    assert r.status_code == 404   