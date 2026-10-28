from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Kind = Literal["discussion", "idea", "market", "poll"]


class ContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=4000)
    kind: Kind = "discussion"
    group_id: UUID | None = None
    options: list[str] = Field(default_factory=list, max_length=6)
    closes_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def poll(self) -> "ContentInput":
        self.options = [s.strip() for s in self.options]
        if self.kind == "poll":
            if (
                not self.closes_at
                or not 2 <= len(self.options) <= 6
                or len(set(self.options)) != len(self.options)
                or any(not s or len(s) > 120 for s in self.options)
            ):
                raise ValueError(
                    "Polls need a closing time and 2–6 distinct options of 1–120 characters"
                )
        elif self.options or self.closes_at:
            raise ValueError("Only polls accept options and a closing time")
        return self


class CommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=4000)


class GroupInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=1, max_length=500)


class GroupOut(BaseModel):
    id: UUID
    name: str
    description: str
    members: int
    joined: bool
    visibility: Literal["members"] = "members"
    owned: bool = False
    posts: int = 0


class ContentOut(BaseModel):
    id: UUID
    author: str
    own: bool
    kind: str
    body: str
    group_id: UUID | None
    group_name: str | None = None
    created_at: datetime
    likes: int
    liked: bool
    saved: bool
    comments: int
    options: list[str]
    votes: list[int]
    my_vote: int | None
    closes_at: datetime | None
    poll_open: bool


class ContentPage(BaseModel):
    items: list[ContentOut]
    next_cursor: str | None


class FlagInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class VoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option: int = Field(ge=0, le=5, strict=True)


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=5, max_length=500)


class ModerateInput(ReportInput):
    action: Literal["hide", "restore", "dismiss"]


class ReportOut(BaseModel):
    resolved: bool
    id: UUID
    content_id: UUID
    body: str
    state: str
    reason: str
    created_at: datetime


class Message(BaseModel):
    message: str


class GroupPage(BaseModel):
    items: list[GroupOut]
    next_cursor: str | None


class ReportPage(BaseModel):
    items: list[ReportOut]
    next_cursor: str | None
