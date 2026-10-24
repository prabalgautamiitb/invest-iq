from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base


class MartinConversation(Base):
    __tablename__ = "martin_conversations"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        CheckConstraint("mode IN ('learning','performance')", name="mode"),
        CheckConstraint("mode = 'performance' OR contest_id IS NULL", name="scope"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(80))
    mode: Mapped[str] = mapped_column(String(12))
    contest_id: Mapped[UUID | None] = mapped_column(ForeignKey("contests.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class MartinTurn(Base):
    __tablename__ = "martin_turns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["martin_conversations.id", "martin_conversations.user_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("user_id", "request_key"),
        CheckConstraint("char_length(question) BETWEEN 1 AND 1000", name="question"),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')", name="status"
        ),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="attempts"),
        CheckConstraint("(status = 'succeeded') = (answer IS NOT NULL)", name="answer"),
        CheckConstraint(
            "(status = 'running') = (lease_token IS NOT NULL AND leased_until IS NOT NULL)",
            name="lease",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[UUID] = mapped_column(index=True)
    request_key: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(String(1000))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(
        String(12), default="queued", server_default="queued", index=True
    )
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    lease_token: Mapped[UUID | None] = mapped_column()
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(40))
    input_tokens: Mapped[int | None] = mapped_column()
    output_tokens: Mapped[int | None] = mapped_column()
    latency_ms: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
