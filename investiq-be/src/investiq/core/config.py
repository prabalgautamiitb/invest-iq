from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INVESTIQ_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://investiq:investiq_local@127.0.0.1:5433/investiq"
    )
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6380/0")
    celery_broker_url: SecretStr = SecretStr("redis://127.0.0.1:6380/1")
    valuation_queue: str = Field(default="investiq.valuation", pattern=r"^[a-zA-Z0-9._-]{1,100}$")
    valuation_scan_seconds: int = Field(default=60, ge=10, le=3600)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    dependency_timeout_seconds: float = Field(default=3, gt=0, le=30)
    market_data_mode: Literal["fixture", "disabled"] = "fixture"
    session_days: int = Field(default=7, ge=1, le=30)
    auth_rate_limit: int = Field(default=10, ge=1)
    auth_rate_window_seconds: int = Field(default=900, ge=1)
    csrf_rate_limit: int = Field(default=60, ge=1)
    rate_limit_prefix: str = "investiq:identity"
    frontend_url: str = "http://localhost:5173"
    smtp_host: str = "127.0.0.1"
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_starttls: bool = False
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    mail_from: str = "InvestIQ <no-reply@investiq.local>"

    @property
    def cookie_name(self) -> str:
        return (
            "__Host-investiq_session"
            if self.environment == "production"
            else "investiq_dev_session"
        )

    @field_validator("frontend_url")
    @classmethod
    def validate_frontend_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use an absolute frontend HTTP(S) URL without query or fragment")
        return value.rstrip("/")

    @field_validator("database_url")
    @classmethod
    def validate_database(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        PostgresDsn(url)
        if not url.startswith("postgresql+asyncpg://"):
            raise ValueError("Use the postgresql+asyncpg driver")
        return value

    @field_validator("redis_url", "celery_broker_url")
    @classmethod
    def validate_redis(cls, value: SecretStr) -> SecretStr:
        RedisDsn(value.get_secret_value())
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_origins(cls, origins: list[str]) -> list[str]:
        from urllib.parse import urlsplit

        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise ValueError("CORS origins must be explicit HTTP(S) origins without paths")
        return origins
