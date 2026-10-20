from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from investiq.api.identity import Service as Identity
from investiq.api.identity import UserContext
from investiq.schemas.rewards import (
    Category,
    LedgerPage,
    RedeemInput,
    RedemptionOut,
    RedemptionPage,
    RewardOut,
    RewardPage,
    WalletOut,
)
from investiq.services.rewards import RewardsService

router = APIRouter(tags=["sandbox rewards"])


def service(request: Request) -> RewardsService:
    result: RewardsService = request.app.state.rewards
    return result


Service = Annotated[RewardsService, Depends(service)]
Cursor = Annotated[str | None, Query(max_length=1024)]
Limit = Annotated[int, Query(ge=1, le=50)]


@router.get("/rewards", response_model=RewardPage)
async def catalogue(
    rewards: Service,
    query: Annotated[str, Query(max_length=100)] = "",
    category: Category | None = None,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> RewardPage:
    return await rewards.catalogue(query, category, cursor, limit)


@router.get("/rewards/{item_id}", response_model=RewardOut)
async def detail(item_id: UUID, rewards: Service) -> RewardOut:
    return await rewards.detail(item_id)


@router.get("/me/coins", response_model=WalletOut)
async def wallet(rewards: Service, principal: UserContext) -> WalletOut:
    return await rewards.wallet(principal)


@router.get("/me/coins/ledger", response_model=LedgerPage)
async def ledger(
    rewards: Service, principal: UserContext, cursor: Cursor = None, limit: Limit = 20
) -> LedgerPage:
    return await rewards.ledger(principal, cursor, limit)


@router.get("/me/redemptions", response_model=RedemptionPage)
async def history(
    rewards: Service, principal: UserContext, cursor: Cursor = None, limit: Limit = 20
) -> RedemptionPage:
    return await rewards.history(principal, cursor, limit)


@router.post("/me/redemptions", response_model=RedemptionOut, status_code=201)
async def redeem(
    data: RedeemInput,
    rewards: Service,
    principal: UserContext,
    identity: Identity,
    idempotency_key: Annotated[UUID, Header()],
) -> RedemptionOut:
    await identity.rate_limit("reward_redeem", str(principal.user_id))
    return await rewards.redeem(principal, data, idempotency_key)
