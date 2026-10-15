from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String, event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine("sqlite+aiosqlite:///./governance.db", echo=False)
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



 