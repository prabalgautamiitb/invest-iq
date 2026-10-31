import ssl

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.ai.workflow import checkpoint_url
from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.db.session import connection_options, make_engine
from investiq.deploy_cli import bootstrap, validate_deployment
from investiq.jobs.scheduler import SchedulerLease
from investiq.main import create_app
from investiq.models.identity import User
from investiq.models.learning import Course
from investiq.models.market import Instrument, PriceSnapshot
from investiq.models.rewards import RewardItem
from investiq.services.market_ingestion import ensure_market_mode
from tests.conftest import CapturedMailer
from tests.helpers import test_client as api_client


def hosted_settings(**changes: object) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "environment": "production",
            "hosted_simulation_enabled": True,
            "database_url": "postgresql://user:secret@db.example/db?sslmode=require",
            "redis_url": "rediss://user:secret@redis.example:6379/0",
            "celery_broker_url": "rediss://user:secret@redis.example:6379/0?ssl_cert_reqs=required",
            "frontend_url": "https://app.example",
            "cors_origins": ["https://app.example", "https://admin.example"],
            "smtp_host": "smtp.example",
            "smtp_starttls": True,
            "smtp_port": 587,
            "smtp_username": "mail-user",
            "smtp_password": "mail-secret",
            "mail_from": "InvestIQ <mail@example.com>",
            "ai_provider": "disabled",
            "market_data_mode": "yahoo",
            "database_pool_size": 1,
            "database_max_overflow": 0,
            **changes,
        },
    )


def test_hosted_simulation_is_explicit_and_keeps_disabled_mode_blocked() -> None:
    with pytest.raises(AppError):
        ensure_market_mode(Settings(_env_file=None, environment="production"))
    ensure_market_mode(hosted_settings())
    with pytest.raises(AppError):
        ensure_market_mode(hosted_settings(market_data_mode="disabled"))


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
def test_provider_database_urls_have_verified_asyncpg_tls_and_libpq_checkpoint_url(
    scheme: str,
) -> None:
    config = hosted_settings(database_url=f"{scheme}://user:secret@db.example/db?sslmode=require")
    url, options = connection_options(config)
    assert url.drivername == "postgresql+asyncpg" and "sslmode" not in url.query
    assert isinstance(options["ssl"], ssl.SSLContext)
    assert options["ssl"].check_hostname
    assert options["ssl"].verify_mode == ssl.CERT_REQUIRED
    assert checkpoint_url(config) == "postgresql://user:secret@db.example/db?sslmode=require"
    assert "secret" not in repr(config)
    validate_deployment(config)


@pytest.mark.parametrize(
    "change",
    [
        {"hosted_simulation_enabled": False},
        {"frontend_url": "http://app.example"},
        {"cors_origins": ["https://other.example"]},
        {"redis_url": "redis://redis.example:6379/0"},
        {"celery_broker_url": "rediss://redis.example:6379/0"},
        {"smtp_starttls": False},
        {"smtp_password": ""},
        {"ai_provider": "ollama"},
        {"market_data_mode": "fixture"},
        {"database_url": "postgresql://user:secret@db.example/db"},
        {
            "database_url": "postgresql://user:secret@db.example/db?sslmode=require&channel_binding=require"
        },
    ],
)
def test_release_preflight_rejects_incomplete_hosted_configuration(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        validate_deployment(hosted_settings(**change))


def test_invalid_database_url_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="not a connection URL")


@pytest.mark.integration
async def test_bootstrap_is_repeatable_and_does_not_invent_users_or_market_prices(
    identity_settings: Settings,
) -> None:
    settings = identity_settings.model_copy(
        update={
            "environment": "production",
            "hosted_simulation_enabled": True,
            "market_data_mode": "yahoo",
        }
    )
    engine = make_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def counts() -> tuple[int, ...]:
        async with factory() as db:
            return tuple(
                [
                    int(await db.scalar(select(func.count()).select_from(model)) or 0)
                    for model in [User, PriceSnapshot, Course, RewardItem, Instrument]
                ]
            )

    try:
        before = await counts()
        await bootstrap(settings)
        first = await counts()
        await bootstrap(settings)
        assert await counts() == first
        assert first[:2] == before[:2]
        assert first[2] > 0 and first[3] > 0 and first[4] >= 51
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_scheduler_lease_only_allows_one_process_and_transfers_after_release(
    identity_settings: Settings,
) -> None:
    one, two = SchedulerLease(identity_settings), SchedulerLease(identity_settings)
    try:
        assert one.acquire()
        one.heartbeat()
        assert not two.acquire()
        one.close()
        assert two.acquire()
        two.heartbeat()
    finally:
        one.close()
        two.close()


@pytest.mark.integration
async def test_production_entry_keeps_secure_cookies_and_private_identity(
    identity_settings: Settings,
) -> None:
    from uuid import uuid4

    settings = identity_settings.model_copy(
        update={
            "environment": "production",
            "hosted_simulation_enabled": True,
            "cors_origins": ["https://app.example"],
        }
    )
    async with api_client(
        create_app(settings, CapturedMailer()), base_url="https://app.example"
    ) as client:
        csrf = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
        response = await client.post(
            "/api/v1/auth/register",
            headers={
                "X-CSRF-Token": csrf,
                "Origin": "https://app.example",
            },
            json={
                "email": f"deploy-{uuid4()}@example.com",
                "name": "Hosted learner",
                "password": "production test password 93",
            },
        )
        assert response.status_code == 201
        cookie = response.headers["set-cookie"]
        assert "__Host-investiq_session=" in cookie and "Secure" in cookie and "HttpOnly" in cookie
        assert (await client.get("/api/v1/me")).status_code == 200
        assert (
            await client.patch(
                "/api/v1/me",
                json={"name": "Forged"},
                headers={"Origin": "https://evil.example", "X-CSRF-Token": csrf},
            )
        ).status_code == 403
