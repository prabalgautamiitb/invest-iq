from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class WalletPositionOut(BaseModel):
    contest_id: UUID
    name: str
    capital: Decimal
    current_value: Decimal
    pnl: Decimal
    session_date: date | None
    status: str


class WalletEntryOut(BaseModel):
    id: UUID
    kind: str
    amount: Decimal
    available_after: Decimal
    created_at: datetime
    contest_id: UUID | None
    contest_name: str | None


class WalletOut(BaseModel):
    currency: Literal["INR"] = "INR"
    virtual: bool = True
    opening_capital: Decimal
    available: Decimal
    reserved_capital: Decimal
    invested_value: Decimal
    total_value: Decimal
    pnl: Decimal
    return_pct: Decimal
    legacy_contest_count: int
    positions: list[WalletPositionOut]
    recent_entries: list[WalletEntryOut]


class PortfolioValuePoint(BaseModel):
    # The opening grant is a baseline, not a fabricated market close.
    session_date: date | None
    total_value: Decimal


class PortfolioOverviewOut(BaseModel):
    opening_capital: Decimal
    total_value: Decimal
    pnl: Decimal
    return_pct: Decimal
    latest_session_date: date | None
    active_contest_count: int
    unvalued_contest_count: int
    legacy_contest_count: int
    series: list[PortfolioValuePoint]
