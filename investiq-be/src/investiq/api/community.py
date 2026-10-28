from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from investiq.api.contest import Viewer
from investiq.api.identity import UserContext
from investiq.schemas.community import (
    CommentInput,
    ContentInput,
    ContentOut,
    ContentPage,
    FlagInput,
    GroupInput,
    GroupOut,
    GroupPage,
    Message,
    ModerateInput,
    ReportInput,
    ReportPage,
    VoteInput,
)
from investiq.services.community import CommunityService

router = APIRouter(prefix="/community", tags=["community"])


def service(request: Request) -> CommunityService:
    result: CommunityService = request.app.state.community
    return result


Service = Annotated[CommunityService, Depends(service)]


async def write_access(principal: UserContext, community: Service) -> None:
    await community.identity.rate_limit(
        "community_write",
        str(principal.user_id),
        limit=community.identity.settings.community_write_limit,
        window_seconds=community.identity.settings.community_rate_window_seconds,
    )


Writes = Annotated[None, Depends(write_access)]
Key = Annotated[UUID, Header(alias="Idempotency-Key")]


@router.get("/posts", response_model=ContentPage)
async def feed(
    community: Service,
    principal: Viewer,
    kind: Literal["discussion", "idea", "market", "poll"] | None = None,
    group: UUID | None = None,
    saved: bool = False,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    scope: Literal["accessible", "joined", "public"] = "accessible",
) -> ContentPage:
    return await community.feed(principal, kind, group, saved, None, cursor, limit, scope)


@router.post("/posts", response_model=ContentOut, status_code=201)
async def create(
    data: ContentInput, community: Service, principal: UserContext, _: Writes, key: Key
) -> ContentOut:
    return await community.create(principal, data, key)


@router.get("/posts/{identifier}", response_model=ContentOut)
async def detail(identifier: UUID, community: Service, principal: Viewer) -> ContentOut:
    return await community.detail(principal, identifier)


@router.get("/posts/{identifier}/comments", response_model=ContentPage)
async def comments(
    identifier: UUID,
    community: Service,
    principal: Viewer,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> ContentPage:
    return await community.feed(principal, None, None, False, identifier, cursor, limit)


@router.post("/posts/{identifier}/comments", response_model=ContentOut, status_code=201)
async def comment(
    identifier: UUID,
    data: CommentInput,
    community: Service,
    principal: UserContext,
    _: Writes,
    key: Key,
) -> ContentOut:
    return await community.create(principal, ContentInput(body=data.body), key, identifier)


@router.put("/posts/{identifier}/like", response_model=Message)
async def like(
    identifier: UUID, data: FlagInput, community: Service, principal: UserContext, _: Writes
) -> Message:
    await community.interact(principal, identifier, "like", data.enabled)
    return Message(message="Reaction saved")


@router.put("/posts/{identifier}/save", response_model=Message)
async def save(
    identifier: UUID, data: FlagInput, community: Service, principal: UserContext, _: Writes
) -> Message:
    await community.interact(principal, identifier, "save", data.enabled)
    return Message(message="Saved-post preference updated")


@router.put("/posts/{identifier}/vote", response_model=Message)
async def vote(
    identifier: UUID, data: VoteInput, community: Service, principal: UserContext, _: Writes
) -> Message:
    await community.interact(principal, identifier, "vote", option=data.option)
    return Message(message="Vote recorded")


@router.delete("/posts/{identifier}", response_model=Message)
async def remove(
    identifier: UUID, community: Service, principal: UserContext, _: Writes
) -> Message:
    await community.interact(principal, identifier, "delete")
    return Message(message="Content deleted")


@router.post("/posts/{identifier}/reports", response_model=Message)
async def report(
    identifier: UUID, data: ReportInput, community: Service, principal: UserContext, _: Writes
) -> Message:
    await community.interact(principal, identifier, "report", reason=data.reason)
    return Message(message="Report recorded for administrator review")


@router.get("/groups", response_model=GroupPage)
async def groups(
    community: Service,
    principal: Viewer,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    scope: Literal["all", "joined", "created"] = "all",
    q: Annotated[str, Query(max_length=80)] = "",
) -> GroupPage:
    return await community.groups(principal, cursor, limit, scope, q)


@router.get("/groups/{identifier}", response_model=GroupOut)
async def group_detail(identifier: UUID, community: Service, principal: Viewer) -> GroupOut:
    return await community.group_detail(principal, identifier)


@router.post("/groups", status_code=201)
async def create_group(
    data: GroupInput, community: Service, principal: UserContext, _: Writes
) -> dict[str, UUID]:
    return {"id": await community.create_group(principal, data)}


@router.put("/groups/{identifier}/membership", response_model=Message)
async def membership(
    identifier: UUID, data: FlagInput, community: Service, principal: UserContext, _: Writes
) -> Message:
    await community.membership(principal, identifier, data.enabled)
    return Message(message="Group membership updated")


@router.get("/reports", response_model=ReportPage)
async def reports(
    community: Service,
    principal: UserContext,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ReportPage:
    return await community.reports(principal, cursor, limit)


@router.post("/posts/{identifier}/moderation", response_model=Message)
async def moderate(
    identifier: UUID, data: ModerateInput, community: Service, principal: UserContext, _: Writes
) -> Message:
    await community.moderate(principal, identifier, data)
    return Message(message="Moderation decision recorded")
