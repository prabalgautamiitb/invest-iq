from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from investiq.api.identity import Service as Identity
from investiq.api.identity import UserContext
from investiq.core.security import Principal
from investiq.schemas.contest import (
    ContestInput,
    ContestOut,
    ContestPage,
    InvitationInput,
    InvitationOut,
    InvitationPage,
    Level,
    Organizer,
    Status,
    TransitionInput,
    Visibility,
)
from investiq.services.contest import ContestService

router = APIRouter(tags=["contests"])


def service(request: Request) -> ContestService:
    result: ContestService = request.app.state.contests
    return result


Service = Annotated[ContestService, Depends(service)]


async def viewer(request: Request, identity: Identity) -> Principal | None:
    raw = request.cookies.get(identity.settings.cookie_name)
    if raw is None:
        return None
    principal = await identity.principal(raw)
    return principal if principal.user_id else None


Viewer = Annotated[Principal | None, Depends(viewer)]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=1024)]


@router.get("/contest-template", response_model=ContestInput)
async def template(contests: Service) -> ContestInput:
    return await contests.template()


@router.get("/contests", response_model=ContestPage)
async def listing(
    contests: Service,
    principal: Viewer,
    query: Annotated[str, Query(max_length=100)] = "",
    visibility: Visibility | None = None,
    organizer: Organizer | None = None,
    level: Level | None = None,
    status: Status | None = None,
    scope: Literal["discover", "joined", "hosted", "managed"] = "discover",
    sort: Literal["name", "-name"] = "name",
    cursor: Cursor = None,
    limit: Limit = 20,
) -> ContestPage:
    return await contests.listing(
        principal,
        query=query,
        visibility=visibility,
        organizer=organizer,
        level=level,
        status=status,
        scope=scope,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )


@router.get("/me/contests", response_model=ContestPage)
async def mine(
    contests: Service,
    principal: UserContext,
    scope: Literal["joined", "hosted"] = "joined",
    cursor: Cursor = None,
    limit: Limit = 20,
) -> ContestPage:
    return await contests.listing(principal, scope=scope, cursor=cursor, limit=limit)


@router.post("/contests", response_model=ContestOut, status_code=201)
async def create(
    data: ContestInput,
    contests: Service,
    principal: UserContext,
    identity: Identity,
    idempotency_key: Annotated[UUID, Header()],
) -> ContestOut:
    await identity.rate_limit("contest_write", str(principal.user_id))
    return await contests.create(principal, data, idempotency_key)


@router.post("/admin/contests", response_model=ContestOut, status_code=201)
async def create_platform(
    data: ContestInput,
    contests: Service,
    principal: UserContext,
    identity: Identity,
    idempotency_key: Annotated[UUID, Header()],
) -> ContestOut:
    await identity.rate_limit("contest_write", str(principal.user_id))
    return await contests.create(principal, data, idempotency_key, platform=True)


@router.get("/contests/{contest_id}", response_model=ContestOut)
async def detail(contest_id: UUID, contests: Service, principal: Viewer) -> ContestOut:
    return await contests.get(contest_id, principal)


@router.put("/contests/{contest_id}", response_model=ContestOut)
async def revise(
    contest_id: UUID,
    data: ContestInput,
    contests: Service,
    principal: UserContext,
    identity: Identity,
) -> ContestOut:
    await identity.rate_limit("contest_write", str(principal.user_id))
    return await contests.revise(principal, contest_id, data)


@router.post("/contests/{contest_id}/transitions", response_model=ContestOut)
async def transition(
    contest_id: UUID, data: TransitionInput, contests: Service, principal: UserContext
) -> ContestOut:
    return await contests.transition(principal, contest_id, data.action)


@router.post("/contests/{contest_id}/entries", response_model=ContestOut)
async def join(contest_id: UUID, contests: Service, principal: UserContext) -> ContestOut:
    return await contests.join(principal, contest_id)


@router.post("/contests/{contest_id}/invitations", response_model=InvitationOut, status_code=201)
async def invite(
    contest_id: UUID,
    data: InvitationInput,
    contests: Service,
    principal: UserContext,
    identity: Identity,
) -> InvitationOut:
    await identity.rate_limit("contest_invite", str(principal.user_id))
    return await contests.invite(principal, contest_id, str(data.email))


@router.get("/contests/{contest_id}/invitations", response_model=InvitationPage)
async def hosted_invitations(
    contest_id: UUID,
    contests: Service,
    principal: UserContext,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> InvitationPage:
    return await contests.invitations(principal, identifier=contest_id, cursor=cursor, limit=limit)


@router.get("/me/contest-invitations", response_model=InvitationPage)
async def invitations(
    contests: Service, principal: UserContext, cursor: Cursor = None, limit: Limit = 20
) -> InvitationPage:
    return await contests.invitations(principal, cursor=cursor, limit=limit)


@router.post("/contest-invitations/{invitation_id}/{action}", response_model=InvitationOut)
async def invitation_action(
    invitation_id: UUID,
    action: Literal["accept", "decline", "revoke"],
    contests: Service,
    principal: UserContext,
) -> InvitationOut:
    return await contests.invitation_action(principal, invitation_id, action)
