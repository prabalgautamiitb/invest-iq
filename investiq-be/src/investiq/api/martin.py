from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from investiq.api.identity import UserContext
from investiq.schemas.coach import CoachSettingsOut
from investiq.schemas.martin import (
    MartinConversationPage,
    MartinInput,
    MartinTurnOut,
    MartinTurnPage,
)
from investiq.services.martin import MartinService

router = APIRouter(prefix="/me/martin", tags=["Ask Martin"])


def service(request: Request) -> MartinService:
    result: MartinService = request.app.state.martin
    return result


Service = Annotated[MartinService, Depends(service)]
Cursor = Annotated[str | None, Query(max_length=1024)]
Limit = Annotated[int, Query(ge=1, le=20)]


@router.get("/settings", response_model=CoachSettingsOut)
async def settings(martin: Service, principal: UserContext) -> CoachSettingsOut:
    await martin.identity.me(principal)
    return martin.coach.configuration()


@router.post("/turns", status_code=202, response_model=MartinTurnOut)
async def ask(
    data: MartinInput,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
    martin: Service,
    principal: UserContext,
) -> MartinTurnOut:
    await martin.identity.rate_limit(
        "martin_question",
        str(principal.user_id),
        limit=martin.settings.martin_request_limit,
        window_seconds=900,
    )
    return await martin.create(principal, data, key)


@router.get("/conversations", response_model=MartinConversationPage)
async def conversations(
    martin: Service, principal: UserContext, cursor: Cursor = None, limit: Limit = 20
) -> MartinConversationPage:
    return await martin.conversations(principal, cursor, limit)


@router.get("/conversations/{identifier}", response_model=MartinTurnPage)
async def turns(
    identifier: UUID,
    martin: Service,
    principal: UserContext,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> MartinTurnPage:
    return await martin.turns(principal, identifier, cursor, limit)


@router.post("/turns/{identifier}/{action}", response_model=MartinTurnOut)
async def control(
    identifier: UUID, action: str, martin: Service, principal: UserContext
) -> MartinTurnOut:
    from investiq.core.errors import AppError

    if action not in {"cancel", "retry"}:
        raise AppError(404, "action_not_found", "Action not found")
    await martin.identity.rate_limit(
        "martin_control", str(principal.user_id), limit=40, window_seconds=900
    )
    return await martin.control(principal, identifier, action)


@router.delete("/conversations/{identifier}", status_code=204)
async def delete(identifier: UUID, martin: Service, principal: UserContext) -> Response:
    await martin.delete(principal, identifier)
    return Response(status_code=204)
