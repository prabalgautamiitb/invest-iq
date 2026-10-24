from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base


class CoachJob(Base):
    __tablename__ = "coach_jobs"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        UniqueConstraint(
            "user_id",
            "record_id",
            "provider",
            "model",
            "prompt_version",
            "generation",
            name="uq_coach_source_policy",
        ),
        CheckConstraint(
            "status IN ('queued','running','retry','succeeded','failed')", name="status"
        ),
        CheckConstraint("generation > 0", name="generation"),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="attempts"),
        CheckConstraint("provider IN ('ollama','gemini')", name="provider"),
        CheckConstraint(
            "(status = 'running') = (lease_token IS NOT NULL AND leased_until IS NOT NULL)",
            name="lease",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    contest_id: Mapped[UUID] = mapped_column(ForeignKey("contests.id"), index=True)
    record_id: Mapped[UUID] = mapped_column(ForeignKey("valuation_records.id"))
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(40))
    evidence_hash: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(12), default="queued", server_default="queued", index=True
    )
    generation: Mapped[int] = mapped_column(default=1, server_default="1")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(40))
    lease_token: Mapped[UUID | None] = mapped_column()
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CoachRequest(Base):
    __tablename__ = "coach_requests"
    __table_args__ = (
        ForeignKeyConstraint(["job_id", "user_id"], ["coach_jobs.id", "coach_jobs.user_id"]),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))


class CoachReport(Base):
    __tablename__ = "coach_reports"
    __table_args__ = (
        ForeignKeyConstraint(["job_id", "user_id"], ["coach_jobs.id", "coach_jobs.user_id"]),
    )
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CoachAttempt(Base):
    __tablename__ = "coach_attempts"
    __table_args__ = (
        CheckConstraint("number BETWEEN 1 AND 3", name="number"),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="input_tokens"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="output_tokens"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_ms"),
        CheckConstraint("estimated_cost_usd IS NULL OR estimated_cost_usd >= 0", name="cost"),
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("coach_jobs.id"), primary_key=True)
    number: Mapped[int] = mapped_column(primary_key=True)
    input_tokens: Mapped[int | None] = mapped_column()
    output_tokens: Mapped[int | None] = mapped_column()
    latency_ms: Mapped[int | None] = mapped_column()
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    error_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CoachReflection(Base):
    __tablename__ = "coach_reflections"
    __table_args__ = (
        UniqueConstraint("user_id", "request_key"),
        CheckConstraint("length(body) BETWEEN 1 AND 2000", name="body_length"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    contest_id: Mapped[UUID] = mapped_column(ForeignKey("contests.id"), index=True)
    request_key: Mapped[UUID] = mapped_column()
    body: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
