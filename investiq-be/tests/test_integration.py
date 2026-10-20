from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import text

from investiq.api import health
from investiq.core.config import Settings
from investiq.db.session import SCHEMA_REVISION, make_engine
from investiq.main import create_app
from tests.helpers import test_client as api_client

pytestmark = pytest.mark.integration


async def test_ready_rejects_incompatible_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "SCHEMA_REVISION", "future_schema_revision")
    async with api_client(create_app(Settings())) as client:
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"] == {"postgresql": "unavailable", "redis": "ok"}


async def test_ready_with_real_infrastructure() -> None:
    async with api_client(create_app(Settings())) as client:
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 200, response.text
        assert response.json() == {
            "status": "ready",
            "checks": {"postgresql": "ok", "redis": "ok"},
        }


async def test_postgres_migration_decimal_utc_and_rollback() -> None:
    engine = make_engine(Settings())
    try:
        async with engine.connect() as conn:
            assert (
                await conn.scalar(text("SELECT version_num FROM alembic_version"))
                == SCHEMA_REVISION
            )
            assert await conn.scalar(text("SHOW TIMEZONE")) == "UTC"
            # Temporary tables cannot alter the application schema or other test runs.
            await conn.execute(
                text("""CREATE TEMP TABLE foundation_probe (
                id UUID PRIMARY KEY, amount NUMERIC(20,4) NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL
            ) ON COMMIT PRESERVE ROWS""")
            )
            await conn.commit()
            transaction = await conn.begin()
            identifier, observed = uuid4(), datetime.now(UTC)
            await conn.execute(
                text("""INSERT INTO foundation_probe VALUES
                (:id, :amount, :observed)"""),
                {"id": identifier, "amount": Decimal("123456789.1234"), "observed": observed},
            )
            row = (await conn.execute(text("SELECT * FROM foundation_probe"))).one()
            assert row.id == identifier
            assert row.amount == Decimal("123456789.1234")
            assert isinstance(row.amount, Decimal)
            assert row.observed_at == observed
            await transaction.rollback()
            assert await conn.scalar(text("SELECT count(*) FROM foundation_probe")) == 0
    finally:
        await engine.dispose()


async def test_real_redis_roundtrip_and_expiry() -> None:
    config = Settings()
    client = Redis.from_url(config.redis_url.get_secret_value(), decode_responses=True)
    key = f"investiq:test:{uuid4()}"
    try:
        assert await client.set(key, "foundation", ex=30, nx=True)
        assert not await client.set(key, "duplicate", ex=30, nx=True)
        assert await client.get(key) == "foundation"
        assert 0 < await client.ttl(key) <= 30
    finally:
        await client.delete(key)
        await client.aclose()
