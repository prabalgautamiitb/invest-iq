import ssl
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from investiq.core.config import Settings

# Advance with each schema migration. Readiness rejects an incompatible database.
SCHEMA_REVISION = "0016_virtual_wallet"


def connection_options(settings: Settings) -> tuple[URL, dict[str, Any]]:
    """Translate libpq provider URLs into asyncpg arguments without logging credentials."""
    url = make_url(settings.database_url.get_secret_value())
    options: dict[str, Any] = {
        "timeout": settings.dependency_timeout_seconds,
        "server_settings": {"timezone": "UTC"},
    }
    mode = url.query.get("sslmode")
    if mode is not None:
        if mode not in {"disable", "require", "verify-ca", "verify-full"}:
            raise ValueError("Use sslmode=verify-full (or require) for a hosted database")
        if mode == "disable":
            options["ssl"] = False
        else:
            root = url.query.get("sslrootcert")
            if root is not None and not isinstance(root, str):
                raise ValueError("Specify one SSL root certificate")
            # Hosted connections always verify the CA and hostname, including 'require'.
            options["ssl"] = ssl.create_default_context(cafile=root)
    binding = url.query.get("channel_binding")
    if binding not in {None, "disable", "prefer"}:
        raise ValueError("asyncpg does not support channel_binding=require; use verified TLS")
    url = url.difference_update_query(["sslmode", "sslrootcert", "channel_binding"])
    return url, options


def postgres_url(settings: Settings) -> str:
    """libpq/psycopg needs its own driver while retaining provider SSL options."""
    url = make_url(settings.database_url.get_secret_value()).set(drivername="postgresql")
    if url.query.get("sslmode") in {"require", "verify-ca", "verify-full"} and not url.query.get(
        "sslrootcert"
    ):
        # libpq otherwise looks for ~/.postgresql/root.crt, absent in serverless images.
        # Its system-root mode requires full certificate and hostname verification.
        url = url.update_query_dict({"sslrootcert": "system", "sslmode": "verify-full"})
    return url.render_as_string(hide_password=False)


def make_engine(settings: Settings) -> AsyncEngine:
    url, options = connection_options(settings)
    if settings.deployment_mode == "free_demo":
        # Return every connection after its transaction so hosted Postgres can sleep.
        return create_async_engine(url, poolclass=NullPool, connect_args=options)
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        connect_args=options,
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with factory() as session:
        # Services own `async with session.begin()` transaction boundaries.
        # No automatic commit on successful HTTP responses.
        yield session
