from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
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


class Contest(Base):
    __tablename__ = "contests"
    __table_args__ = (
        UniqueConstraint("owner_id", "creation_key"),
        CheckConstraint("organizer IN ('community', 'platform')", name="organizer"),
        CheckConstraint("organizer <> 'platform' OR visibility = 'public'", name="platform_public"),
        CheckConstraint("visibility IN ('public', 'private')", name="visibility"),
        CheckConstraint("level IN ('beginner', 'advanced', 'all')", name="level"),
        CheckConstraint(
            "status IN ('draft','scheduled','open','locked','running',"
            "'settling','completed','cancelled')",
            name="status",
        ),
        CheckConstraint("capacity BETWEEN 1 AND 10000", name="capacity"),
        CheckConstraint(
            "entry_opens_at < entry_closes_at AND entry_closes_at < starts_at "
            "AND starts_at < ends_at",
            name="schedule",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    organizer: Mapped[str] = mapped_column(
        String(12), index=True, default="community", server_default="community"
    )
    creation_key: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500))
    visibility: Mapped[str] = mapped_column(String(8), index=True)
    level: Mapped[str] = mapped_column(String(8), index=True)
    status: Mapped[str] = mapped_column(String(12), index=True, default="draft")
    capacity: Mapped[int] = mapped_column(Integer)
    entry_opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContestRules(Base):
    __tablename__ = "contest_rule_versions"
    __table_args__ = (
        UniqueConstraint("contest_id", "version"),
        UniqueConstraint("contest_id", "id", name="uq_contest_rules_contest_id_id"),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint(
            "capital > 0 AND capital <= 100000000 AND capital <> 'NaN'::numeric", name="capital"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    contest_id: Mapped[UUID] = mapped_column(
        ForeignKey("contests.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    # Immutable typed snapshot. Capital uses NUMERIC; JSON limits/costs use integer basis points.
    capital: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContestMembership(Base):
    __tablename__ = "contest_memberships"
    __table_args__ = (
        UniqueConstraint("id", "rule_id", name="uq_membership_id_rule"),
        UniqueConstraint("contest_id", "user_id"),
        ForeignKeyConstraint(
            ["contest_id", "rule_id"],
            ["contest_rule_versions.contest_id", "contest_rule_versions.id"],
            ondelete="RESTRICT",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    contest_id: Mapped[UUID] = mapped_column(
        ForeignKey("contests.id", ondelete="RESTRICT"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    rule_id: Mapped[UUID] = mapped_column()
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContestInvitation(Base):
    __tablename__ = "contest_invitations"
    __table_args__ = (
        UniqueConstraint("contest_id", "email"),
        CheckConstraint("status IN ('pending','accepted','declined','revoked')", name="status"),
        CheckConstraint("expires_at > created_at", name="expiry"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    contest_id: Mapped[UUID] = mapped_column(
        ForeignKey("contests.id", ondelete="RESTRICT"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ContestEligibleInstrument(Base):
    __tablename__ = "contest_eligible_instruments"
    rule_id: Mapped[UUID] = mapped_column(
        ForeignKey("contest_rule_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
