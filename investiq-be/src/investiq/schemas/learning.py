from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
