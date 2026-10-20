from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StrictBool,
    ValidationInfo,
    field_validator,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def valid_text(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, str):
            # Normalize display/email fields explicitly; passwords must remain byte-for-byte.
            if info.field_name in {"name", "email"}:
                value = value.strip()
            try:
                value.encode("utf-8")
            except UnicodeError as exc:
                raise ValueError("Use valid Unicode text") from exc
            if info.field_name == "name" and any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Display names must be a single line without control characters")
        return value


class EmailInput(Input):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.lower()


class LoginInput(EmailInput):
    password: SecretStr

    @field_validator("password")
    @classmethod
    def bound_password(cls, value: SecretStr) -> SecretStr:
        if not 1 <= len(value.get_secret_value()) <= 128:
            raise ValueError("Password must be between 1 and 128 characters")
        return value


class RegisterInput(LoginInput):
    name: str = Field(min_length=1, max_length=70)

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 12:
            raise ValueError("Use at least 12 characters")
        return value


class TokenInput(Input):
    token: SecretStr

    @field_validator("token")
    @classmethod
    def bound_token(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) != 43 or any(
            c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in raw
        ):
            raise ValueError("Invalid token")
        return value


class ResetInput(TokenInput):
    password: SecretStr

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: SecretStr) -> SecretStr:
        if not 12 <= len(value.get_secret_value()) <= 128:
            raise ValueError("Use between 12 and 128 characters")
        return value


class ProfileUpdate(Input):
    name: str | None = Field(default=None, min_length=1, max_length=70)
    weekly_goal: Literal[35, 75, 105, 210] | None = None

    @field_validator("name", "weekly_goal", mode="before")
    @classmethod
    def no_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Explicit null is not supported")
        return value


class PreferencesUpdate(Input):
    contest: StrictBool | None = None
    ranks: StrictBool | None = None
    ai: StrictBool | None = None
    replies: StrictBool | None = None
    digest: StrictBool | None = None

    @field_validator("*", mode="before")
    @classmethod
    def no_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Explicit null is not supported")
        return value


class PrivacyUpdate(Input):
    public: StrictBool | None = None
    holdings: StrictBool | None = None

    @field_validator("*", mode="before")
    @classmethod
    def no_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Explicit null is not supported")
        return value


class PreferencesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    contest: bool
    ranks: bool
    ai: bool
    replies: bool
    digest: bool


class PrivacyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    public: bool
    holdings: bool


class OnboardingInput(Input):
    version: int = Field(ge=1)
    answers: dict[str, str] = Field(min_length=5, max_length=5)


class Option(BaseModel):
    id: str
    title: str
    description: str


class Question(BaseModel):
    id: str
    tag: str
    title: str
    description: str
    options: list[Option]


class QuestionsOut(BaseModel):
    version: int
    questions: list[Question]


class OnboardingOut(BaseModel):
    version: int
    answers: dict[str, str]
    experience: str
    learning_profile: str
    classification_version: int
    completed_at: datetime


class MeOut(BaseModel):
    id: UUID
    email: str
    name: str
    role: Literal["user", "admin"]
    email_verified: bool
    weekly_goal: int
    preferences: PreferencesOut
    privacy: PrivacyOut
    onboarding: OnboardingOut | None


class SessionOut(BaseModel):
    id: UUID
    current: bool
    created_at: datetime
    expires_at: datetime


class Message(BaseModel):
    message: str


class CsrfOut(BaseModel):
    csrf_token: str
