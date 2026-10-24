from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from investiq.api.identity import UserContext
from investiq.schemas.coach import (
    CoachEvidence,
    CoachJobOut,
    CoachSettingsOut,
    CreateCoachInput,
    JobPage,
    ReflectionInput,
    ReflectionOut,
    ReflectionPage,
    UsageOut,
)
from investiq.services.coach import CoachService

router = APIRouter(prefix="/me/coach", tags=["performance coach"])


def service(request: Request) -> CoachService:
    result: CoachService = request.app.state.coach
    return result


Service = Annotated[CoachService, Depends(service)]
Key = Annotated[UUID, Header(alias="Idempotency-Key")]
Cursor = Annotated[str | None, Query(max_length=1024)]
Limit = Annotated[int, Query(ge=1, le=20)]


@router.get("/settings", response_model=CoachSettingsOut)
async def settings(coach: Service, principal: UserContext) -> CoachSettingsOut:
    await coach.identity.me(principal)
    return coach.configuration()


@router.get("/evidence", response_model=CoachEvidence)
async def evidence(contest_id: UUID, coach: Service, principal: UserContext) -> CoachEvidence:
    return await coach.evidence(principal, contest_id)


@router.post("/jobs", status_code=202, response_model=CoachJobOut)
async def create(
    data: CreateCoachInput, key: Key, coach: Service, principal: UserContext
) -> CoachJobOut:
    await coach.identity.rate_limit(
        "coach_request",
        str(principal.user_id),
        limit=coach.settings.ai_request_limit,
        window_seconds=900,
    )
    return await coach.create(principal, data, key)


@router.get("/jobs", response_model=JobPage)
async def history(
    coach: Service,
    principal: UserContext,
    contest_id: UUID | None = None,
    cursor: Cursor = None,
    limit: Limit = 10,
) -> JobPage:
    return await coach.history(principal, contest_id, cursor, limit)


@router.get("/jobs/{identifier}", response_model=CoachJobOut)
async def job(identifier: UUID, coach: Service, principal: UserContext) -> CoachJobOut:
    return await coach.get(principal, identifier)


@router.get("/jobs/{identifier}/usage", response_model=list[UsageOut])
async def usage(identifier: UUID, coach: Service, principal: UserContext) -> list[UsageOut]:
    return await coach.usage(principal, identifier)


@router.post("/reflections", response_model=ReflectionOut, status_code=201)
async def reflect(
    data: ReflectionInput, key: Key, coach: Service, principal: UserContext
) -> ReflectionOut:
    await coach.identity.rate_limit(
        "coach_reflection", str(principal.user_id), limit=20, window_seconds=900
    )
    return await coach.reflect(principal, data, key)


@router.get("/reflections", response_model=ReflectionPage)
async def reflections(
    contest_id: UUID,
    coach: Service,
    principal: UserContext,
    cursor: Cursor = None,
    limit: Limit = 10,
) -> ReflectionPage:
    return await coach.reflections(principal, contest_id, cursor, limit)
