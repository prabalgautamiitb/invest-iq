from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "(subscription_plan IS NULL AND subscription_starts_at IS NULL "
            "AND subscription_ends_at IS NULL) OR "
            "(subscription_plan IS NOT NULL AND subscription_plan IN ('student', 'standard') "
            "AND subscription_starts_at IS NOT NULL AND subscription_ends_at IS NOT NULL "
            "AND subscription_ends_at > subscription_starts_at)",
            name="subscription",
        ),
        CheckConstraint("role IN ('user', 'admin')", name="role"),
        CheckConstraint("weekly_goal IN (35, 75, 105, 210)", name="weekly_goal"),
        CheckConstraint("email = lower(email)", name="normalized_email"),
        CheckConstraint("length(name) BETWEEN 1 AND 70", name="name_length"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    name: Mapped[str] = mapped_column(String(70))
    role: Mapped[str] = mapped_column(String(10), default="user", server_default="user")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    subscription_plan: Mapped[str | None] = mapped_column(String(12))
    subscription_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscription_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weekly_goal: Mapped[int] = mapped_column(Integer, default=75, server_default="75")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProfilePhoto(Base):
    __tablename__ = "profile_photos"
    __table_args__ = (
        CheckConstraint("octet_length(image) BETWEEN 1 AND 262144", name="image_size"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[UUID] = mapped_column(default=uuid4)
    image: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (CheckConstraint("expires_at > created_at", name="expiry"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountToken(Base):
    __tablename__ = "account_tokens"
    __table_args__ = (
        CheckConstraint("purpose IN ('verification', 'password_reset')", name="purpose"),
        CheckConstraint("expires_at > created_at", name="expiry"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Preferences(Base):
    __tablename__ = "user_preferences"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    contest: Mapped[bool] = mapped_column(default=True, server_default="true")
    ranks: Mapped[bool] = mapped_column(default=True, server_default="true")
    ai: Mapped[bool] = mapped_column(default=True, server_default="true")
    replies: Mapped[bool] = mapped_column(default=False, server_default="false")
    digest: Mapped[bool] = mapped_column(default=True, server_default="true")


class Privacy(Base):
    __tablename__ = "user_privacy"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    public: Mapped[bool] = mapped_column(default=False, server_default="false")
    holdings: Mapped[bool] = mapped_column(default=False, server_default="false")


class QuestionSet(Base):
    __tablename__ = "onboarding_question_sets"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OnboardingResponse(Base):
    __tablename__ = "onboarding_responses"
    __table_args__ = (
        CheckConstraint(
            "experience IN ('beginner', 'intermediate', 'advanced')", name="experience"
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    question_set_id: Mapped[UUID] = mapped_column(
        ForeignKey("onboarding_question_sets.id", ondelete="RESTRICT"), primary_key=True
    )
    answers: Mapped[dict[str, str]] = mapped_column(JSONB)
    experience: Mapped[str] = mapped_column(String(20))
    learning_profile: Mapped[str] = mapped_column(String(40))
    classification_version: Mapped[int] = mapped_column(Integer, default=1)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
