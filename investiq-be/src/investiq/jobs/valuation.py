import asyncio
from typing import Any
from uuid import UUID

from celery import Celery
from celery.signals import setup_logging

from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.core.logging import configure_logging
from investiq.main import create_app
from investiq.services.market_ingestion import MarketIngestionService
from investiq.services.rewards import reconcile_earnings
from investiq.services.valuation import ValuationService

settings = Settings()
app: Any = Celery("investiq", broker=settings.celery_broker_url.get_secret_value())
app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    task_ignore_result=True,
    task_store_errors_even_if_ignored=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=90,
    task_time_limit=120,
    task_default_queue=settings.valuation_queue,
    broker_transport_options={"visibility_timeout": 180, "global_keyprefix": "investiq:jobs:"},
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "market-news-scan": {
            "task": "investiq.news.scan",
            "schedule": 60,
            "options": {"expires": 60},
        },
        "market-scan": {
            "task": "investiq.market.scan",
            "schedule": settings.market_scan_seconds,
            "options": {"expires": settings.market_scan_seconds},
        },
        "martin-scan": {
            "task": "investiq.martin.scan",
            "schedule": settings.ai_scan_seconds,
            "options": {"expires": settings.ai_scan_seconds},
        },
        "coach-scan": {
            "task": "investiq.coach.scan",
            "schedule": settings.ai_scan_seconds,
            "options": {"expires": settings.ai_scan_seconds},
        },
        "valuation-scan": {
            "task": "investiq.valuation.scan",
            "schedule": settings.valuation_scan_seconds,
            "options": {"expires": settings.valuation_scan_seconds},
        },
    },
)


def safe_logging(*args: Any, **kwargs: Any) -> None:
    configure_logging(settings.log_level)


setup_logging.connect(safe_logging, weak=False)


async def execute(config: Settings | None = None, identifier: UUID | None = None) -> dict[str, Any]:
    # Fresh pools per asyncio.run; no asyncpg connections cross worker event loops/forks.
    application = create_app(config or settings)
    async with application.router.lifespan_context(application):
        await reconcile_earnings(application.state.sessions)
        config = application.state.settings
        if config.public_contest_fixtures_enabled:
            await MarketIngestionService(application.state.sessions, config).seed_public_fixtures()
        service: ValuationService = application.state.valuations
        return await service.evaluate(identifier) if identifier else await service.sweep()


def scan() -> dict[str, Any]:
    try:
        return asyncio.run(execute())
    except AppError as exc:
        # Stable codes only; never log SQL/provider payloads or credential-bearing exceptions.
        return {"status": "blocked", "error_code": exc.code}
    except Exception:
        raise RuntimeError("valuation_scan_failed; retry on the next scheduled scan") from None


# No framework decorator leaks into the typed service layer.
scan_task = app.task(
    name="investiq.valuation.scan",
    acks_late=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)(scan)


async def execute_coach() -> dict[str, int]:
    from investiq.ai.workflow import sweep
    from investiq.services.coach_overview import queue_daily

    application = create_app(settings)
    async with application.router.lifespan_context(application):
        await queue_daily(application.state.coach)
        return await sweep(application.state.coach)


def coach_scan() -> dict[str, int]:
    try:
        return asyncio.run(execute_coach())
    except Exception:
        # No provider messages, prompts or account data in worker exception logs.
        raise RuntimeError("coach_scan_failed; retry on next scheduled scan") from None


coach_scan_task = app.task(name="investiq.coach.scan", acks_late=True)(coach_scan)


async def execute_martin() -> dict[str, int]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        result: dict[str, int] = await application.state.martin.sweep()
        return result


def martin_scan() -> dict[str, int]:
    try:
        return asyncio.run(execute_martin())
    except Exception:
        raise RuntimeError("martin_scan_failed; retry on next scheduled scan") from None


martin_scan_task = app.task(name="investiq.martin.scan", acks_late=True)(martin_scan)


async def execute_market() -> dict[str, object]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from investiq.db.session import make_engine

    if settings.market_data_mode != "yahoo":
        return {"status": "disabled", "imported": 0}
    engine = make_engine(settings)
    try:
        return await MarketIngestionService(
            async_sessionmaker(engine, expire_on_commit=False), settings
        ).sync_yahoo()
    finally:
        await engine.dispose()


def market_scan() -> dict[str, object]:
    try:
        return asyncio.run(execute_market())
    except AppError as exc:
        return {"status": "blocked", "error_code": exc.code}
    except Exception:
        raise RuntimeError("market_scan_failed; retry on the next scheduled scan") from None


market_scan_task = app.task(name="investiq.market.scan", acks_late=True)(market_scan)


async def execute_news() -> dict[str, object]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        result: dict[str, object] = await application.state.market_news.refresh()
        return result


def news_scan() -> dict[str, object]:
    try:
        return asyncio.run(execute_news())
    except Exception:
        raise RuntimeError("news_scan_failed; retry on next scheduled scan") from None


news_scan_task = app.task(name="investiq.news.scan", acks_late=True)(news_scan)
