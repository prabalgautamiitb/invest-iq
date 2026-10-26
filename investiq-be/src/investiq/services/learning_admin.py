"""Administrator publishing; existing lesson versions and learner results stay immutable."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from investiq.core.errors import AppError
from investiq.core.security import Principal
from investiq.models.identity import AuditEvent
from investiq.models.learning import Course, Lesson, LessonVersion
from investiq.schemas.learning import CourseContentInput, LessonContentInput, LessonSummary
from investiq.services.learning import LearningService


async def require_admin(service: LearningService, db: AsyncSession, principal: Principal) -> None:
    user = await service.identity.authenticated_user(db, principal)
    if user.role != "admin":
        raise AppError(403, "admin_required", "Only administrators can publish learning content")
    if user.email_verified_at is None:
        raise AppError(
            403, "verification_required", "Verify your email to publish learning content"
        )


async def add_lesson(
    db: AsyncSession, course_id: UUID, position: int, data: LessonContentInput
) -> LessonSummary:
    lesson = Lesson(course_id=course_id, position=position, xp=data.xp)
    db.add(lesson)
    await db.flush()
    db.add(
        LessonVersion(
            lesson_id=lesson.id,
            version=1,
            title=data.title,
            paragraphs=data.paragraphs,
            questions=[q.model_dump() for q in data.questions],
        )
    )
    await db.flush()
    return LessonSummary(id=lesson.id, title=data.title, position=position, xp=data.xp)


async def create_course(
    service: LearningService, principal: Principal, data: CourseContentInput
) -> UUID:
    try:
        async with service.factory() as db, db.begin():
            await require_admin(service, db, principal)
            course = Course(slug=data.slug, title=data.title, description=data.description)
            db.add(course)
            await db.flush()
            for position, lesson in enumerate(data.lessons, 1):
                await add_lesson(db, course.id, position, lesson)
            db.add(
                AuditEvent(
                    actor_id=principal.user_id,
                    action="learning_course_published",
                    resource_id=course.id,
                )
            )
            return course.id
    except IntegrityError as exc:
        if "learning_courses" in str(exc.orig) and "slug" in str(exc.orig):
            raise AppError(
                409, "course_slug_taken", "A course with this URL name already exists"
            ) from exc
        raise


async def publish_lesson(
    service: LearningService, principal: Principal, course_id: UUID, data: LessonContentInput
) -> LessonSummary:
    async with service.factory() as db, db.begin():
        await require_admin(service, db, principal)
        course = await db.get(Course, course_id, with_for_update=True)
        if course is None:
            raise AppError(404, "course_not_found", "Course not found")
        # The course lock serializes position allocation between administrators.
        position = await db.scalar(
            select(func.max(Lesson.position)).where(Lesson.course_id == course_id)
        )
        summary = await add_lesson(db, course_id, (position or 0) + 1, data)
        db.add(
            AuditEvent(
                actor_id=principal.user_id,
                action="learning_lesson_published",
                resource_id=summary.id,
            )
        )
        return summary
