from fastapi import APIRouter
from sqlalchemy import func, select

from investiq.api.identity import Service, UserContext
from investiq.models.contest import Contest, ContestMembership
from investiq.models.wallet import WalletEntry, WalletPosition
from investiq.schemas.wallet import (
    PortfolioOverviewOut,
    WalletEntryOut,
    WalletOut,
    WalletPositionOut,
)
from investiq.services.wallet import OPENING_CAPITAL, lock_wallet, portfolio_overview

router = APIRouter(tags=["virtual wallet"])


@router.get("/me/portfolio", response_model=PortfolioOverviewOut)
async def portfolio(identity: Service, principal: UserContext) -> PortfolioOverviewOut:
    async with identity.factory() as db, db.begin():
        user = await identity.authenticated_user(db, principal)
        return await portfolio_overview(db, user.id)


@router.get("/me/wallet", response_model=WalletOut)
async def wallet(identity: Service, principal: UserContext) -> WalletOut:
    async with identity.factory() as db, db.begin():
        user = await identity.authenticated_user(db, principal)
        funds = await lock_wallet(db, user.id)
        rows = (
            await db.execute(
                select(WalletPosition, Contest)
                .join(ContestMembership, ContestMembership.id == WalletPosition.membership_id)
                .join(Contest, Contest.id == ContestMembership.contest_id)
                .where(WalletPosition.user_id == user.id, WalletPosition.status == "active")
                .order_by(Contest.starts_at, Contest.id)
            )
        ).all()
        positions = [
            WalletPositionOut(
                contest_id=c.id,
                name=c.name,
                capital=p.capital,
                current_value=p.current_value,
                pnl=p.current_value - p.capital,
                session_date=p.session_date,
                status=c.status,
            )
            for p, c in rows
        ]
        entries = (
            await db.execute(
                select(WalletEntry, Contest.id, Contest.name)
                .outerjoin(ContestMembership, ContestMembership.id == WalletEntry.membership_id)
                .outerjoin(Contest, Contest.id == ContestMembership.contest_id)
                .where(WalletEntry.user_id == user.id)
                .order_by(WalletEntry.created_at.desc(), WalletEntry.id.desc())
                .limit(30)
            )
        ).all()
        legacy = await db.scalar(
            select(func.count())
            .select_from(ContestMembership)
            .outerjoin(WalletPosition, WalletPosition.membership_id == ContestMembership.id)
            .where(ContestMembership.user_id == user.id, WalletPosition.membership_id.is_(None))
        )
        invested = sum((p.current_value for p in positions), start=OPENING_CAPITAL * 0)
        reserved = sum((p.capital for p in positions), start=OPENING_CAPITAL * 0)
        total = funds.available + invested
        return WalletOut(
            opening_capital=OPENING_CAPITAL,
            available=funds.available,
            reserved_capital=reserved,
            invested_value=invested,
            total_value=total,
            pnl=total - OPENING_CAPITAL,
            return_pct=((total / OPENING_CAPITAL) - 1) * 100,
            legacy_contest_count=legacy or 0,
            positions=positions,
            recent_entries=[
                WalletEntryOut(
                    id=e.id,
                    kind=e.kind,
                    amount=e.amount,
                    available_after=e.available_after,
                    created_at=e.created_at,
                    contest_id=cid,
                    contest_name=name,
                )
                for e, cid, name in entries
            ],
        )
