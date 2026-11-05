"""Virtual INR funds, separate from reward coins and pre-wallet contest activity."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base


class VirtualWallet(Base):
    __tablename__ = "virtual_wallets"
    __table_args__ = (
        CheckConstraint("available >= 0 AND available <> 'NaN'::numeric", name="available"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    available: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WalletPosition(Base):
    __tablename__ = "wallet_positions"
    __table_args__ = (
        CheckConstraint("capital > 0 AND capital <> 'NaN'::numeric", name="capital"),
        CheckConstraint("current_value >= 0 AND current_value <> 'NaN'::numeric", name="value"),
        CheckConstraint("status IN ('active','settled','refunded')", name="status"),
        CheckConstraint(
            "(status = 'active' AND released_at IS NULL) OR "
            "(status <> 'active' AND released_at IS NOT NULL)",
            name="release",
        ),
    )
    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("contest_memberships.id", ondelete="RESTRICT"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("virtual_wallets.user_id", ondelete="RESTRICT"), index=True
    )
    capital: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    current_value: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    status: Mapped[str] = mapped_column(String(10), default="active")
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("valuation_runs.id", ondelete="RESTRICT")
    )
    session_date: Mapped[date | None] = mapped_column()
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WalletEntry(Base):
    __tablename__ = "wallet_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "event_key"),
        CheckConstraint(
            "kind IN ('opening','reservation','settlement','cancellation','no_submission')",
            name="kind",
        ),
        CheckConstraint(
            "available_after >= 0 AND available_after <> 'NaN'::numeric", name="balance"
        ),
        CheckConstraint("amount <> 'NaN'::numeric", name="amount"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("virtual_wallets.user_id", ondelete="RESTRICT"), index=True
    )
    membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("contest_memberships.id", ondelete="RESTRICT")
    )
    event_key: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    available_after: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
