"""Learning transactions. The user lock serializes awards across all lessons and sessions."""

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from investiq.core.errors import AppError
from investiq.core.security import Principal, now
from investiq.models.learning import (
    Course,
    Enrollment,
    LearningAchievement,
    LearningDay,
    Lesson,
    LessonCompletion,
    LessonVersion,
    QuizAnswer,
    QuizAttempt,
    XpEvent,
)
from investiq.schemas.learning import (
    AchievementOut,
    AttemptInput,
    AttemptOut,
    AttemptPage,
    CourseOut,
    CoursePage,
    FeedbackOut,
    LessonOut,
    LessonSummary,
    ProgressOut,
    QuestionOut,
)
from investiq.services.identity import IdentityService
from investiq.services.market import decode_cursor, encode_cursor, fingerprint

TZ = ZoneInfo("Asia/Kolkata")


def streaks(days: list[date], today: date) -> tuple[int, int]:
    current = longest = length = 0
    previous = None
    for day in sorted(set(days)):
        length = length + 1 if previous is not None and day == previous + timedelta(days=1) else 1
        longest = max(longest, length)
        previous = day
    if previous in {today, today - timedelta(days=1)}:
        current = length
    return current, longest


class LearningService:
    def __init__(self, identity: IdentityService, clock: Callable[[], datetime] | None = None):
        self.identity = identity
        self.factory = identity.factory
        self.clock = clock or now

    async def current_version(self, db: AsyncSession, lesson_id: UUID) -> LessonVersion:
        version = await db.scalar(
            select(LessonVersion)
            .where(LessonVersion.lesson_id == lesson_id)
            .order_by(LessonVersion.version.desc())
            .limit(1)
        )
        if version is None:
            raise AppError(404, "lesson_not_found", "Lesson not found")
        return version

    async def courses(self, cursor: str | None, limit: int) -> CoursePage:
        context = "learning-courses-v1"
        query = select(Course).order_by(Course.id).limit(limit + 1)
        if cursor:
            _, identifier = decode_cursor(cursor, context)
            query = query.where(Course.id > identifier)
        async with self.factory() as db:
            rows = list((await db.scalars(query)).all())
            items = []
            for course in rows[:limit]:
                lessons = (
                    await db.scalars(
                        select(Lesson)
                        .where(Lesson.course_id == course.id)
                        .order_by(Lesson.position)
                    )
                ).all()
                summaries = []
                for lesson in lessons:
                    version = await self.current_version(db, lesson.id)
                    summaries.append(
                        LessonSummary(
                            id=lesson.id,
                            title=version.title,
                            position=lesson.position,
                            xp=lesson.xp,
                        )
                    )
                items.append(
                    CourseOut(
                        id=course.id,
                        slug=course.slug,
                        title=course.title,
                        description=course.description,
                        lessons=summaries,
                    )
                )
            return CoursePage(
                items=items,
                next_cursor=encode_cursor("", rows[limit - 1].id, context)
                if len(rows) > limit
                else None,
            )

    async def lesson(self, lesson_id: UUID) -> LessonOut:
        async with self.factory() as db:
            version = await self.current_version(db, lesson_id)
            lesson = await db.get(Lesson, lesson_id)
            assert lesson is not None
            return LessonOut(
                id=lesson.id,
                course_id=lesson.course_id,
                version_id=version.id,
                version=version.version,
                title=version.title,
                paragraphs=version.paragraphs,
                xp=lesson.xp,
                questions=[
                    QuestionOut(key=q["key"], prompt=q["prompt"], options=q["options"])
                    for q in version.questions
                ],
            )

    async def enroll(self, principal: Principal, course_id: UUID) -> None:
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            if user.email_verified_at is None:
                raise AppError(403, "verification_required", "Verify your email to enroll")
            if await db.get(Course, course_id) is None:
                raise AppError(404, "course_not_found", "Course not found")
            if await db.get(Enrollment, (user.id, course_id)) is None:
                db.add(Enrollment(user_id=user.id, course_id=course_id, enrolled_at=self.clock()))

    async def result(self, db: AsyncSession, attempt: QuizAttempt) -> AttemptOut:
        version = await db.get(LessonVersion, attempt.version_id)
        assert version is not None
        answers = {
            a.question_key: a
            for a in (
                await db.scalars(select(QuizAnswer).where(QuizAnswer.attempt_id == attempt.id))
            ).all()
        }
        return AttemptOut(
            id=attempt.id,
            lesson_id=attempt.lesson_id,
            version_id=attempt.version_id,
            correct_count=attempt.correct_count,
            total=attempt.total,
            passed=attempt.passed,
            xp_awarded=attempt.xp_awarded,
            submitted_at=attempt.submitted_at,
            feedback=[
                FeedbackOut(
                    question_key=q["key"],
                    choice=answers[q["key"]].choice,
                    correct=answers[q["key"]].correct,
                    explanation=q["explanation"],
                )
                for q in version.questions
            ],
        )

    async def submit(
        self, principal: Principal, lesson_id: UUID, data: AttemptInput, key: UUID
    ) -> AttemptOut:
        # Canonicalize order so reordering an identical answer set is a valid retry.
        digest = hashlib.sha256(
            json.dumps(
                {
                    "lesson": str(lesson_id),
                    "version": str(data.version_id),
                    "answers": sorted((a.question_key, a.choice) for a in data.answers),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            if user.email_verified_at is None:
                raise AppError(403, "verification_required", "Verify your email to submit quizzes")
            existing = await db.scalar(
                select(QuizAttempt).where(
                    QuizAttempt.user_id == user.id, QuizAttempt.idempotency_key == key
                )
            )
            if existing is not None:
                if existing.request_hash != digest:
                    raise AppError(
                        409, "idempotency_conflict", "Use a new key for a different attempt"
                    )
                return await self.result(db, existing)
            version = await self.current_version(db, lesson_id)
            if version.id != data.version_id:
                raise AppError(
                    409,
                    "lesson_version_changed",
                    "Reload this lesson before answering its current quiz",
                )
            lesson = await db.get(Lesson, lesson_id)
            assert lesson is not None
            if await db.get(Enrollment, (user.id, lesson.course_id)) is None:
                raise AppError(409, "enrollment_required", "Enroll in this course first")
            answers = {a.question_key: a.choice for a in data.answers}
            if set(answers) != {q["key"] for q in version.questions} or any(
                answers[q["key"]] >= len(q["options"]) for q in version.questions
            ):
                raise AppError(
                    422, "invalid_answers", "Answer every question using one of its options"
                )
            count = sum(answers[q["key"]] == q["correct"] for q in version.questions)
            instant = self.clock()
            first_pass = (
                count == len(version.questions)
                and await db.get(LessonCompletion, (user.id, lesson_id)) is None
            )
            attempt = QuizAttempt(
                user_id=user.id,
                lesson_id=lesson_id,
                version_id=version.id,
                idempotency_key=key,
                request_hash=digest,
                correct_count=count,
                total=len(version.questions),
                passed=count == len(version.questions),
                xp_awarded=lesson.xp if first_pass else 0,
                submitted_at=instant,
            )
            db.add(attempt)
            await db.flush()
            db.add_all(
                [
                    QuizAnswer(
                        attempt_id=attempt.id,
                        question_key=q["key"],
                        choice=answers[q["key"]],
                        correct=answers[q["key"]] == q["correct"],
                    )
                    for q in version.questions
                ]
            )
            if first_pass:
                db.add(
                    LessonCompletion(
                        user_id=user.id,
                        lesson_id=lesson_id,
                        attempt_id=attempt.id,
                        completed_at=instant,
                    )
                )
                db.add(
                    XpEvent(
                        user_id=user.id,
                        lesson_id=lesson_id,
                        attempt_id=attempt.id,
                        amount=lesson.xp,
                        created_at=instant,
                    )
                )
                day = instant.astimezone(TZ).date()
                if await db.get(LearningDay, (user.id, day)) is None:
                    db.add(LearningDay(user_id=user.id, local_date=day, created_at=instant))
                await db.flush()
                codes = ["first_lesson"]
                remaining = await db.scalar(
                    select(func.count())
                    .select_from(Lesson)
                    .where(
                        Lesson.course_id == lesson.course_id,
                        ~Lesson.id.in_(
                            select(LessonCompletion.lesson_id).where(
                                LessonCompletion.user_id == user.id
                            )
                        ),
                    )
                )
                if remaining == 0:
                    codes.append("first_course")
                days = list(
                    (
                        await db.scalars(
                            select(LearningDay.local_date).where(LearningDay.user_id == user.id)
                        )
                    ).all()
                )
                if streaks(days, day)[1] >= 3:
                    codes.append("three_day_streak")
                for code in codes:
                    if await db.get(LearningAchievement, (user.id, code)) is None:
                        db.add(LearningAchievement(user_id=user.id, code=code, awarded_at=instant))
            await db.flush()
            return await self.result(db, attempt)

    async def progress(self, principal: Principal) -> ProgressOut:
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            days = list(
                (
                    await db.scalars(
                        select(LearningDay.local_date)
                        .where(LearningDay.user_id == user.id)
                        .order_by(LearningDay.local_date)
                    )
                ).all()
            )
            current, longest = streaks(days, self.clock().astimezone(TZ).date())
            xp = await db.scalar(
                select(func.coalesce(func.sum(XpEvent.amount), 0)).where(XpEvent.user_id == user.id)
            )
            return ProgressOut(
                xp=int(xp or 0),
                completed_lesson_ids=list(
                    (
                        await db.scalars(
                            select(LessonCompletion.lesson_id)
                            .where(LessonCompletion.user_id == user.id)
                            .order_by(LessonCompletion.lesson_id)
                        )
                    ).all()
                ),
                enrolled_course_ids=list(
                    (
                        await db.scalars(
                            select(Enrollment.course_id)
                            .where(Enrollment.user_id == user.id)
                            .order_by(Enrollment.course_id)
                        )
                    ).all()
                ),
                current_streak=current,
                longest_streak=longest,
                last_learning_date=days[-1] if days else None,
                achievements=[
                    AchievementOut(code=a.code, awarded_at=a.awarded_at)
                    for a in (
                        await db.scalars(
                            select(LearningAchievement)
                            .where(LearningAchievement.user_id == user.id)
                            .order_by(LearningAchievement.awarded_at, LearningAchievement.code)
                        )
                    ).all()
                ],
            )

    async def attempts(
        self, principal: Principal, lesson_id: UUID, cursor: str | None, limit: int
    ) -> AttemptPage:
        context = fingerprint(
            {"user": str(principal.user_id), "lesson": str(lesson_id), "kind": "quiz-v1"}
        )
        query = (
            select(QuizAttempt)
            .where(QuizAttempt.user_id == principal.user_id, QuizAttempt.lesson_id == lesson_id)
            .order_by(QuizAttempt.id)
            .limit(limit + 1)
        )
        if cursor:
            _, identifier = decode_cursor(cursor, context)
            query = query.where(QuizAttempt.id > identifier)
        async with self.factory() as db, db.begin():
            await self.identity.authenticated_user(db, principal)
            rows = list((await db.scalars(query)).all())
            return AttemptPage(
                items=[await self.result(db, a) for a in rows[:limit]],
                next_cursor=encode_cursor("", rows[limit - 1].id, context)
                if len(rows) > limit
                else None,
            )
