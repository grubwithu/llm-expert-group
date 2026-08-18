from __future__ import annotations

from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class CouncilSession(Base):
    __tablename__ = "council_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    topic: Mapped[str] = mapped_column(Text)
    repo_path: Mapped[str] = mapped_column(Text)
    repo_commit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    repo_context: Mapped[str] = mapped_column(Text)
    repo_context_truncated: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(40), default="ready")
    current_round: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    rounds: Mapped[list["CouncilRound"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="CouncilRound.number"
    )


class CouncilRound(Base):
    __tablename__ = "council_rounds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("council_sessions.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32), default="discussion")
    graph_thread_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    opening_statement: Mapped[str] = mapped_column(Text)
    expert_responses_json: Mapped[str] = mapped_column(Text)
    chairman_summary: Mapped[str] = mapped_column(Text)
    human_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    human_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[CouncilSession] = relationship(back_populates="rounds")
    secretary_interactions: Mapped[list["SecretaryInteractionRow"]] = relationship(
        back_populates="round", cascade="all, delete-orphan", order_by="SecretaryInteractionRow.sequence"
    )


class CouncilRoundRun(Base):
    """Durable execution record for an asynchronously streamed council round."""

    __tablename__ = "council_round_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("council_sessions.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32), default="discussion")
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    opening_statement: Mapped[str] = mapped_column(Text, default="")
    expert_responses_json: Mapped[str] = mapped_column(Text, default="[]")
    chairman_summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CouncilRoundEvent(Base):
    __tablename__ = "council_round_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("council_round_runs.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(80))
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SecretaryInteractionRow(Base):
    __tablename__ = "secretary_interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    round_id: Mapped[str] = mapped_column(ForeignKey("council_rounds.id", ondelete="CASCADE"), index=True)
    requester_role: Mapped[str] = mapped_column(String(20))
    requester_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phase: Mapped[str] = mapped_column(String(20))
    sequence: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    limitations_json: Mapped[str] = mapped_column(Text, default="[]")
    tool_trace_json: Mapped[str] = mapped_column(Text, default="[]")
    repo_commit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    round: Mapped["CouncilRound"] = relationship(back_populates="secretary_interactions")


class Database:
    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)
        # v0.1 databases predate graph_thread_id. Keep the local SQLite upgrade
        # path self-contained instead of forcing users to delete council history.
        if str(self.engine.url).startswith("sqlite"):
            columns = {column["name"] for column in inspect(self.engine).get_columns("council_rounds")}
            if "graph_thread_id" not in columns:
                with self.engine.begin() as connection:
                    connection.exec_driver_sql("ALTER TABLE council_rounds ADD COLUMN graph_thread_id VARCHAR(180)")

    def session(self) -> Generator[Session, None, None]:
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()
