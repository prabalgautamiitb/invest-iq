import asyncio

from alembic import context

from investiq.core.config import Settings
from investiq.db.base import Base
from investiq.db.session import make_engine
from investiq.models import (  # noqa: F401 -- register domain metadata
    coach,
    community,
    contest,
    identity,
    learning,
    market,
    martin,
    portfolio,
    rewards,
    valuation,
    wallet,
)


def run_sync(connection: object) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    engine = make_engine(Settings())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_sync)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=Settings().database_url.get_secret_value(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
