import asyncio
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import RedisError
from sqlalchemy.pool import NullPool

from investiq.core.errors import AppError
from investiq.db.session import make_engine
from investiq.main import create_app
from investiq.services.ai_budget import reserve_generation
from tests.conftest import CapturedMailer


async def test_free_demo_releases_idle_database_connections(identity_settings):
    engine = make_engine(identity_settings.model_copy(update={"deployment_mode": "free_demo"}))
    try:
        assert isinstance(engine.pool, NullPool)
        async with engine.connect() as conn:
            assert await conn.exec_driver_sql("SELECT 1")
        assert engine.sync_engine.pool.status() == "NullPool"
    finally:
        await engine.dispose()


async def test_demo_ai_allowance_is_shared_atomic_and_fails_closed(identity_settings, monkeypatch):
    settings = identity_settings.model_copy(
        update={"deployment_mode": "free_demo", "free_demo_ai_daily_limit": 2}
    )
    app = create_app(settings, CapturedMailer())
    async with app.router.lifespan_context(app):
        outcomes = await asyncio.gather(
            *[reserve_generation(app.state.identity) for _ in range(8)], return_exceptions=True
        )
        assert outcomes.count(None) == 2
        errors = [e for e in outcomes if isinstance(e, AppError)]
        assert len(errors) == 6 and all(e.code == "daily_ai_limit" for e in errors)
        monkeypatch.setattr(app.state.redis, "eval", AsyncMock(side_effect=RedisError()))
        with pytest.raises(AppError, match="Please try again later") as error:
            await reserve_generation(app.state.identity)
        assert error.value.code == "rate_limit_unavailable"


async def test_worker_mode_does_not_use_demo_allowance(identity_settings, monkeypatch):
    app = create_app(identity_settings, CapturedMailer())
    async with app.router.lifespan_context(app):
        counter = AsyncMock(side_effect=AssertionError("worker mode must not use demo counter"))
        monkeypatch.setattr(app.state.redis, "eval", counter)
        await reserve_generation(app.state.identity)
        counter.assert_not_called()
