from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from investiq.db.base import Base


class Course(Base):
    __tablename__ = "learning_courses"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(1000))


class Lesson(Base):
    __tablename__ = "learning_lessons"
    __table_args__ = (
        UniqueConstraint("course_id", "position"),
        CheckConstraint("position > 0 AND xp BETWEEN 1 AND 1000", name="lesson_values"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_courses.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    xp: Mapped[int] = mapped_column(Integer)


class LessonVersion(Base):
    __tablename__ = "learning_lesson_versions"
    __table_args__ = (
        UniqueConstraint("lesson_id", "version"),
        UniqueConstraint("id", "lesson_id"),
        CheckConstraint(
            "version > 0 AND jsonb_array_length(questions) BETWEEN 1 AND 20", name="version_values"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_lessons.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(160))
    paragraphs: Mapped[list[str]] = mapped_column(JSONB)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Enrollment(Base):
    __tablename__ = "learning_enrollments"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_courses.id", ondelete="RESTRICT"), primary_key=True
    )
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuizAttempt(Base):
    __tablename__ = "learning_quiz_attempts"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key"),
        UniqueConstraint("id", "user_id", "lesson_id"),
        ForeignKeyConstraint(
            ["version_id", "lesson_id"],
            ["learning_lesson_versions.id", "learning_lesson_versions.lesson_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "xp_awarded BETWEEN 0 AND 1000 AND (xp_awarded = 0 OR passed)", name="attempt_xp"
        ),
        CheckConstraint(
            "total BETWEEN 1 AND 20 AND correct_count BETWEEN 0 AND total "
            "AND passed = (correct_count = total)",
            name="score",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    lesson_id: Mapped[UUID] = mapped_column(ForeignKey("learning_lessons.id", ondelete="RESTRICT"))
    version_id: Mapped[UUID] = mapped_column()
    idempotency_key: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    correct_count: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column()
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class QuizAnswer(Base):
    __tablename__ = "learning_quiz_answers"
    __table_args__ = (CheckConstraint("choice BETWEEN 0 AND 9", name="answer_choice"),)
    attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_quiz_attempts.id", ondelete="RESTRICT"), primary_key=True
    )
    question_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    choice: Mapped[int] = mapped_column(Integer)
    correct: Mapped[bool] = mapped_column()


class LessonCompletion(Base):
    __tablename__ = "learning_completions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["attempt_id", "user_id", "lesson_id"],
            [
                "learning_quiz_attempts.id",
                "learning_quiz_attempts.user_id",
                "learning_quiz_attempts.lesson_id",
            ],
            ondelete="RESTRICT",
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_lessons.id", ondelete="RESTRICT"), primary_key=True
    )
    attempt_id: Mapped[UUID] = mapped_column(unique=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class XpEvent(Base):
    __tablename__ = "learning_xp_events"
    __table_args__ = (
        UniqueConstraint("user_id", "lesson_id"),
        ForeignKeyConstraint(
            ["attempt_id", "user_id", "lesson_id"],
            [
                "learning_quiz_attempts.id",
                "learning_quiz_attempts.user_id",
                "learning_quiz_attempts.lesson_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount BETWEEN 1 AND 1000", name="xp_amount"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    lesson_id: Mapped[UUID] = mapped_column(ForeignKey("learning_lessons.id", ondelete="RESTRICT"))
    attempt_id: Mapped[UUID] = mapped_column(unique=True)
    amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LearningDay(Base):
    __tablename__ = "learning_days"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LearningAchievement(Base):
    __tablename__ = "learning_achievements"
    __table_args__ = (
        CheckConstraint(
            "code IN ('first_lesson', 'first_course', 'three_day_streak')", name="achievement_code"
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
