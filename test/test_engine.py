# test/test_engine.py
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from datetime import datetime, timezone
import models

# Create test engine FIRST, then patch models BEFORE importing app
test_engine = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

# Patch the session factory that app.py uses internally
models.async_session = TestSession

# NOW import app (it will pick up the patched session)
from app import app
from models import Base, User  # noqa: F401
from trust_engine.auth import create_token


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
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


async def test_protected_endpoint_rejects_missing_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as unauthenticated:
        r = await unauthenticated.get("/trust/nonexistent-system")
    assert r.status_code == 401


async def test_create_user(client):
    r = await client.post("/users", json={
        "name": " Ada Lovelace ",
        "email": "Ada@example.com",
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
    })
    duplicate = await client.post("/users", json={
        "name": "Another User",
        "email": "ADA@example.com",
    })

    assert first.status_code == 201
    assert duplicate.status_code == 409


async def test_create_user_rejects_invalid_email(client):
    r = await client.post("/users", json={
        "name": "Ada Lovelace",
        "email": "not-an-email",
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