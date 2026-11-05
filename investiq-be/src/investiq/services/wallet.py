"""Wallet mutations share the caller's contest transaction; no independent commits."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from investiq.core.errors import AppError
from investiq.models.contest import ContestMembership
from investiq.models.valuation import ValuationRecord, ValuationRun
from investiq.models.wallet import VirtualWallet, WalletEntry, WalletPosition
from investiq.schemas.wallet import PortfolioOverviewOut, PortfolioValuePoint

OPENING_CAPITAL = Decimal("1000000.0000")


async def portfolio_overview(db: AsyncSession, user_id: UUID) -> PortfolioOverviewOut:
    wallet = await lock_wallet(db, user_id)
    positions = list(
        (await db.scalars(select(WalletPosition).where(WalletPosition.user_id == user_id))).all()
    )
    active = [p for p in positions if p.status == "active"]
    total = wallet.available + sum((p.current_value for p in active), Decimal(0))
    rows = (
        await db.execute(
            select(ValuationRecord, ValuationRun.session_date)
            .join(ValuationRun, ValuationRun.id == ValuationRecord.run_id)
            .join(WalletPosition, WalletPosition.membership_id == ValuationRecord.membership_id)
            .where(
                WalletPosition.user_id == user_id,
                WalletPosition.status != "refunded",
                WalletPosition.run_id.is_not(None),
                ValuationRun.status == "succeeded",
                ValuationRun.session_date <= WalletPosition.session_date,
            )
            .order_by(ValuationRun.session_date, ValuationRecord.membership_id)
        )
    ).all()
    # Transfers between available funds and a contest are not investment gains.
    # Retain completed P&L and carry each contest's latest published P&L forward.
    latest_pnl: dict[UUID, Decimal] = {}
    by_day: dict[date, Decimal] = {}
    running_total = OPENING_CAPITAL
    for record, day in rows:
        running_total += record.pnl - latest_pnl.get(record.membership_id, Decimal(0))
        latest_pnl[record.membership_id] = record.pnl
        by_day[day] = running_total
    legacy = await db.scalar(
        select(func.count())
        .select_from(ContestMembership)
        .outerjoin(WalletPosition, WalletPosition.membership_id == ContestMembership.id)
        .where(ContestMembership.user_id == user_id, WalletPosition.membership_id.is_(None))
    )
    return PortfolioOverviewOut(
        opening_capital=OPENING_CAPITAL,
        total_value=total,
        pnl=total - OPENING_CAPITAL,
        return_pct=(total / OPENING_CAPITAL - 1) * 100,
        latest_session_date=max(by_day) if by_day else None,
        active_contest_count=len(active),
        unvalued_contest_count=sum(p.run_id is None for p in active),
        legacy_contest_count=legacy or 0,
        series=[PortfolioValuePoint(session_date=None, total_value=OPENING_CAPITAL)]
        + [
            PortfolioValuePoint(session_date=day, total_value=value)
            for day, value in by_day.items()
        ],
    )


async def lock_wallet(db: AsyncSession, user_id: UUID) -> VirtualWallet:
    # Supports operator-created users too; ON CONFLICT prevents duplicate opening grants.
    await db.execute(
        insert(VirtualWallet)
        .values(user_id=user_id, available=OPENING_CAPITAL)
        .on_conflict_do_nothing(index_elements=[VirtualWallet.user_id])
    )
    wallet = await db.get(VirtualWallet, user_id, with_for_update=True)
    assert wallet is not None
    await db.execute(
        insert(WalletEntry)
        .values(
            user_id=user_id,
            event_key="opening",
            kind="opening",
            amount=OPENING_CAPITAL,
            available_after=OPENING_CAPITAL,
        )
        .on_conflict_do_nothing(index_elements=[WalletEntry.user_id, WalletEntry.event_key])
    )
    return wallet


async def reserve(db: AsyncSession, member: ContestMembership, capital: Decimal) -> None:
    wallet = await lock_wallet(db, member.user_id)
    if wallet.available < capital:
        raise AppError(
            409,
            "insufficient_wallet_balance",
            "Not enough available virtual funds for this contest. "
            f"Required ₹{capital:,.2f}; available ₹{wallet.available:,.2f}. "
            "Funds in active contests become available after final results.",
        )
    wallet.available -= capital
    db.add(
        WalletPosition(
            membership_id=member.id,
            user_id=member.user_id,
            capital=capital,
            current_value=capital,
            status="active",
        )
    )
    db.add(
        WalletEntry(
            user_id=member.user_id,
            membership_id=member.id,
            event_key=f"reserve:{member.id}",
            kind="reservation",
            amount=-capital,
            available_after=wallet.available,
        )
    )
    await db.flush()


async def update_contest(
    db: AsyncSession,
    contest_id: UUID,
    instant: datetime,
    *,
    run_id: UUID | None = None,
    session_date: date | None = None,
    final: bool = False,
    cancelled: bool = False,
) -> None:
    """Caller holds the contest lock. Lock wallets in stable order across contests."""
    positions = list(
        (
            await db.scalars(
                select(WalletPosition)
                .join(ContestMembership, ContestMembership.id == WalletPosition.membership_id)
                .where(
                    ContestMembership.contest_id == contest_id,
                    WalletPosition.status == "active",
                )
                .order_by(WalletPosition.user_id)
            )
        ).all()
    )
    records = (
        {
            row.membership_id: row
            for row in (
                await db.scalars(select(ValuationRecord).where(ValuationRecord.run_id == run_id))
            )
        }
        if run_id
        else {}
    )
    for position in positions:
        wallet = await lock_wallet(db, position.user_id)
        record = records.get(position.membership_id)
        if record is not None:
            position.current_value = record.total_value
            position.run_id, position.session_date = run_id, session_date
        if not (final or cancelled):
            continue
        refund = cancelled or record is None
        returned = position.capital if refund else position.current_value
        position.status = "refunded" if refund else "settled"
        position.current_value, position.released_at = returned, instant
        wallet.available += returned
        kind = "cancellation" if cancelled else "no_submission" if refund else "settlement"
        db.add(
            WalletEntry(
                user_id=position.user_id,
                membership_id=position.membership_id,
                event_key=f"release:{position.membership_id}",
                kind=kind,
                amount=returned,
                available_after=wallet.available,
            )
        )
    await db.flush()
