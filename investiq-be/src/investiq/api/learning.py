from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from investiq.api.identity import Service as Identity
from investiq.api.identity import UserContext
from investiq.schemas.learning import (
    AttemptInput,
    AttemptOut,
    AttemptPage,
    CourseContentInput,
    CoursePage,
    LessonContentInput,
    LessonOut,
    LessonSummary,
    ProgressOut,
)
from investiq.services.learning import LearningService
from investiq.services.learning_admin import create_course, publish_lesson, require_admin

router = APIRouter(tags=["learning"])


def service(request: Request) -> LearningService:
    result: LearningService = request.app.state.learning
    return result


Service = Annotated[LearningService, Depends(service)]
Cursor = Annotated[str | None, Query(max_length=1024)]
Limit = Annotated[int, Query(ge=1, le=50)]


@router.get("/admin/courses", response_model=CoursePage)
async def admin_courses(
    learning: Service, principal: UserContext, cursor: Cursor = None, limit: Limit = 20
) -> CoursePage:
    async with learning.factory() as db, db.begin():
        await require_admin(learning, db, principal)
    return await learning.courses(cursor, limit)


@router.post("/admin/courses", status_code=201)
async def publish_course(
    data: CourseContentInput, learning: Service, principal: UserContext, identity: Identity
) -> dict[str, UUID]:
    await identity.rate_limit("learning_write", str(principal.user_id))
    return {"id": await create_course(learning, principal, data)}


@router.post("/admin/courses/{course_id}/lessons", response_model=LessonSummary, status_code=201)
async def add_course_lesson(
    course_id: UUID,
    data: LessonContentInput,
    learning: Service,
    principal: UserContext,
    identity: Identity,
) -> LessonSummary:
    await identity.rate_limit("learning_write", str(principal.user_id))
    return await publish_lesson(learning, principal, course_id, data)


@router.get("/courses", response_model=CoursePage)
async def courses(learning: Service, cursor: Cursor = None, limit: Limit = 20) -> CoursePage:
    return await learning.courses(cursor, limit)


@router.get("/lessons/{lesson_id}", response_model=LessonOut)
async def lesson(lesson_id: UUID, learning: Service) -> LessonOut:
    return await learning.lesson(lesson_id)


@router.post("/courses/{course_id}/enrollment")
async def enroll(
    course_id: UUID, learning: Service, principal: UserContext, identity: Identity
) -> dict[str, str]:
    await identity.rate_limit("learning_write", str(principal.user_id))
    await learning.enroll(principal, course_id)
    return {"message": "Enrolled"}


@router.post("/lessons/{lesson_id}/attempts", response_model=AttemptOut, status_code=201)
async def submit(
    lesson_id: UUID,
    data: AttemptInput,
    learning: Service,
    principal: UserContext,
    identity: Identity,
    idempotency_key: Annotated[UUID, Header()],
) -> AttemptOut:
    await identity.rate_limit("quiz_attempt", str(principal.user_id))
    return await learning.submit(principal, lesson_id, data, idempotency_key)


@router.get("/lessons/{lesson_id}/attempts", response_model=AttemptPage)
async def attempts(
    lesson_id: UUID,
    learning: Service,
    principal: UserContext,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> AttemptPage:
    return await learning.attempts(principal, lesson_id, cursor, limit)


@router.get("/me/learning", response_model=ProgressOut)
async def progress(learning: Service, principal: UserContext) -> ProgressOut:
    return await learning.progress(principal)
