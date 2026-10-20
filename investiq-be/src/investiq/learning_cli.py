"""Initialize development curriculum: python -m investiq.learning_cli."""

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.db.session import make_engine
from investiq.services.learning_seed import seed_curriculum


async def seed() -> None:
    settings = Settings()
    engine = make_engine(settings)
    try:
        await seed_curriculum(async_sessionmaker(engine, expire_on_commit=False), settings)
        print(
            "Development curriculum initialized: 2 courses, 6 lessons. No learner activity created."
        )
    except AppError as exc:
        raise SystemExit(f"{exc.code}: {exc.message}") from None
    except Exception:
        raise SystemExit(
            "learning_initialization_failed: check the configured infrastructure"
        ) from None
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
