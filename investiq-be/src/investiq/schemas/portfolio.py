from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Mode = Literal["quantity", "weight"]


class PositionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument_id: UUID
    quantity: int | None = Field(default=None, strict=True, ge=1, le=1000000000)
    weight_pct: Decimal | None = Field(default=None, gt=0, le=100, max_digits=7, decimal_places=4)

    @field_validator("weight_pct", mode="before")
    @classmethod
    def exact_weight(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("Send percentages as decimal strings")
        return value

    @model_validator(mode="after")
    def allocation(self) -> Self:
        if (self.quantity is None) == (self.weight_pct is None):
            raise ValueError("Supply exactly one of quantity or weight_pct")
        return self


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, le=2147483646, strict=True)
    mode: Mode
    positions: list[PositionInput] = Field(max_length=100)

    @model_validator(mode="after")
    def positions_match(self) -> Self:
        if len({p.instrument_id for p in self.positions}) != len(self.positions):
            raise ValueError("Instruments must be distinct")
        if any((p.quantity is not None) != (self.mode == "quantity") for p in self.positions):
            raise ValueError("Positions must match the draft mode")
        return self


class DraftOut(BaseModel):
    id: UUID | None
    contest_id: UUID
    rule_id: UUID
    revision: int
    mode: Mode
    positions: list[PositionInput]
    updated_at: datetime | None
    editable: bool


class PriceEvidence(BaseModel):
    instrument_id: UUID
    symbol: str
    price: Decimal
    price_snapshot_id: UUID
    observed_at: datetime
    source_published_at: datetime
    ingested_at: datetime
    source: str
    dataset_version: str


class HoldingOut(PriceEvidence):
    quantity: int
    notional: Decimal


class PreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_revision: int = Field(ge=1, strict=True)


class SubmitInput(PreviewInput):
    preview_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class PreviewOut(BaseModel):
    contest_id: UUID
    rule_id: UUID
    draft_revision: int
    preview_hash: str
    capital: Decimal
    notional: Decimal
    fee: Decimal
    cash: Decimal
    holdings: list[HoldingOut]
    benchmark: PriceEvidence
    price_session_date: date
    calendar_version: str
    pricing_as_of: datetime
    locks_at: datetime
    calculation_version: Literal["whole-shares-v1"] = "whole-shares-v1"
    data_kind: Literal["fixture", "yahoo"] = "fixture"


class SubmissionOut(PreviewOut):
    id: UUID
    version: int
    submitted_at: datetime
    is_latest: bool


class SubmissionPage(BaseModel):
    items: list[SubmissionOut]
    next_cursor: str | None
