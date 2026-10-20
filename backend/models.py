import os
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String, event, Integer
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://neondb_owner:npg_w8XAUEeYh4QP@ep-autumn-fire-b4xvmij2-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass




class System(Base):
    __tablename__ = "systems"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)   




class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    system_id: Mapped[str] = mapped_column(ForeignKey("systems.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    signals_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    policy_results_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    risk_tier: Mapped[str] = mapped_column(String(16))
    trust_score: Mapped[float] = mapped_column(Float)
    uncertainty: Mapped[float] = mapped_column(Float)
    trusted: Mapped[bool] = mapped_column(Boolean)


class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    sutra: Mapped[str] = mapped_column(String(100))
    rule_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String(16))
    nist_ref: Mapped[str] = mapped_column(String(32))
    nist_characteristic: Mapped[str] = mapped_column(String(100))

class Collab(Base):
    __tablename__ = "collabs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    focus: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String, default="")
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")  # "active" | "community"
    community_id: Mapped[str | None] = mapped_column(String, ForeignKey("communities.id"))
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

# In models.py, Community class
community_type: Mapped[str] = mapped_column(String(32), default="general")
# Values: "research" | "policy" | "industry" | "academic" | "general"   

class Community(Base):
    __tablename__ = "communities"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    focus: Mapped[str] = mapped_column(String(100), default="")
    city: Mapped[str] = mapped_column(String(100), default="multi")
    state: Mapped[str] = mapped_column(String(100), default="")
    country: Mapped[str] = mapped_column(String(2), default="IN")
    min_members: Mapped[int] = mapped_column(Integer, default=10)
    admin_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"))
    moderator_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"))
    voting_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phase: Mapped[str] = mapped_column(String(16), default="growing")  # "growing" | "voting" | "active"
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 90-day admin review
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollabMember(Base):
    __tablename__ = "collab_members"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    collab_id: Mapped[str] = mapped_column(String, ForeignKey("collabs.id"), index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")  # "member" | "moderator" | "admin"
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # free exit


class Vote(Base):
    __tablename__ = "votes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    community_id: Mapped[str] = mapped_column(String, ForeignKey("communities.id"), index=True)
    voter_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    candidate_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16))  # "admin" | "moderator"
    cast_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommunityInvite(Base):
    __tablename__ = "community_invites"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    community_id: Mapped[str] = mapped_column(String, ForeignKey("communities.id"), index=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    invited_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)   


class PolicyOverride(Base):
    __tablename__ = "policy_overrides"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    community_id: Mapped[str] = mapped_column(
        String, ForeignKey("communities.id"), index=True, nullable=False
    )
    rule_id: Mapped[str] = mapped_column(String(16), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    community_id: Mapped[str] = mapped_column(
        String, ForeignKey("communities.id"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String, default="", nullable=False)
    scope: Mapped[str] = mapped_column(String(16), default="remote", nullable=False)
    city: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    state: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    min_trust_score: Mapped[float] = mapped_column(Float, default=500, nullable=False)
    required_rules: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    domain: Mapped[str] = mapped_column(String(32), default="general", nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)


class OpportunityApplication(Base):
    __tablename__ = "opportunity_applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("opportunities.id"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), index=True, nullable=False
    )
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)



async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all) 

def init_db(connection: Connection) -> None:
    Base.metadata.create_all(bind=connection)

@event.listens_for(Session, "before_flush")
def prevent_evaluation_mutation(session: Session, *_: object) -> None:
    if any(isinstance(row, Evaluation) for row in session.dirty | session.deleted):
        raise ValueError("Evaluation records are append-only")


async def get_session():
    async with async_session() as session:
        yield session



 