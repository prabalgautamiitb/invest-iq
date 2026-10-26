import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import uuid4

import asyncpg
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from investiq.core.config import Settings


@dataclass
class CapturedMailer:
    messages: list[tuple[str, str, str]] = field(default_factory=list)
    fail: bool = False

    async def send(self, recipient: str, purpose: str, token: str) -> None:
        if self.fail:
            raise ConnectionError("Test email adapter unavailable")
        self.messages.append((recipient, purpose, token))

    def token(self, email: str, purpose: str) -> str:
        return next(
            token
            for recipient, kind, token in reversed(self.messages)
            if recipient == email and kind == purpose
        )


@asynccontextmanager
async def migrated_database() -> AsyncIterator[str]:
    config = Settings()
    base = make_url(config.database_url.get_secret_value())
    name = "investiq_integration_test_" + uuid4().hex
    admin_url = base.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    test_url = base.set(database=name).render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
            env={**os.environ, "INVESTIQ_DATABASE_URL": test_url},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        assert process.returncode == 0, (stdout.decode(), stderr.decode())
        yield test_url
    finally:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        finally:
            await admin.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def identity_database() -> AsyncIterator[str]:
    async with migrated_database() as url:
        yield url


@pytest_asyncio.fixture
async def market_settings() -> AsyncIterator[Settings]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from investiq.db.session import make_engine
    from investiq.services.market_ingestion import MarketIngestionService

    async with migrated_database() as url:
        config = Settings(
            database_url=SecretStr(url), environment="test", market_data_mode="fixture"
        )
        engine = make_engine(config)
        try:
            await MarketIngestionService(
                async_sessionmaker(engine, expire_on_commit=False), config
            ).seed_fixtures()
        finally:
            await engine.dispose()
        yield config


@pytest_asyncio.fixture
async def identity_settings(identity_database: str) -> Settings:
    return Settings(
        database_url=SecretStr(identity_database),
        environment="test",
        auth_rate_limit=10000,
        csrf_rate_limit=10000,
        rate_limit_prefix=f"investiq:test:{uuid4()}",
    )
