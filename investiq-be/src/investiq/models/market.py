from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base


class Sector(Base):
    __tablename__ = "sectors"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("exchange", "symbol"),
        CheckConstraint("exchange = 'NSE'", name="exchange"),
        CheckConstraint("kind IN ('equity', 'benchmark')", name="kind"),
        CheckConstraint("market_cap IN ('large', 'mid', 'small')", name="market_cap"),
        CheckConstraint(
            "(kind = 'equity' AND sector_id IS NOT NULL AND market_cap IS NOT NULL "
            "AND currency = 'INR') OR (kind = 'benchmark' AND sector_id IS NULL "
            "AND market_cap IS NULL AND currency = 'POINTS')",
            name="classification",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(String(150))
    exchange: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(12))
    currency: Mapped[str] = mapped_column(String(6))
    sector_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sectors.id", ondelete="RESTRICT"), index=True
    )
    market_cap: Mapped[str | None] = mapped_column(String(8), index=True)
    active: Mapped[bool] = mapped_column(default=True, server_default="true")
    data_kind: Mapped[str] = mapped_column(String(10), default="fixture")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExchangeSession(Base):
    __tablename__ = "exchange_sessions"
    __table_args__ = (
        UniqueConstraint("exchange", "session_date"),
        CheckConstraint("status IN ('open', 'closed', 'unsupported')", name="status"),
        CheckConstraint(
            "(status = 'open' AND opens_at IS NOT NULL AND closes_at IS NOT NULL "
            "AND available_at IS NOT NULL AND closes_at > opens_at "
            "AND available_at >= closes_at) OR (status <> 'open' AND opens_at IS NULL "
            "AND closes_at IS NULL AND available_at IS NULL)",
            name="times",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    exchange: Mapped[str] = mapped_column(String(10))
    session_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12))
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(150))
    calendar_version: Mapped[str] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(200))


class MarketExclusion(Base):
    __tablename__ = "market_exclusions"
    __table_args__ = (CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="dates"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), index=True
    )
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(150))
    source: Mapped[str] = mapped_column(String(80))


class IngestionRun(Base):
    __tablename__ = "market_ingestion_runs"
    __table_args__ = (
        UniqueConstraint("provider", "dataset_version", "session_date"),
        CheckConstraint("status IN ('succeeded', 'failed')", name="status"),
        CheckConstraint("attempts > 0 AND point_count >= 0", name="counts"),
        CheckConstraint(
            "(status = 'succeeded' AND content_hash IS NOT NULL AND error_code IS NULL) "
            "OR (status = 'failed' AND error_code IS NOT NULL)",
            name="result",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(60))
    dataset_version: Mapped[str] = mapped_column(String(40))
    session_date: Mapped[date] = mapped_column(Date)
    data_kind: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(12))
    attempts: Mapped[int] = mapped_column(Integer)
    point_count: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__ = (
        UniqueConstraint("run_id", "instrument_id"),
        CheckConstraint("close > 0 AND close <> 'NaN'::numeric", name="positive_close"),
        CheckConstraint("source_published_at >= observed_at", name="publication"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_ingestion_runs.id", ondelete="RESTRICT"), index=True
    )
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), index=True
    )
    session_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
