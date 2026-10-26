from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Fact(BaseModel):
    id: str
    category: Literal["summary", "benchmark", "concentration", "contribution", "worked", "review"]
    text: str
    source: str


class LessonEvidence(BaseModel):
    lesson_id: UUID
    version_id: UUID
    version: int
    title: str
    paragraphs: list[str]


class CoachEvidence(BaseModel):
    contest_id: UUID
    record_id: UUID
    run_id: UUID
    submission_id: UUID
    session_date: date
    is_final: bool
    is_current: bool
    metric_version: str
    evidence_version: str = "coach-evidence-v1"
    data_kind: Literal["synthetic", "yahoo"] = "synthetic"
    facts: list[Fact]
    lessons: list[LessonEvidence]
    limitations: list[str]


class CoachPlan(BaseModel):
    """No unrestricted prose or numbers: the model selects verified evidence and learning focus."""

    model_config = ConfigDict(extra="forbid")
    focus_fact_ids: list[str] = Field(min_length=2, max_length=6)
    worked_fact_ids: list[str] = Field(max_length=3)
    review_fact_ids: list[str] = Field(min_length=1, max_length=3)
    lesson_version_ids: list[str] = Field(min_length=1, max_length=3)
    reflection: Literal["allocation", "benchmark", "evidence"]


class ReportBody(BaseModel):
    format_version: str = "coach-report-v1"
    summary: list[Fact]
    focus: list[Fact]
    what_worked: list[Fact]
    review_points: list[Fact]
    learning_actions: list[LessonEvidence]
    reflection_question: str
    limitations: list[str]


class CreateCoachInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contest_id: UUID


class CoachJobOut(BaseModel):
    id: UUID
    contest_id: UUID
    session_date: date
    status: str
    provider: str
    model: str
    prompt_version: str
    evidence_hash: str
    generation: int
    attempts: int
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    next_attempt_at: datetime
    evidence: CoachEvidence
    report: ReportBody | None


class JobPage(BaseModel):
    items: list[CoachJobOut]
    next_cursor: str | None


class CoachSettingsOut(BaseModel):
    enabled: bool
    provider: str
    model: str
    max_attempts: int


class ReflectionInput(CreateCoachInput):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=2000)


class ReflectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    contest_id: UUID
    body: str
    created_at: datetime


class ReflectionPage(BaseModel):
    items: list[ReflectionOut]
    next_cursor: str | None


class UsageOut(BaseModel):
    attempt: int
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    estimated_cost_usd: Decimal | None
    error_code: str | None
