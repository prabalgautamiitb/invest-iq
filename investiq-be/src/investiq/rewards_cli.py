"""Initialize sandbox catalogue and reconcile genuine learning coin earnings."""

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.db.session import make_engine
from investiq.services.rewards import reconcile_earnings
from investiq.services.rewards_seed import seed_rewards


async def seed() -> None:
    settings = Settings()
    engine = make_engine(settings)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        await seed_rewards(factory, settings)
        count = await reconcile_earnings(factory)
        print(
            f"Sandbox catalogue initialized. Credited {count} genuine lesson completions. "
            "Reruns are safe. No real fulfillment."
        )
    except AppError as exc:
        raise SystemExit(f"{exc.code}: {exc.message}") from None
    except Exception:
        raise SystemExit(
            "rewards_initialization_failed: check migrations and local infrastructure"
        ) from None
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
