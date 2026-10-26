from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

MarketCap = Literal["large", "mid", "small"]
InstrumentKind = Literal["equity", "benchmark"]
MarketDataKind = Literal["fixture", "yahoo"]


class SectorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    slug: str
    name: str


class InstrumentOut(BaseModel):
    id: UUID
    symbol: str
    name: str
    exchange: str
    kind: InstrumentKind
    currency: Literal["INR", "POINTS"]
    sector: SectorOut | None
    market_cap: MarketCap | None
    active: bool
    excluded: bool
    data_kind: MarketDataKind = "fixture"


class InstrumentPage(BaseModel):
    items: list[InstrumentOut]
    next_cursor: str | None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    session_date: date
    status: Literal["open", "closed", "unsupported"]
    opens_at: datetime | None
    closes_at: datetime | None
    available_at: datetime | None
    reason: str | None
    calendar_version: str
    source: str


class SectorPage(BaseModel):
    items: list[SectorOut]
    next_cursor: None = None


class SessionPage(BaseModel):
    items: list[SessionOut]
    next_cursor: None = None


class PricePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instrument_id: UUID
    close: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    open: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)

    @field_validator("close", "open", mode="before")
    @classmethod
    def exact_input(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("Provider prices must be decimal strings or Decimal values")
        return value


class ProviderBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str = Field(min_length=1, max_length=60)
    dataset_version: str = Field(min_length=1, max_length=40)
    data_kind: MarketDataKind
    session_date: date
    observed_at: AwareDatetime
    source_published_at: AwareDatetime
    points: tuple[PricePoint, ...] = Field(min_length=1, max_length=10000)


class QuoteOut(BaseModel):
    instrument_id: UUID
    symbol: str
    currency: str
    close: Decimal | None
    session_date: date | None
    observed_at: datetime | None
    source_published_at: datetime | None
    ingested_at: datetime | None
    source: str | None
    dataset_version: str | None
    data_kind: MarketDataKind = "fixture"
    open: Decimal | None = None
    day_change_pct: Decimal | None = None
    freshness: Literal["current_eod", "stale", "missing"]
    blocked_reason: str | None
    eligible_for_simulation: bool
    eligible_for_live_use: Literal[False] = False


class QuoteBatchOut(BaseModel):
    as_of: datetime
    expected_session_date: date
    calendar_version: str
    all_current: bool
    data_kind: MarketDataKind = "fixture"
    items: list[QuoteOut]


class MarketStatusOut(BaseModel):
    mode: Literal["fixture", "yahoo", "disabled"]
    provider: str | None
    benchmark_id: UUID | None
    latest_session_date: date | None
    last_imported_at: datetime | None
    last_error_code: str | None
    calendar_end: date | None
    update_policy: str = "Daily after 18:00 IST, once a complete EOD dataset is available"
