"""Development-only, deterministic market fixture initialization."""

import argparse
import asyncio
from datetime import date

from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.db.session import make_engine
from investiq.services.market_ingestion import MarketIngestionService


async def seed(
    public_contests: bool = False,
    *,
    yahoo: bool = False,
    start: date | None = None,
    end: date | None = None,
) -> None:
    settings = Settings()
    engine = make_engine(settings)
    try:
        service = MarketIngestionService(
            async_sessionmaker(engine, expire_on_commit=False), settings
        )
        if yahoo:
            if settings.market_data_mode != "yahoo":
                raise AppError(422, "yahoo_disabled", "Set INVESTIQ_MARKET_DATA_MODE=yahoo first")
            import json

            result = await service.sync_yahoo(start, end, limit=32)
            print(json.dumps(result))
            if result["status"] == "blocked":
                raise SystemExit(1)
            return
        runs = await service.seed_fixtures()
        # Initializing the catalogue does not contact Yahoo or alter synthetic history.
        await service.seed_yahoo_catalogue()
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
        "--yahoo", action="store_true", help="Import dated Yahoo EOD prices for the active universe"
    )
    parser.add_argument("--start", type=date.fromisoformat, help="First date, YYYY-MM-DD")
    parser.add_argument("--end", type=date.fromisoformat, help="Last date, YYYY-MM-DD")
    parser.add_argument(
        "--public-contests",
        action="store_true",
        help="Also release due fixed public-contest scenario prices",
    )
    args = parser.parse_args()
    if (args.start or args.end) and not args.yahoo:
        parser.error("--start and --end require --yahoo")
    asyncio.run(seed(args.public_contests, yahoo=args.yahoo, start=args.start, end=args.end))
