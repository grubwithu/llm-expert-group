from __future__ import annotations

from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine
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
    opening_statement: Mapped[str] = mapped_column(Text)
    expert_responses_json: Mapped[str] = mapped_column(Text)
    chairman_summary: Mapped[str] = mapped_column(Text)
    human_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    human_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[CouncilSession] = relationship(back_populates="rounds")


class Database:
    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def session(self) -> Generator[Session, None, None]:
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()
