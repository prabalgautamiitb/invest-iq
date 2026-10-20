"""Integer virtual coins and atomic sandbox redemption; no fulfillment providers."""

import hashlib
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import exists, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investiq.core.errors import AppError
from investiq.core.security import Principal, now
from investiq.models.identity import AuditEvent, User
from investiq.models.learning import LessonCompletion
from investiq.models.rewards import (
    CoinAccount,
    CoinLedger,
    Redemption,
    RewardInventory,
    RewardItem,
    RewardTier,
)
from investiq.schemas.rewards import (
    Category,
    LedgerOut,
    LedgerPage,
    RedeemInput,
    RedemptionOut,
    RedemptionPage,
    RewardOut,
    RewardPage,
    TierOut,
    WalletOut,
)
from investiq.services.identity import IdentityService
from investiq.services.market import decode_cursor, encode_cursor, fingerprint

LESSON_COINS = 50


async def locked_account(db: AsyncSession, user_id: UUID) -> CoinAccount:
    # Caller holds the user lock. Identity mutations use user -> session -> account -> item.
    account = await db.get(CoinAccount, user_id, with_for_update=True)
    if account is None:
        account = CoinAccount(user_id=user_id, balance=0, lifetime_earned=0, entry_count=0)
        db.add(account)
        await db.flush()
    return account


async def credit_completions(db: AsyncSession, user_id: UUID, instant: datetime) -> int:
    """Credit genuine first completions, once per stable lesson; caller locks the user."""
    lessons = list(
        (
            await db.scalars(
                select(LessonCompletion.lesson_id)
                .where(
                    LessonCompletion.user_id == user_id,
                    ~exists().where(
                        CoinLedger.user_id == user_id,
                        CoinLedger.lesson_id == LessonCompletion.lesson_id,
                    ),
                )
                .order_by(LessonCompletion.completed_at, LessonCompletion.lesson_id)
                .limit(100)
            )
        ).all()
    )
    if not lessons:
        return 0
    account = await locked_account(db, user_id)
    for lesson_id in lessons:
        account.balance += LESSON_COINS
        account.lifetime_earned += LESSON_COINS
        account.entry_count += 1
        db.add(
            CoinLedger(
                user_id=user_id,
                sequence=account.entry_count,
                kind="lesson_completion",
                delta=LESSON_COINS,
                balance_after=account.balance,
                policy_version="lesson-coins-v1",
                lesson_id=lesson_id,
                redemption_id=None,
                created_at=instant,
            )
        )
        # Preserve the sequence order even when multiple old completions are reconciled.
        await db.flush()
    return len(lessons)


async def reconcile_earnings(factory: async_sessionmaker[AsyncSession], limit: int = 100) -> int:
    """Bounded recovery over durable completion evidence, without public credit endpoints."""
    async with factory() as db:
        users = list(
            (
                await db.scalars(
                    select(User.id)
                    .where(
                        User.active.is_(True),
                        User.email_verified_at.is_not(None),
                        exists().where(
                            LessonCompletion.user_id == User.id,
                            ~exists()
                            .where(
                                CoinLedger.user_id == LessonCompletion.user_id,
                                CoinLedger.lesson_id == LessonCompletion.lesson_id,
                            )
                            .correlate(LessonCompletion),
                        ),
                    )
                    .order_by(User.id)
                    .limit(limit)
                )
            ).all()
        )
    awarded = 0
    for user_id in users:
        async with factory() as db, db.begin():
            user = await db.get(User, user_id, with_for_update=True)
            if user and user.active and user.email_verified_at is not None:
                awarded += await credit_completions(db, user.id, now())
    return awarded


def reward_out(item: RewardItem, inventory: RewardInventory) -> RewardOut:
    return RewardOut(
        id=item.id,
        name=item.name,
        description=item.description,
        category=cast(Category, item.category),
        cost=item.cost,
        version=item.version,
        remaining=inventory.remaining,
    )


