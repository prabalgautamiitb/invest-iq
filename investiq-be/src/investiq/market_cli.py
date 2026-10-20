"""Development-only, deterministic market fixture initialization."""

import argparse
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.db.session import make_engine
from investiq.services.market_ingestion import MarketIngestionService


async def seed(public_contests: bool = False) -> None:
    settings = Settings()
    engine = make_engine(settings)
    try:
        service = MarketIngestionService(
            async_sessionmaker(engine, expire_on_commit=False), settings
        )
        runs = await service.seed_fixtures()
        if public_contests:
            runs += await MarketIngestionService(
                async_sessionmaker(engine, expire_on_commit=False), settings
            ).seed_public_fixtures()
        print(
            f"Synthetic market fixture initialized: {len(runs)} EOD batches. Not real market data."
        )
    except AppError as exc:
        raise SystemExit(f"{exc.code}: {exc.message}") from None
    except Exception:
        raise SystemExit(
            "market_initialization_failed: check the configured infrastructure"
        ) from None
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public-contests",
        action="store_true",
        help="Also release due fixed public-contest scenario prices",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.public_contests))
