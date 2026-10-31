"""Bounded daily processing on a standard GitHub runner; no broker or daemon."""

import asyncio
import json
from typing import Any

from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import text

from investiq.ai.workflow import sweep as coach_sweep
from investiq.core.config import Settings
from investiq.deploy_cli import validate_deployment
from investiq.main import create_app
from investiq.services.coach_overview import queue_daily
from investiq.services.market_ingestion import MarketIngestionService
from investiq.services.rewards import reconcile_earnings


async def process(application: FastAPI) -> dict[str, Any]:
    state = application.state
    async with state.engine.connect() as guard, guard.begin():
        if not await guard.scalar(text("SELECT pg_try_advisory_xact_lock(742021)")):
            return {"status": "busy"}
        market = await MarketIngestionService(state.sessions, state.settings).sync_yahoo(limit=5)
        valuations = []
        # Catch up several missed closes without unbounded database work.
        for _ in range(5):
            result = await state.valuations.sweep(limit=100)
            valuations.append(result)
            if not result["more_due"]:
                break
        await reconcile_earnings(state.sessions)
        news = await state.market_news.refresh()
        queued = await queue_daily(state.coach, limit=20)
        processed = 0
        for _ in range(20):
            result = await coach_sweep(state.coach)
            processed += result["processed"]
            if not result["processed"]:
                break
        # Recover a small number of questions interrupted during a web request.
        for _ in range(5):
            if not (await state.martin.sweep())["processed"]:
                break
        return {
            "status": "blocked" if market.get("status") == "blocked" else "ok",
            "market": market,
            "valuations": valuations,
            "news": news,
            "reports_queued": queued,
            "reports_processed": processed,
        }


async def execute(settings: Settings) -> dict[str, Any]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        async with asyncio.timeout(900):
            return await process(application)


def main() -> None:
    try:
        settings = Settings()
        validate_deployment(settings)
        if settings.deployment_mode != "free_demo":
            raise ValueError("Daily processing requires INVESTIQ_DEPLOYMENT_MODE=free_demo")
        result = asyncio.run(execute(settings))
        print(json.dumps(result))
        if result["status"] == "blocked":
            raise SystemExit("daily_market_import_blocked: inspect the error codes above")
    except ValidationError:
        raise SystemExit("daily_configuration_invalid: check production settings") from None
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    except Exception:
        raise SystemExit(
            "daily_processing_failed: check infrastructure and rerun the job"
        ) from None


if __name__ == "__main__":
    main()
