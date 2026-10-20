from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from investiq.api.contest import Viewer
from investiq.api.identity import UserContext
from investiq.schemas.valuation import (
    ContestHistoryOut,
    DashboardOut,
    LeaderboardOut,
    PerformanceOut,
)
from investiq.services.valuation import ValuationService

router = APIRouter(tags=["simulation performance"])


def service(request: Request) -> ValuationService:
    result: ValuationService = request.app.state.valuations
    return result


Service = Annotated[ValuationService, Depends(service)]
Cursor = Annotated[str | None, Query(max_length=1024)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/contests/{contest_id}/leaderboard", response_model=LeaderboardOut)
async def leaderboard(
    contest_id: UUID,
    valuations: Service,
    principal: Viewer,
    cursor: Cursor = None,
    limit: Limit = 20,
    run_id: UUID | None = None,
) -> LeaderboardOut:
    return await valuations.leaderboard(contest_id, principal, cursor, limit, run_id)


@router.get("/contests/{contest_id}/performance", response_model=PerformanceOut)
async def performance(
    contest_id: UUID,
    valuations: Service,
    principal: UserContext,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> PerformanceOut:
    return await valuations.performance(principal, contest_id, cursor, limit)


@router.get("/me/dashboard", response_model=DashboardOut)
async def dashboard(valuations: Service, principal: UserContext) -> DashboardOut:
    return await valuations.dashboard(principal)


@router.get("/me/contest-history", response_model=ContestHistoryOut)
async def history(
    valuations: Service, principal: UserContext, cursor: Cursor = None, limit: Limit = 20
) -> ContestHistoryOut:
    return await valuations.history(principal, cursor, limit)
