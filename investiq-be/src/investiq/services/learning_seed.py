"""Reviewed development curriculum only; never creates learner activity."""

from importlib.resources import files
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.models.learning import Course, Lesson, LessonVersion

NAMESPACE = UUID("353fa435-6252-40bf-939f-dfeec4c43c43")


class SeedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    prompt: str = Field(min_length=1, max_length=1000)
    options: list[str] = Field(min_length=2, max_length=10)
    correct: int = Field(ge=0)
    explanation: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def valid_choice(self) -> "SeedQuestion":
        if self.correct >= len(self.options):
            raise ValueError("Correct option is out of range")
        return self


class SeedLesson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    paragraphs: list[str] = Field(min_length=1, max_length=50)
    questions: list[SeedQuestion] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_keys(self) -> "SeedLesson":
        if len({q.key for q in self.questions}) != len(self.questions):
            raise ValueError("Duplicate question keys")
        return self


class SeedCourse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{0,79}$")
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1000)
    lessons: list[SeedLesson] = Field(min_length=1, max_length=50)


async def seed_curriculum(factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    if settings.environment not in {"development", "test"}:
        raise AppError(
            403, "development_curriculum_only", "This curriculum seed is for development and tests"
        )
    courses = TypeAdapter(list[SeedCourse]).validate_json(
        files("investiq.data").joinpath("learning_curriculum_v1.json").read_text()
    )
    async with factory() as db, db.begin():
        await db.execute(text("SELECT pg_advisory_xact_lock(742017)"))
        for data in courses:
            course_id = uuid5(NAMESPACE, data.slug)
            course = await db.get(Course, course_id)
            expected = dict(slug=data.slug, title=data.title, description=data.description)
            if course is None:
                db.add(Course(id=course_id, **expected))
                await db.flush()
            elif any(getattr(course, key) != value for key, value in expected.items()):
                raise AppError(
                    409, "curriculum_changed", "Published curriculum differs from its seed"
                )
            for position, lesson_data in enumerate(data.lessons, 1):
                lesson_id = uuid5(course_id, str(position))
                if await db.get(Lesson, lesson_id) is None:
                    db.add(Lesson(id=lesson_id, course_id=course_id, position=position, xp=25))
                    await db.flush()
                version_id = uuid5(lesson_id, "version-1")
                version = await db.get(LessonVersion, version_id)
                values = dict(
                    title=lesson_data.title,
                    paragraphs=lesson_data.paragraphs,
                    questions=[q.model_dump() for q in lesson_data.questions],
                )
                if version is None:
                    db.add(LessonVersion(id=version_id, lesson_id=lesson_id, version=1, **values))
                elif any(getattr(version, key) != value for key, value in values.items()):
                    raise AppError(
                        409,
                        "curriculum_changed",
                        "Publish a new version instead of editing existing content",
                    )
        await db.flush()
