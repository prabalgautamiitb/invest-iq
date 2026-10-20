from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from investiq.api.identity import Service as Identity
from investiq.api.identity import UserContext
from investiq.schemas.portfolio import (
    DraftInput,
    DraftOut,
    PreviewInput,
    PreviewOut,
    SubmissionOut,
    SubmissionPage,
    SubmitInput,
)
from investiq.services.portfolio import PortfolioService

router = APIRouter(tags=["portfolios"])


def service(request: Request) -> PortfolioService:
    result: PortfolioService = request.app.state.portfolios
    return result


Service = Annotated[PortfolioService, Depends(service)]


@router.get("/contests/{contest_id}/portfolio/draft", response_model=DraftOut)
async def draft(contest_id: UUID, portfolios: Service, principal: UserContext) -> DraftOut:
    return await portfolios.get_draft(principal, contest_id)


@router.put("/contests/{contest_id}/portfolio/draft", response_model=DraftOut)
async def save(
    contest_id: UUID,
    data: DraftInput,
    portfolios: Service,
    principal: UserContext,
    identity: Identity,
) -> DraftOut:
    await identity.rate_limit("portfolio_write", str(principal.user_id))
    return await portfolios.save(principal, contest_id, data)


@router.post("/contests/{contest_id}/portfolio/preview", response_model=PreviewOut)
async def preview(
    contest_id: UUID,
    data: PreviewInput,
    portfolios: Service,
    principal: UserContext,
    identity: Identity,
) -> PreviewOut:
    await identity.rate_limit("portfolio_preview", str(principal.user_id))
    return await portfolios.preview(principal, contest_id, data.draft_revision)


@router.post("/contests/{contest_id}/submissions", response_model=SubmissionOut, status_code=201)
async def submit(
    contest_id: UUID,
    data: SubmitInput,
    portfolios: Service,
    principal: UserContext,
    identity: Identity,
    idempotency_key: Annotated[UUID, Header()],
) -> SubmissionOut:
    await identity.rate_limit("portfolio_submit", str(principal.user_id))
    return await portfolios.submit(principal, contest_id, data, idempotency_key)


@router.get("/contests/{contest_id}/submissions", response_model=SubmissionPage)
async def history(
    contest_id: UUID,
    portfolios: Service,
    principal: UserContext,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SubmissionPage:
    return await portfolios.history(principal, contest_id, cursor, limit)
