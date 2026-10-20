import asyncio
import hashlib
import json
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investiq.adapters.market import FixtureMarketProvider, MarketDataProvider, fixture_document
from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.core.security import now
from investiq.models.market import (
    ExchangeSession,
    IngestionRun,
    Instrument,
    MarketExclusion,
    PriceSnapshot,
    Sector,
)
from investiq.schemas.market import ProviderBatch
from investiq.services.exchange_calendar import calendar_rows


def ensure_fixture_mode(settings: Settings) -> None:
    if settings.environment == "production" or settings.market_data_mode != "fixture":
        raise AppError(
            503, "market_data_disabled", "No approved production market-data feed is configured"
        )


def content_hash(batch: ProviderBatch) -> str:
    payload = batch.model_dump(mode="json")
    payload["observed_at"] = batch.observed_at.astimezone(UTC).isoformat()
    payload["source_published_at"] = batch.source_published_at.astimezone(UTC).isoformat()
    payload["points"] = [
        {"instrument_id": str(p.instrument_id), "close": format(p.close, ".4f")}
        for p in sorted(batch.points, key=lambda p: p.instrument_id)
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class MarketIngestionService:
    def __init__(self, factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.factory, self.settings = factory, settings

    async def seed_fixtures(self) -> list[UUID]:
        ensure_fixture_mode(self.settings)
        document = fixture_document()
        async with self.factory() as db, db.begin():
            # Seed missing definitions only. Never overwrite operator corrections or price history.
            for row in document["sectors"]:
                await db.execute(
                    insert(Sector).values(**row).on_conflict_do_nothing(index_elements=["id"])
                )
            for row in document["instruments"]:
                values = {k: v for k, v in row.items() if k != "key"}
                await db.execute(
                    insert(Instrument)
                    .values(**values, data_kind="fixture")
                    .on_conflict_do_nothing(index_elements=["id"])
                )
            await db.execute(
                insert(ExchangeSession)
                .values(calendar_rows())
                .on_conflict_do_nothing(index_elements=["id"])
            )
            excluded_id = UUID("9a0d8e44-435e-4bca-a98e-32e5c38b52ce")
            await db.execute(
                insert(MarketExclusion)
                .values(
                    id=excluded_id,
                    instrument_id=UUID(document["instruments"][-1]["id"]),
                    starts_on=date(2026, 10, 15),
                    ends_on=None,
                    reason="Synthetic split: adjusted-price handling is not implemented",
                    source="fixture-v1 exclusion example",
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
        provider = FixtureMarketProvider()
        return [
            await self.ingest(provider, date.fromisoformat(day))
            for day in sorted(document["prices"])
        ]

    async def _run(
        self, db: AsyncSession, provider: MarketDataProvider, session_date: date, started: datetime
    ) -> tuple[IngestionRun, bool]:
        identifier = await db.scalar(
            insert(IngestionRun)
            .values(
                provider=provider.provider,
                dataset_version=provider.dataset_version,
                session_date=session_date,
                data_kind="fixture",
                status="failed",
                attempts=1,
                point_count=0,
                error_code="provider_failed",
                started_at=started,
                completed_at=now(),
            )
            .on_conflict_do_nothing(index_elements=["provider", "dataset_version", "session_date"])
            .returning(IngestionRun.id)
        )
        row = await db.scalar(
            select(IngestionRun)
            .where(
                IngestionRun.provider == provider.provider,
                IngestionRun.dataset_version == provider.dataset_version,
                IngestionRun.session_date == session_date,
            )
            .with_for_update()
        )
        assert row is not None
        return row, identifier is not None

    async def _failure(
        self, provider: MarketDataProvider, session_date: date, started: datetime, code: str
    ) -> None:
        async with self.factory() as db, db.begin():
            run, created = await self._run(db, provider, session_date, started)
            if run.status == "succeeded":
                return
            if not created:
                run.attempts += 1
            run.error_code, run.started_at, run.completed_at = code, started, now()

    async def ingest(self, provider: MarketDataProvider, session_date: date) -> UUID:
        ensure_fixture_mode(self.settings)
        started = now()
        try:
            received = await asyncio.wait_for(provider.fetch_eod(session_date), timeout=10)
            batch = ProviderBatch.model_validate(received.model_dump())
            if (
                batch.provider != provider.provider
                or batch.dataset_version != provider.dataset_version
                or batch.session_date != session_date
            ):
                raise AppError(
                    422,
                    "invalid_provider_batch",
                    "Provider batch identity does not match the request",
                )
            async with self.factory() as db, db.begin():
                session = await db.scalar(
                    select(ExchangeSession).where(
                        ExchangeSession.exchange == "NSE",
                        ExchangeSession.session_date == session_date,
                    )
                )
                if not session or session.status != "open":
                    raise AppError(
                        422,
                        "invalid_market_session",
                        "Prices require a supported open exchange session",
                    )
                expected = set(
                    (
                        await db.scalars(
                            select(Instrument.id).where(Instrument.data_kind == "fixture")
                        )
                    ).all()
                )
                actual = [point.instrument_id for point in batch.points]
                if len(actual) != len(set(actual)) or set(actual) != expected:
                    raise AppError(
                        422,
                        "incomplete_provider_batch",
                        "Prices must cover the exact instrument universe once",
                    )
                if (
                    batch.observed_at != session.closes_at
                    or session.available_at is None
                    or batch.source_published_at < session.available_at
                    or batch.source_published_at > now()
                ):
                    raise AppError(
                        422,
                        "invalid_price_timestamp",
                        "Observation/publication times violate the session policy",
                    )
                checksum = content_hash(batch)
                run, created = await self._run(db, provider, session_date, started)
                if run.status == "succeeded":
                    if run.content_hash != checksum:
                        raise AppError(
                            409,
                            "immutable_price_conflict",
                            "Published prices cannot be silently replaced",
                        )
                    return run.id
                if not created:
                    run.attempts += 1
                run.status, run.point_count, run.content_hash = "succeeded", len(actual), checksum
                run.error_code, run.started_at, run.completed_at = None, started, now()
                db.add_all(
                    [
                        PriceSnapshot(
                            run_id=run.id,
                            instrument_id=point.instrument_id,
                            session_date=session_date,
                            close=point.close,
                            observed_at=batch.observed_at,
                            source_published_at=batch.source_published_at,
                        )
                        for point in batch.points
                    ]
                )
                await db.flush()
                return run.id
        except AppError as exc:
            await self._failure(provider, session_date, started, exc.code)
            raise
        except Exception:
            await self._failure(provider, session_date, started, "provider_failed")
            raise AppError(
                503, "provider_failed", "Market-data ingestion failed; no prices were published"
            ) from None
