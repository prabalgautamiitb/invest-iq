from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base


class PortfolioDraft(Base):
    __tablename__ = "portfolio_drafts"
    __table_args__ = (
        CheckConstraint("revision > 0", name="revision"),
        CheckConstraint("mode IN ('quantity','weight')", name="mode"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("contest_memberships.id", ondelete="RESTRICT"), unique=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(8))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DraftPosition(Base):
    __tablename__ = "portfolio_draft_positions"
    __table_args__ = (
        CheckConstraint(
            "(quantity IS NOT NULL AND quantity BETWEEN 1 AND 1000000000 AND weight_pct "
            "IS NULL) OR (quantity IS NULL AND weight_pct IS NOT NULL AND weight_pct > "
            "0 AND weight_pct <= 100 AND weight_pct <> 'NaN'::numeric)",
            name="allocation",
        ),
    )
    draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_drafts.id", ondelete="CASCADE"), primary_key=True
    )
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), primary_key=True
    )
    quantity: Mapped[int | None] = mapped_column(BigInteger)
    weight_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))


class PortfolioSubmission(Base):
    __tablename__ = "portfolio_submissions"
    __table_args__ = (
        UniqueConstraint("id", "membership_id", name="uq_submission_id_member"),
        UniqueConstraint("membership_id", "version"),
        UniqueConstraint("membership_id", "idempotency_key", name="uq_submission_membership_key"),
        UniqueConstraint("draft_id", "draft_revision"),
        ForeignKeyConstraint(
            ["membership_id", "rule_id"],
            ["contest_memberships.id", "contest_memberships.rule_id"],
            name="fk_submission_membership_rule",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version > 0 AND draft_revision > 0", name="versions"),
        CheckConstraint(
            "capital > 0 AND notional > 0 AND fee >= 0 AND cash >= 0 AND capital = "
            "notional + fee + cash AND capital <> 'NaN'::numeric AND notional <> "
            "'NaN'::numeric AND fee <> 'NaN'::numeric AND cash <> 'NaN'::numeric",
            name="accounting",
        ),
        CheckConstraint(
            "benchmark_price > 0 AND benchmark_price <> 'NaN'::numeric", name="benchmark"
        ),
        CheckConstraint("pricing_as_of < locks_at AND submitted_at < locks_at", name="before_lock"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("contest_memberships.id", ondelete="RESTRICT"), index=True
    )
    rule_id: Mapped[UUID] = mapped_column(
        ForeignKey("contest_rule_versions.id", ondelete="RESTRICT")
    )
    draft_id: Mapped[UUID] = mapped_column(ForeignKey("portfolio_drafts.id", ondelete="RESTRICT"))
    draft_revision: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    preview_hash: Mapped[str] = mapped_column(String(64))
    capital: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    notional: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    fee: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    cash: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    benchmark_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("price_snapshots.id", ondelete="RESTRICT")
    )
    benchmark_price: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    benchmark_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB)
    price_session_date: Mapped[date] = mapped_column(Date)
    calendar_version: Mapped[str] = mapped_column(String(60))
    pricing_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    locks_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)
    calculation_version: Mapped[str] = mapped_column(String(40))


class SubmissionHolding(Base):
    __tablename__ = "portfolio_submission_holdings"
    __table_args__ = (
        CheckConstraint(
            "quantity > 0 AND price > 0 AND notional = quantity * price AND price <> "
            "'NaN'::numeric AND notional <> 'NaN'::numeric",
            name="accounting",
        ),
        CheckConstraint("source_published_at >= observed_at", name="publication"),
    )
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_submissions.id", ondelete="RESTRICT"), primary_key=True
    )
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), primary_key=True
    )
    price_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("price_snapshots.id", ondelete="RESTRICT")
    )
    symbol: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    notional: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(60))
    dataset_version: Mapped[str] = mapped_column(String(40))
