from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["digital", "learning", "merchandise"]


class TierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    minimum_earned: int


class WalletOut(BaseModel):
    balance: int
    lifetime_earned: int
    tier: TierOut
    next_tier: TierOut | None
    coins_to_next_tier: int
    lesson_completion_coins: int = 50
    mode: Literal["sandbox"] = "sandbox"


class RewardOut(BaseModel):
    id: UUID
    name: str
    description: str
    category: Category
    cost: int
    version: int
    remaining: int
    mode: Literal["sandbox"] = "sandbox"


class RewardPage(BaseModel):
    items: list[RewardOut]
    next_cursor: str | None


class RedeemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: UUID
    item_version: int = Field(ge=1, strict=True)


class RedemptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    item_id: UUID
    item_name: str
    item_version: int
    cost: int
    balance_after: int
    status: Literal["sandbox_confirmed"]
    created_at: datetime
    mode: Literal["sandbox"] = "sandbox"


class RedemptionPage(BaseModel):
    items: list[RedemptionOut]
    next_cursor: str | None


class LedgerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sequence: int
    kind: Literal["lesson_completion", "redemption"]
    delta: int
    balance_after: int
    policy_version: str
    lesson_id: UUID | None
    redemption_id: UUID | None
    created_at: datetime


class LedgerPage(BaseModel):
    items: list[LedgerOut]
    next_cursor: str | None
