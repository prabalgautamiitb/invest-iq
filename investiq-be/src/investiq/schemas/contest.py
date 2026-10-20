from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

Status = Literal[
    "draft", "scheduled", "open", "locked", "running", "settling", "completed", "cancelled"
]
Visibility = Literal["public", "private"]
Organizer = Literal["community", "platform"]
Level = Literal["beginner", "advanced", "all"]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class RulesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capital: Decimal = Field(
        default=Decimal("1000000.00"),
        gt=0,
        le=Decimal("100000000"),
        max_digits=12,
        decimal_places=2,
    )
    min_holdings: int = Field(default=5, ge=1, le=100)
    max_holdings: int = Field(default=12, ge=1, le=100)
    max_position_bps: int = Field(default=2500, ge=100, le=10000)
    simulated_cost_bps: int = Field(default=10, ge=0, le=1000)
    benchmark_id: UUID
    eligible_instrument_ids: list[UUID] = Field(min_length=1, max_length=500)
    # Fixed MVP execution policy: no real money, intraday quotes, or in-contest trades.
    pricing_policy: Literal["published_eod_before_lock"] = "published_eod_before_lock"
    residual_cash_allowed: Literal[True] = True
    cost_policy: Literal["once_on_submission_notional"] = "once_on_submission_notional"
    share_policy: Literal["whole_shares_floor"] = "whole_shares_floor"
    trading_policy: Literal["locked_before_start"] = "locked_before_start"
    data_kind: Literal["fixture"] = "fixture"

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (
            self.min_holdings > self.max_holdings
            or len(set(self.eligible_instrument_ids)) != len(self.eligible_instrument_ids)
            or len(self.eligible_instrument_ids) < self.min_holdings
        ):
            raise ValueError("Holdings limits must fit a distinct eligible universe")
        return self


class ContestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Text
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    visibility: Visibility = "private"
    level: Level = "all"
    capacity: int = Field(default=100, ge=1, le=10000)
    entry_opens_at: AwareDatetime
    entry_closes_at: AwareDatetime
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    rules: RulesInput

    @model_validator(mode="after")
    def schedule(self) -> Self:
        if not self.entry_opens_at < self.entry_closes_at < self.starts_at < self.ends_at:
            raise ValueError("Require entry open < entry close < start < end")
        return self


class ContestOut(BaseModel):
    first_session_closes_at: datetime | None
    first_results_available_at: datetime | None
    organizer: Organizer
    can_manage: bool
    id: UUID
    owner_id: UUID
    name: str
    description: str
    visibility: Visibility
    level: Level
    status: Status
    capacity: int
    member_count: int
    is_owner: bool
    joined: bool
    entry_opens_at: datetime
    entry_closes_at: datetime
    starts_at: datetime
    ends_at: datetime
    rule_id: UUID
    rule_version: int
    rules: RulesInput


class ContestPage(BaseModel):
    items: list[ContestOut]
    next_cursor: str | None


class InvitationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class InvitationOut(BaseModel):
    id: UUID
    contest_id: UUID
    contest_name: str
    status: Literal["pending", "accepted", "declined", "revoked", "expired"]
    expires_at: datetime
    # Email is visible only to the host and recipient, never public contest viewers.
    email: str


class InvitationPage(BaseModel):
    items: list[InvitationOut]
    next_cursor: str | None


class TransitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["publish", "cancel"]
