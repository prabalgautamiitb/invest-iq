from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ContentText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)
]
OptionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ContentQuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    prompt: str = Field(min_length=1, max_length=1000)
    options: list[OptionText] = Field(min_length=2, max_length=10)
    correct: int = Field(ge=0, le=9, strict=True)
    explanation: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def valid_options(self) -> "ContentQuestionInput":
        if self.correct >= len(self.options) or len(set(self.options)) != len(self.options):
            raise ValueError("Choose a valid answer and use distinct options")
        return self


class LessonContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=160)
    xp: int = Field(ge=1, le=1000, strict=True)
    paragraphs: list[ContentText] = Field(min_length=1, max_length=50)
    questions: list[ContentQuestionInput] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def distinct_questions(self) -> "LessonContentInput":
        if len({q.key for q in self.questions}) != len(self.questions):
            raise ValueError("Use distinct question keys")
        return self


class CourseContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{0,79}$")
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1000)
    lessons: list[LessonContentInput] = Field(min_length=1, max_length=50)


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question_key: str = Field(min_length=1, max_length=40)
    choice: int = Field(ge=0, le=9)


class AttemptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: UUID
    answers: list[AnswerInput] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def distinct(self) -> "AttemptInput":
        if len({a.question_key for a in self.answers}) != len(self.answers):
            raise ValueError("Answer each question exactly once")
        return self


class LessonSummary(BaseModel):
    id: UUID
    title: str
    position: int
    xp: int


class CourseOut(BaseModel):
    id: UUID
    slug: str
    title: str
    description: str
    lessons: list[LessonSummary]


class CoursePage(BaseModel):
    items: list[CourseOut]
    next_cursor: str | None = None


class QuestionOut(BaseModel):
    key: str
    prompt: str
    options: list[str]


class LessonOut(BaseModel):
    id: UUID
    course_id: UUID
    version_id: UUID
    version: int
    title: str
    paragraphs: list[str]
    xp: int
    questions: list[QuestionOut]


class FeedbackOut(BaseModel):
    question_key: str
    choice: int
    correct: bool
    explanation: str


class AttemptOut(BaseModel):
    id: UUID
    lesson_id: UUID
    version_id: UUID
    correct_count: int
    total: int
    passed: bool
    xp_awarded: int
    submitted_at: datetime
    feedback: list[FeedbackOut]


class AttemptPage(BaseModel):
    items: list[AttemptOut]
    next_cursor: str | None = None


class AchievementOut(BaseModel):
    code: str
    awarded_at: datetime


class ProgressOut(BaseModel):
    xp: int
    completed_lesson_ids: list[UUID]
    enrolled_course_ids: list[UUID]
    current_streak: int
    longest_streak: int
    last_learning_date: date | None
    timezone: str = "Asia/Kolkata"
    achievements: list[AchievementOut]