class RewardsService:
    def __init__(self, identity: IdentityService) -> None:
        self.identity, self.factory = identity, identity.factory

    async def catalogue(
        self, query: str, category: Category | None, cursor: str | None, limit: int
    ) -> RewardPage:
        context = fingerprint({"kind": "rewards-v1", "query": query.strip(), "category": category})
        statement = (
            select(RewardItem, RewardInventory)
            .join(RewardInventory)
            .where(RewardItem.active.is_(True))
        )
        if category:
            statement = statement.where(RewardItem.category == category)
        if query.strip():
            escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            statement = statement.where(RewardItem.name.ilike(f"%{escaped}%", escape="\\"))
        name = RewardItem.name.collate("C")
        if cursor:
            value, identifier = decode_cursor(cursor, context)
            statement = statement.where(tuple_(name, RewardItem.id) > tuple_(value, identifier))
        async with self.factory() as db:
            rows = (
                await db.execute(statement.order_by(name, RewardItem.id).limit(limit + 1))
            ).all()
            return RewardPage(
                items=[reward_out(item, stock) for item, stock in rows[:limit]],
                next_cursor=encode_cursor(rows[limit - 1][0].name, rows[limit - 1][0].id, context)
                if len(rows) > limit
                else None,
            )

    async def detail(self, identifier: UUID) -> RewardOut:
        async with self.factory() as db:
            row = (
                await db.execute(
                    select(RewardItem, RewardInventory)
                    .join(RewardInventory)
                    .where(RewardItem.id == identifier, RewardItem.active.is_(True))
                )
            ).one_or_none()
            if row is None:
                raise AppError(404, "reward_not_found", "Reward not found")
            return reward_out(*row)

    async def wallet(self, principal: Principal) -> WalletOut:
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            account = await db.get(CoinAccount, user.id)
            balance, earned = (account.balance, account.lifetime_earned) if account else (0, 0)
            tiers = list(
                (await db.scalars(select(RewardTier).order_by(RewardTier.minimum_earned))).all()
            )
            if not tiers or tiers[0].minimum_earned != 0:
                raise AppError(
                    503, "rewards_not_initialized", "Initialize the reward catalogue and tiers"
                )
            tier = next(t for t in reversed(tiers) if t.minimum_earned <= earned)
            upcoming = next((t for t in tiers if t.minimum_earned > earned), None)
            return WalletOut(
                balance=balance,
                lifetime_earned=earned,
                tier=TierOut.model_validate(tier),
                next_tier=TierOut.model_validate(upcoming) if upcoming else None,
                coins_to_next_tier=upcoming.minimum_earned - earned if upcoming else 0,
            )

    async def redeem(self, principal: Principal, data: RedeemInput, key: UUID) -> RedemptionOut:
        digest = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            if user.email_verified_at is None:
                raise AppError(
                    403, "verification_required", "Verify your email before redeeming virtual coins"
                )
            existing = await db.scalar(
                select(Redemption).where(
                    Redemption.user_id == user.id, Redemption.idempotency_key == key
                )
            )
            if existing:
                if existing.request_hash != digest:
                    raise AppError(
                        409, "idempotency_conflict", "Use a new key for a different reward request"
                    )
                return RedemptionOut.model_validate(existing)
            instant = now()
            await credit_completions(db, user.id, instant)
            account = await locked_account(db, user.id)
            item = await db.get(RewardItem, data.item_id, with_for_update=True)
            if item is None or not item.active:
                raise AppError(404, "reward_not_found", "Reward not found")
            if item.version != data.item_version:
                raise AppError(
                    409, "reward_version_changed", "Refresh the reward before confirming"
                )
            stock = await db.get(RewardInventory, item.id, with_for_update=True)
            if stock is None or stock.remaining < 1:
                raise AppError(409, "reward_sold_out", "This sandbox reward is sold out")
            if account.balance < item.cost:
                raise AppError(
                    409,
                    "insufficient_coins",
                    "Earn more virtual coins before redeeming this reward",
                )
            account.balance -= item.cost
            account.entry_count += 1
            stock.remaining -= 1
            redemption = Redemption(
                user_id=user.id,
                item_id=item.id,
                idempotency_key=key,
                request_hash=digest,
                item_version=item.version,
                item_name=item.name,
                cost=item.cost,
                balance_after=account.balance,
                status="sandbox_confirmed",
                created_at=instant,
            )
            db.add(redemption)
            await db.flush()
            db.add(
                CoinLedger(
                    user_id=user.id,
                    sequence=account.entry_count,
                    kind="redemption",
                    delta=-item.cost,
                    balance_after=account.balance,
                    policy_version="sandbox-redemption-v1",
                    lesson_id=None,
                    redemption_id=redemption.id,
                    created_at=instant,
                )
            )
            db.add(
                AuditEvent(
                    actor_id=user.id, action="sandbox_reward_redeemed", resource_id=redemption.id
                )
            )
            await db.flush()
            return RedemptionOut.model_validate(redemption)

    async def ledger(self, principal: Principal, cursor: str | None, limit: int) -> LedgerPage:
        context = fingerprint({"kind": "coin-ledger-v1", "user": str(principal.user_id)})
        statement = select(CoinLedger).where(CoinLedger.user_id == principal.user_id)
        if cursor:
            value, _ = decode_cursor(cursor, context)
            try:
                before = int(value)
                if before < 1:
                    raise ValueError
            except ValueError as exc:
                raise AppError(
                    422, "invalid_cursor", "Use a ledger cursor from this account"
                ) from exc
            statement = statement.where(CoinLedger.sequence < before)
        async with self.factory() as db, db.begin():
            await self.identity.authenticated_user(db, principal)
            rows = list(
                (
                    await db.scalars(
                        statement.order_by(CoinLedger.sequence.desc()).limit(limit + 1)
                    )
                ).all()
            )
            return LedgerPage(
                items=[LedgerOut.model_validate(row) for row in rows[:limit]],
                next_cursor=encode_cursor(
                    str(rows[limit - 1].sequence), rows[limit - 1].id, context
                )
                if len(rows) > limit
                else None,
            )

    async def history(self, principal: Principal, cursor: str | None, limit: int) -> RedemptionPage:
        context = fingerprint({"kind": "redemptions-v1", "user": str(principal.user_id)})
        statement = select(Redemption).where(Redemption.user_id == principal.user_id)
        if cursor:
            value, identifier = decode_cursor(cursor, context)
            try:
                before = datetime.fromisoformat(value)
                if before.utcoffset() is None:
                    raise ValueError
            except ValueError as exc:
                raise AppError(
                    422, "invalid_cursor", "Use a redemption cursor from this account"
                ) from exc
            statement = statement.where(
                tuple_(Redemption.created_at, Redemption.id) < tuple_(before, identifier)
            )
        async with self.factory() as db, db.begin():
            await self.identity.authenticated_user(db, principal)
            rows = list(
                (
                    await db.scalars(
                        statement.order_by(
                            Redemption.created_at.desc(), Redemption.id.desc()
                        ).limit(limit + 1)
                    )
                ).all()
            )
            return RedemptionPage(
                items=[RedemptionOut.model_validate(row) for row in rows[:limit]],
                next_cursor=encode_cursor(
                    rows[limit - 1].created_at.isoformat(), rows[limit - 1].id, context
                )
                if len(rows) > limit
                else None,
            )
