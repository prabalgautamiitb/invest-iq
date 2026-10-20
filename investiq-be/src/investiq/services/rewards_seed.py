"""Development catalogue only; never seeds balances, users or redemption activity."""

from importlib.resources import files
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.models.rewards import RewardInventory, RewardItem, RewardTier

NAMESPACE = UUID("1a099d48-ee99-4828-a8b8-aecbb7f42daa")


class TierSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    name: str = Field(min_length=1, max_length=80)
    minimum_earned: int = Field(ge=0)


class ItemSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{0,79}$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1000)
    category: Literal["digital", "learning", "merchandise"]
    cost: int = Field(ge=1, le=1000000)
    capacity: int = Field(ge=0, le=100000)


class CatalogueSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tiers: list[TierSeed] = Field(min_length=1, max_length=20)
    items: list[ItemSeed] = Field(min_length=1, max_length=100)


async def seed_rewards(factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    if settings.environment not in {"development", "test"}:
        raise AppError(
            403,
            "development_catalogue_only",
            "This sandbox catalogue seed is for development and tests",
        )
    data = CatalogueSeed.model_validate_json(
        files("investiq.data").joinpath("rewards_catalogue_v1.json").read_text()
    )
    if min(t.minimum_earned for t in data.tiers) != 0:
        raise AppError(
            422, "invalid_reward_tiers", "Tiers must include a zero-earnings starting tier"
        )
    async with factory() as db, db.begin():
        await db.execute(text("SELECT pg_advisory_xact_lock(742018)"))
        for tier in data.tiers:
            identifier = uuid5(NAMESPACE, "tier:" + tier.slug)
            existing = await db.get(RewardTier, identifier)
            values = tier.model_dump()
            if existing is None:
                db.add(RewardTier(id=identifier, **values))
            elif any(getattr(existing, k) != v for k, v in values.items()):
                raise AppError(
                    409, "reward_seed_changed", "Published tier definitions differ from the seed"
                )
        for item in data.items:
            identifier = uuid5(NAMESPACE, "item:" + item.slug)
            existing_item = await db.get(RewardItem, identifier)
            values = item.model_dump(exclude={"capacity"})
            if existing_item is None:
                db.add(RewardItem(id=identifier, **values, version=1, active=True, mode="sandbox"))
                await db.flush()
            elif any(getattr(existing_item, k) != v for k, v in values.items()):
                raise AppError(
                    409, "reward_seed_changed", "Published reward terms differ from the seed"
                )
            stock = await db.get(RewardInventory, identifier)
            if stock is None:
                db.add(
                    RewardInventory(
                        item_id=identifier, capacity=item.capacity, remaining=item.capacity
                    )
                )
            elif stock.capacity != item.capacity:
                raise AppError(
                    409, "reward_seed_changed", "Inventory capacity differs from the seed"
                )
