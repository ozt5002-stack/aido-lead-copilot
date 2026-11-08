"""Database layer: models, engine, session, startup migration and seeding.

Postgres on Railway (DATABASE_URL from the plugin) or SQLite locally. The
schema is created at start with `create_all`; `schema_version` records which
version is live so a later real migration tool has somewhere to start.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import ROOT, settings
from .stage import DOMAIN_IDS

SCHEMA_VERSION = 2  # 2: the bakery tables replaced by leads (docs/02-architecture.md); needs a fresh database


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)  # plain text shown in the UI
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Run(Base):
    """One model turn: the record behind the cost cap, the digest and the runbook."""

    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    model: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | refusal | error | aborted | capped
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_names: Mapped[str] = mapped_column(String(200), default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


PIPELINE_STATUSES = ("new", "contacted", "meeting", "diagnosed", "proposal", "won", "lost")

# business_key() order (docs/02-architecture.md, "Data shapes"): Unicode-normalise, drop vowel marks and
# case; delete quote marks (so נדל"ן = נדלן and בע"מ = בעמ); remove a trailing legal suffix, even in
# brackets or with a dot; then the remaining punctuation becomes a space.
_QUOTES = re.compile("[\"'\u05f3\u05f4\u2018\u2019\u201c\u201d\u00b4`]")
_SUFFIX = re.compile(r"(?:^|[\s,.\-]+)\(?\s*(בעמ|ltd|inc|limited)\s*\.?\s*\)?[\s,.\-]*$")
_PUNCT = re.compile(r"[^\w\s]|_")


def business_key(name: str | None) -> str:
    """The dedup key for a business: 'אופק חנויות בע"מ.' and 'אופק  חנויות' are the same business.

    Returns "" when nothing is left (a name that is only a suffix); callers must refuse an empty key.
    """
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _QUOTES.sub("", text)
    text = " ".join(text.split())
    previous = None
    while previous != text:
        previous = text
        text = _SUFFIX.sub("", " " + text).strip()
    return " ".join(_PUNCT.sub(" ", text).split())


class Lead(Base):
    """One business: the lead and, once it exists, its diagnosis (docs/02-architecture.md, "Data shapes")."""

    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_name: Mapped[str] = mapped_column(String(120))
    business_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    employees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    total_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    strategy_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    management_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    systems_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    people_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    finance_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy_stage: Mapped[str | None] = mapped_column(String(12), nullable=True)
    management_stage: Mapped[str | None] = mapped_column(String(12), nullable=True)
    systems_stage: Mapped[str | None] = mapped_column(String(12), nullable=True)
    people_stage: Mapped[str | None] = mapped_column(String(12), nullable=True)
    finance_stage: Mapped[str | None] = mapped_column(String(12), nullable=True)
    pains: Mapped[str | None] = mapped_column(Text, nullable=True)
    pipeline_status: Mapped[str] = mapped_column(String(12), default="new", index=True)
    deal_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fictional: Mapped[bool] = mapped_column(Boolean, default=False)
    record_status: Mapped[str] = mapped_column(String(14), default="logged")  # logged | needs_a_look
    source_ref: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(String(8), default="chat", index=True)  # seed | chat
    logged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ---------------------------------------------------------------------------
# Engine and session
# ---------------------------------------------------------------------------

def make_engine(url: str | None = None):
    url = url or settings.database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Startup: schema, version, seed data
# ---------------------------------------------------------------------------

def init_db(bind=None, data_dir: Path | None = None) -> dict:
    """Create tables, record the schema version, seed reference data if empty."""
    bind = bind or engine
    data_dir = data_dir or (ROOT / "data")
    Base.metadata.create_all(bind)
    report = {"schema_version": SCHEMA_VERSION, "leads_seeded": 0}
    with Session(bind) as db:
        if db.scalar(select(func.count()).select_from(SchemaVersion)) == 0:
            db.add(SchemaVersion(version=SCHEMA_VERSION))
            db.commit()
        if db.scalar(select(func.count()).select_from(Lead)) == 0:
            report["leads_seeded"] = seed_leads(db, data_dir / "leads.csv")
    return report


def seed_leads(db: Session, path: Path) -> int:
    """Load the fictional leads (scripts/generate_leads.py). Stages come from the file, which got them from app/stage.py."""
    if not path.exists():
        return 0

    def num(v, cast):
        return cast(v) if v not in ("", None) else None

    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            row = {
                "business_name": r["business_name"], "business_key": business_key(r["business_name"]),
                "industry": r["industry"] or None, "employees": num(r["employees"], int),
                "lead_date": date.fromisoformat(r["lead_date"]), "total_score": num(r["total_score"], int),
                "stage": r["stage"] or None, "pains": r["pains"] or None, "pipeline_status": r["pipeline_status"],
                "deal_value": num(r["deal_value"], int), "fictional": r["fictional"] == "true",
                "record_status": "logged", "origin": "seed",
            }
            for d in DOMAIN_IDS:
                row[f"{d}_avg"] = num(r[f"{d}_avg"], float)
                row[f"{d}_stage"] = r[f"{d}_stage"] or None
            rows.append(row)
    db.execute(Lead.__table__.insert(), rows)
    db.commit()
    return len(rows)
