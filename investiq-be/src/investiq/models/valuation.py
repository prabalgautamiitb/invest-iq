from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base


class ValuationRun(Base):
    __tablename__ = "valuation_runs"
    __table_args__ = (
        UniqueConstraint("contest_id", "session_date"),
        CheckConstraint("status IN ('pending','blocked','succeeded')", name="status"),
        CheckConstraint("attempts > 0 AND participant_count >= 0", name="counts"),
        CheckConstraint(
            "(status = 'succeeded' AND evidence_hash IS NOT NULL AND error_code IS NULL) "
            "OR status <> 'succeeded'",
            name="outcome",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    contest_id: Mapped[UUID] = mapped_column(
        ForeignKey("contests.id", ondelete="RESTRICT"), index=True
    )
    session_date: Mapped[date] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12))
    attempts: Mapped[int] = mapped_column(Integer)
    participant_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    calculation_version: Mapped[str] = mapped_column(String(40), default="eod-valuation-v1")


class ValuationPrice(Base):
    __tablename__ = "valuation_prices"
    __table_args__ = (CheckConstraint("price > 0 AND price <> 'NaN'::numeric", name="price"),)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("valuation_runs.id", ondelete="RESTRICT"), primary_key=True
    )
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), primary_key=True
    )
    price_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("price_snapshots.id", ondelete="RESTRICT")
    )
    sector_id: Mapped[UUID | None] = mapped_column(ForeignKey("sectors.id", ondelete="RESTRICT"))
    symbol: Mapped[str] = mapped_column(String(30))
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(60))
    dataset_version: Mapped[str] = mapped_column(String(40))


class ValuationRecord(Base):
    __tablename__ = "valuation_records"
    __table_args__ = (
        UniqueConstraint("run_id", "membership_id"),
        UniqueConstraint("run_id", "rank", name="uq_valuation_run_rank"),
        ForeignKeyConstraint(
            ["submission_id", "membership_id"],
            ["portfolio_submissions.id", "portfolio_submissions.membership_id"],
            name="fk_valuation_submission_member",
            ondelete="RESTRICT",
        ),
        CheckConstraint("rank > 0 AND holding_count > 0 AND sector_count >= 0", name="counts"),
        CheckConstraint(
            "capital > 0 AND cash >= 0 AND fee >= 0 AND holdings_value > 0 "
            "AND total_value = holdings_value + cash AND pnl = total_value - capital "
            "AND peak_value >= total_value AND capital <> 'NaN'::numeric "
            "AND total_value <> 'NaN'::numeric",
            name="accounting",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("valuation_runs.id", ondelete="RESTRICT"), index=True
    )
    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("contest_memberships.id", ondelete="RESTRICT"), index=True
    )
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_submissions.id", ondelete="RESTRICT")
    )
    rank: Mapped[int] = mapped_column(Integer)
    capital: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    holdings_value: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    cash: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    fee: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    total_value: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    pnl: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    peak_value: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    return_pct: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    benchmark_return_pct: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    excess_return_pct: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    max_drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    largest_position_pct: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    concentration_hhi: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    holding_count: Mapped[int] = mapped_column(Integer)
    sector_count: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ContestFinalization(Base):
    __tablename__ = "contest_finalizations"
    contest_id: Mapped[UUID] = mapped_column(
        ForeignKey("contests.id", ondelete="RESTRICT"), primary_key=True
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("valuation_runs.id", ondelete="RESTRICT"), unique=True
    )
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
