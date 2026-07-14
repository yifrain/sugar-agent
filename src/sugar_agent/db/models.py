"""Database models for Sugar Agent."""

import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Message(Base):
    """Stores all chat messages (inbound and outbound)."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    from_user: Mapped[str] = mapped_column(String(128), index=True)
    from_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(String(20))  # user, assistant, system
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string
    is_proactive: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationship to blood glucose readings
    glucose_readings: Mapped[list["BloodGlucose"]] = relationship(
        back_populates="source_message", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role={self.role}, from={self.from_name})>"


class BloodGlucose(Base):
    """Blood glucose readings extracted from messages or manually entered."""

    __tablename__ = "blood_glucose"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # When the reading was taken
    value_mmol: Mapped[float] = mapped_column(Float)  # Normalized to mmol/L
    context: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )  # fasting, before_meal, after_meal, bedtime, random
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_message_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("messages.id"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    source_message: Mapped[Optional["Message"]] = relationship(back_populates="glucose_readings")

    def __repr__(self) -> str:
        return f"<BloodGlucose(id={self.id}, value={self.value_mmol}, context={self.context})>"


class Memory(Base):
    """Long-term memories about the user, preferences, events, etc."""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )  # love, health, preference, habit, fact, event
    tags: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Comma-separated
    importance: Mapped[int] = mapped_column(Integer, default=3)  # 1-5
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    source_message_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("messages.id"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Memory(id={self.id}, category={self.category}, content={self.content[:50]}...)>"


class ProactiveLog(Base):
    """Log of proactively sent messages (weather, check-ins, etc.)."""

    __tablename__ = "proactive_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(String(128), index=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, sent, failed
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ProactiveLog(id={self.id}, task={self.task_name}, status={self.status})>"


class ConversationSummary(Base):
    """Condensed summaries of older conversation segments to manage context window."""

    __tablename__ = "conversation_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    summary: Mapped[str] = mapped_column(Text)
    key_points: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    first_message_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("messages.id"), nullable=True
    )
    last_message_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("messages.id"), nullable=True
    )
    last_message_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ConversationSummary(id={self.id}, messages={self.message_count})>"


def init_db(db_url: str = "sqlite+aiosqlite:///data/sugar-agent.db"):
    """Create engine and tables. Uses aiosqlite for async support."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    # Resolve relative path to absolute
    if db_url.startswith("sqlite+aiosqlite:///./"):
        db_path = db_url.replace("sqlite+aiosqlite:///./", "")
        from pathlib import Path as _Path

        project_root = _Path(__file__).parent.parent.parent
        abs_path = project_root / db_path
        db_url = f"sqlite+aiosqlite:///{abs_path}"

    engine = create_async_engine(db_url, echo=False)

    return engine


async def create_tables(engine):
    """Create all tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
