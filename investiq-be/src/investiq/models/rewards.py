from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base


class CoinAccount(Base):
    __tablename__ = "coin_accounts"
    __table_args__ = (
        CheckConstraint(
            "balance >= 0 AND lifetime_earned >= balance AND entry_count >= 0",
            name="account_totals",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    lifetime_earned: Mapped[int] = mapped_column(BigInteger, default=0)
    entry_count: Mapped[int] = mapped_column(BigInteger, default=0)


class RewardTier(Base):
    __tablename__ = "reward_tiers"
    __table_args__ = (CheckConstraint("minimum_earned >= 0", name="tier_threshold"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    minimum_earned: Mapped[int] = mapped_column(BigInteger, unique=True)


class RewardItem(Base):
    __tablename__ = "reward_items"
    __table_args__ = (
        CheckConstraint("cost BETWEEN 1 AND 1000000 AND version > 0", name="item_values"),
        CheckConstraint("category IN ('digital','learning','merchandise')", name="item_category"),
        CheckConstraint("mode = 'sandbox'", name="item_mode"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(1000))
    category: Mapped[str] = mapped_column(String(20), index=True)
    cost: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(default=True)
    mode: Mapped[str] = mapped_column(String(10), default="sandbox", server_default="sandbox")


class RewardInventory(Base):
    __tablename__ = "reward_inventory"
    __table_args__ = (
        CheckConstraint(
            "capacity BETWEEN 0 AND 100000 AND remaining BETWEEN 0 AND capacity",
            name="inventory_counts",
        ),
    )
    item_id: Mapped[UUID] = mapped_column(
        ForeignKey("reward_items.id", ondelete="RESTRICT"), primary_key=True
    )
    capacity: Mapped[int] = mapped_column(Integer)
    remaining: Mapped[int] = mapped_column(Integer)


class Redemption(Base):
    __tablename__ = "reward_redemptions"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key"),
        UniqueConstraint("id", "user_id"),
        CheckConstraint(
            "cost BETWEEN 1 AND 1000000 AND balance_after >= 0 AND item_version > 0",
            name="redemption_values",
        ),
        CheckConstraint("status = 'sandbox_confirmed'", name="redemption_status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("coin_accounts.user_id", ondelete="RESTRICT"), index=True
    )
    item_id: Mapped[UUID] = mapped_column(
        ForeignKey("reward_items.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    item_version: Mapped[int] = mapped_column(Integer)
    item_name: Mapped[str] = mapped_column(String(160))
    cost: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(
        String(24), default="sandbox_confirmed", server_default="sandbox_confirmed"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class CoinLedger(Base):
    __tablename__ = "coin_ledger"
    __table_args__ = (
        UniqueConstraint("user_id", "sequence"),
        UniqueConstraint("user_id", "lesson_id", name="uq_coin_ledger_lesson"),
        UniqueConstraint("redemption_id"),
        ForeignKeyConstraint(
            ["user_id", "lesson_id"],
            ["learning_completions.user_id", "learning_completions.lesson_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["redemption_id", "user_id"],
            ["reward_redemptions.id", "reward_redemptions.user_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence > 0 AND balance_after >= 0", name="ledger_values"),
        CheckConstraint(
            "(kind = 'lesson_completion' AND delta = 50 AND lesson_id IS NOT NULL "
            "AND redemption_id IS NULL AND policy_version = 'lesson-coins-v1') OR "
            "(kind = 'redemption' AND delta < 0 AND lesson_id IS NULL "
            "AND redemption_id IS NOT NULL AND policy_version = 'sandbox-redemption-v1')",
            name="ledger_source",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("coin_accounts.user_id", ondelete="RESTRICT"), index=True
    )
    sequence: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(24))
    delta: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    policy_version: Mapped[str] = mapped_column(String(40))
    lesson_id: Mapped[UUID | None] = mapped_column()
    redemption_id: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
