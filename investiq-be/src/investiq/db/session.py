from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from investiq.core.config import Settings

# Advance with each schema migration. Readiness rejects an incompatible database.
SCHEMA_REVISION = "0012_martin"


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={
            "timeout": settings.dependency_timeout_seconds,
            "server_settings": {"timezone": "UTC"},
        },
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with factory() as session:
        # Services own `async with session.begin()` transaction boundaries.
        # No automatic commit on successful HTTP responses.
        yield session
