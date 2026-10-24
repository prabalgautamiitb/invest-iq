from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MartinInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=1000)
    conversation_id: UUID | None = None
    mode: Literal["learning", "performance"] = "learning"
    contest_id: UUID | None = None

    @model_validator(mode="after")
    def scope(self) -> "MartinInput":
        if self.mode == "learning" and self.contest_id is not None:
            raise ValueError("Select performance mode to use contest evidence")
        return self


class MartinSource(BaseModel):
    id: str
    kind: Literal["lesson", "performance", "status"]
    title: str
    text: str
    href: str
    session_date: str | None = None
    is_current: bool | None = None
    is_final: bool | None = None
    contest_id: UUID | None = None


class MartinPlan(BaseModel):
    """A conversational answer, its intent, and the evidence used to support it."""

    model_config = ConfigDict(extra="forbid")
    intent: Literal["explanation", "benefits", "personal_assessment", "comparison", "out_of_scope"]
    reply: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(max_length=6)
    follow_up: str = Field(min_length=1, max_length=200)


class MartinAnswer(BaseModel):
    introduction: str
    sources: list[MartinSource]
    follow_up: str
    limitation: str
    # Older saved answers have no intent and remain readable.
    intent: str = "explanation"


class MartinTurnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    question: str
    status: str
    answer: MartinAnswer | None
    attempts: int
    error_code: str | None
    created_at: datetime


class MartinConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    mode: str
    contest_id: UUID | None
    updated_at: datetime


class MartinConversationPage(BaseModel):
    items: list[MartinConversationOut]
    next_cursor: str | None


class MartinTurnPage(BaseModel):
    conversation: MartinConversationOut
    items: list[MartinTurnOut]
    next_cursor: str | None
