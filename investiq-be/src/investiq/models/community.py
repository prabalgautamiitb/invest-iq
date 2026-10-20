from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base


class CommunityGroup(Base):
    __tablename__ = "community_groups"
    __table_args__ = (CheckConstraint("length(name) BETWEEN 3 AND 80", name="name_length"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    creator_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GroupMember(Base):
    __tablename__ = "community_members"
    group_id: Mapped[UUID] = mapped_column(ForeignKey("community_groups.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)


class CommunityContent(Base):
    __tablename__ = "community_content"
    __table_args__ = (
        CheckConstraint("length(body) BETWEEN 1 AND 4000", name="body_length"),
        CheckConstraint("kind IN ('discussion','idea','market','poll','comment')", name="kind"),
        CheckConstraint("state IN ('visible','deleted','hidden')", name="state"),
        CheckConstraint("(kind = 'comment') = (parent_id IS NOT NULL)", name="parent_kind"),
        CheckConstraint("(kind = 'poll') = (closes_at IS NOT NULL)", name="poll_close"),
        CheckConstraint(
            "jsonb_typeof(options) = 'array' AND ((kind = 'poll' "
            "AND jsonb_array_length(options) BETWEEN 2 AND 6) OR "
            "(kind <> 'poll' AND jsonb_array_length(options) = 0))",
            name="options",
        ),
        UniqueConstraint("author_id", "request_key"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    request_key: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("community_content.id"), index=True)
    group_id: Mapped[UUID | None] = mapped_column(ForeignKey("community_groups.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(String(4000))
    options: Mapped[list[str]] = mapped_column(JSONB, default=list)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(10), default="visible", server_default="visible")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class CommunityReaction(Base):
    __tablename__ = "community_reactions"
    content_id: Mapped[UUID] = mapped_column(ForeignKey("community_content.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)


class CommunitySave(Base):
    __tablename__ = "community_saves"
    content_id: Mapped[UUID] = mapped_column(ForeignKey("community_content.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)


class CommunityVote(Base):
    __tablename__ = "community_votes"
    __table_args__ = (CheckConstraint("option BETWEEN 0 AND 5", name="option"),)
    content_id: Mapped[UUID] = mapped_column(ForeignKey("community_content.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    option: Mapped[int] = mapped_column()


class CommunityReport(Base):
    __tablename__ = "community_reports"
    __table_args__ = (
        UniqueConstraint("content_id", "reporter_id"),
        CheckConstraint("length(reason) BETWEEN 5 AND 500", name="reason"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    content_id: Mapped[UUID] = mapped_column(ForeignKey("community_content.id"))
    reporter_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(500))
    resolved: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommunityModeration(Base):
    __tablename__ = "community_moderation"
    __table_args__ = (
        CheckConstraint("action IN ('hide','restore','dismiss')", name="action"),
        CheckConstraint("length(reason) BETWEEN 5 AND 500", name="reason"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    content_id: Mapped[UUID] = mapped_column(ForeignKey("community_content.id"))
    moderator_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
