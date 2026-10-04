import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Float, Integer, String, Text, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import API_ROOT

engine = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(40), default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    trusted_contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    home_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(40), default="")
    token: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=utcnow)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    amount: Mapped[float] = mapped_column(Float)
    recipient: Mapped[str] = mapped_column(String(80))
    method: Mapped[str] = mapped_column(String(20))
    prompt_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    outcome: Mapped[str] = mapped_column(String(20), default="allow")
    stage: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0)


class RiskCheck(Base):
    __tablename__ = "risk_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=utcnow)
    attempt_id: Mapped[str] = mapped_column(String(36), index=True)
    score: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(20))
    signals: Mapped[str] = mapped_column(Text, default="{}")
    reasons: Mapped[str] = mapped_column(Text, default="[]")
    stage: Mapped[int] = mapped_column(Integer, default=0)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempt_id: Mapped[str] = mapped_column(String(36), index=True)
    contact_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReasonBelief(Base):
    __tablename__ = "reason_beliefs"

    reason_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    successes: Mapped[int] = mapped_column(Integer, default=0)
    disputes: Mapped[int] = mapped_column(Integer, default=0)


class ReasonObservation(Base):
    __tablename__ = "reason_observations"

    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reason_id: Mapped[str] = mapped_column(String(40))
    target: Mapped[int] = mapped_column(Integer)


class Watcher(Base):
    __tablename__ = "watchers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name_en: Mapped[str] = mapped_column(String(80))
    name_es: Mapped[str] = mapped_column(String(80))
    signal: Mapped[str] = mapped_column(String(40))
    phrases: Mapped[str] = mapped_column(Text, default="[]")
    sentence_en: Mapped[str] = mapped_column(Text, default="")
    sentence_es: Mapped[str] = mapped_column(Text, default="")
    builtin: Mapped[int] = mapped_column(Integer, default=0)


class VitalsSample(Base):
    __tablename__ = "vitals_samples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, default=utcnow)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    pulse: Mapped[float] = mapped_column(Float)
    breathing: Mapped[float] = mapped_column(Float)


class FlaggedNumber(Base):
    """A phone number reported as a scam. Shared across every wallet, carrier,
    and credit union that reports into the same list."""

    __tablename__ = "flagged_numbers"

    number: Mapped[str] = mapped_column(String(32), primary_key=True)
    reports: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(32), default="community")
    reason_en: Mapped[str] = mapped_column(Text, default="")
    reason_es: Mapped[str] = mapped_column(Text, default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def configure(url: str) -> None:
    global engine, SessionLocal
    if url.startswith("sqlite") and ":memory:" not in url:
        path = url.split("///", 1)[-1]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    if engine is not None:
        engine.sync_engine.dispose()
    engine = create_async_engine(url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    assert engine is not None
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "postgresql":
            await _enable_tiger(conn)


async def _enable_tiger(conn) -> None:
    schema = (API_ROOT / "schema.sql").read_text(encoding="utf-8")
    statements = []
    for chunk in schema.split(";"):
        lines = [line for line in chunk.splitlines() if not line.strip().startswith("--")]
        statement = "\n".join(lines).strip()
        if statement:
            statements.append(statement)
    for statement in statements:
        try:
            await conn.execute(text(statement))
        except Exception:
            continue


def dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str, fallback: object) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def session_factory() -> async_sessionmaker[AsyncSession]:
    if SessionLocal is None:
        raise RuntimeError("Database is not configured")
    return SessionLocal
