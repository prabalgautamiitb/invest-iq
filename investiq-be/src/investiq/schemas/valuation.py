from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class RankOut(BaseModel):
    entry_id: UUID
    label: str
    is_you: bool
    rank: int
    total_value: Decimal
    return_pct: Decimal
    benchmark_return_pct: Decimal
    excess_return_pct: Decimal
    max_drawdown_pct: Decimal


class LeaderboardOut(BaseModel):
    contest_id: UUID
    contest_name: str
    contest_status: str
    run_id: UUID | None
    session_date: date | None
    valued_at: datetime | None
    expected_session_date: date | None
    is_current: bool
    is_final: bool
    job_status: Literal["waiting", "blocked", "succeeded"]
    error_code: str | None
    participant_count: int
    member_count: int
    items: list[RankOut]
    next_cursor: str | None
    calculation_version: str = "eod-valuation-v1"
    data_kind: Literal["fixture"] = "fixture"


class MetricsOut(BaseModel):
    run_id: UUID
    session_date: date
    rank: int
    submission_id: UUID
    capital: Decimal
    holdings_value: Decimal
    cash: Decimal
    fee: Decimal
    total_value: Decimal
    pnl: Decimal
    return_pct: Decimal
    benchmark_return_pct: Decimal
    excess_return_pct: Decimal
    peak_value: Decimal
    max_drawdown_pct: Decimal
    largest_position_pct: Decimal
    concentration_hhi: Decimal
    holding_count: int
    sector_count: int
    positions: list[dict[str, str | int]]


class PerformanceOut(BaseModel):
    contest_id: UUID
    contest_name: str
    contest_status: str
    is_current: bool
    is_final: bool
    expected_session_date: date | None
    error_code: str | None
    has_submission: bool
    metrics: MetricsOut | None
    series: list[MetricsOut]
    next_cursor: str | None


class DashboardItem(BaseModel):
    contest_id: UUID
    name: str
    status: str
    has_submission: bool
    session_date: date | None
    is_current: bool
    is_final: bool
    rank: int | None
    total_value: Decimal | None
    pnl: Decimal | None
    return_pct: Decimal | None


class DashboardOut(BaseModel):
    joined_count: int
    active_count: int
    completed_count: int
    cancelled_count: int
    submitted_count: int
    wins: int
    valued_count: int
    latest_snapshot_value: Decimal
    latest_snapshot_pnl: Decimal
    all_valued_current: bool
    items: list[DashboardItem]


class ContestHistoryOut(BaseModel):
    items: list[DashboardItem]
    next_cursor: str | None
