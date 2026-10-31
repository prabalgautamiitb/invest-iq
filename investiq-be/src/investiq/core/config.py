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
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=20)
    hosted_simulation_enabled: bool = False
    deployment_mode: Literal["worker", "free_demo"] = "worker"
    free_demo_ai_daily_limit: int = Field(default=20, ge=1, le=100)
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6380/0")
    celery_broker_url: SecretStr = SecretStr("redis://127.0.0.1:6380/1")
    valuation_queue: str = Field(default="investiq.valuation", pattern=r"^[a-zA-Z0-9._-]{1,100}$")
    valuation_scan_seconds: int = Field(default=60, ge=10, le=3600)
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://admin.localhost:5173",
    ]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    dependency_timeout_seconds: float = Field(default=3, gt=0, le=30)
    public_contest_fixtures_enabled: bool = False
    market_data_mode: Literal["fixture", "yahoo", "disabled"] = "fixture"
    market_scan_seconds: int = Field(default=300, ge=60, le=3600)
    market_news_enabled: bool = True
    yahoo_timeout_seconds: int = Field(default=45, ge=5, le=60)
    session_days: int = Field(default=7, ge=1, le=30)
    auth_rate_limit: int = Field(default=10, ge=1)
    auth_rate_window_seconds: int = Field(default=900, ge=1)
    ai_provider: Literal["disabled", "ollama", "gemini"] = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = Field(default="llama3.1:8b", min_length=1, max_length=120)
    gemini_model: str = Field(default="", max_length=120)
    gemini_api_key: SecretStr = SecretStr("")
    ai_timeout_seconds: int = Field(default=45, ge=5, le=60)
    ai_scan_seconds: int = Field(default=10, ge=5, le=60)
    martin_request_limit: int = Field(default=20, ge=1, le=1000)
    ai_request_limit: int = Field(default=5, ge=1, le=1000)
    community_write_limit: int = Field(default=60, ge=1, le=10000)
    community_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
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
        from sqlalchemy.engine import make_url
        from sqlalchemy.exc import ArgumentError

        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("Use a PostgreSQL connection URL") from None
        if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}:
            raise ValueError("Use a PostgreSQL connection URL")
        canonical = url.set(drivername="postgresql+asyncpg")
        if "ssl" in canonical.query:
            if "sslmode" in canonical.query:
                raise ValueError("Specify sslmode only once")
            mode = canonical.query["ssl"]
            if not isinstance(mode, str):
                raise ValueError("Specify sslmode only once")
            canonical = canonical.update_query_dict({"sslmode": mode})
            canonical = canonical.difference_update_query(["ssl"])
        PostgresDsn(canonical.render_as_string(hide_password=False))
        return SecretStr(canonical.render_as_string(hide_password=False))

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

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Use an Ollama HTTP(S) server origin without credentials or a path")
        return value.rstrip("/")
