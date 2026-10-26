import asyncio
import hashlib
import json
from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investiq.adapters.market import (
    EXCHANGE_TZ,
    FixtureMarketProvider,
    MarketDataProvider,
    PublicContestFixtureProvider,
    fixture_document,
    public_fixture_document,
)
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
from investiq.services.exchange_calendar import calendar_rows, expected_session
from investiq.services.market_sources import YAHOO_DATASET, YAHOO_PROVIDER


def ensure_market_mode(settings: Settings) -> None:
    if settings.environment == "production" or settings.market_data_mode == "disabled":
        raise AppError(503, "market_data_disabled", "Market data is disabled in this environment")


def content_hash(batch: ProviderBatch) -> str:
    payload = batch.model_dump(mode="json")
    payload["observed_at"] = batch.observed_at.astimezone(UTC).isoformat()
    payload["source_published_at"] = batch.source_published_at.astimezone(UTC).isoformat()
    payload["points"] = [
        {
            "instrument_id": str(p.instrument_id),
            "close": format(p.close, ".4f"),
            **({"open": format(p.open, ".4f")} if p.open is not None else {}),
        }
        for p in sorted(batch.points, key=lambda p: p.instrument_id)
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class MarketIngestionService:
    def __init__(self, factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.factory, self.settings = factory, settings

    async def seed_yahoo_catalogue(self) -> None:
        from investiq.adapters.yahoo_market import yahoo_catalogue, yahoo_pricing_instruments

        ensure_market_mode(self.settings)
        document = yahoo_catalogue()
        async with self.factory() as db, db.begin():
            for row in document["sectors"]:
                await db.execute(insert(Sector).values(**row).on_conflict_do_nothing())
            for row in yahoo_pricing_instruments():
                await db.execute(
                    insert(Instrument)
                    .values(**{k: v for k, v in row.items() if k != "ticker"}, data_kind="yahoo")
                    .on_conflict_do_nothing(index_elements=["id"])
                )
            await db.execute(
                insert(ExchangeSession).values(calendar_rows()).on_conflict_do_nothing()
            )

    async def sync_yahoo(
        self, start: date | None = None, end: date | None = None, *, limit: int = 1
    ) -> dict[str, object]:
        """Worker/operator import. Successful daily publications are immutable and skipped."""
        from investiq.adapters.yahoo_market import YahooMarketProvider

        ensure_market_mode(self.settings)
        if self.settings.market_data_mode != "yahoo":
            return {"status": "disabled", "imported": 0}
        await self.seed_yahoo_catalogue()
        # Prevent concurrent workers from downloading the same universe repeatedly.
        async with self.factory() as guard, guard.begin():
            if not await guard.scalar(text("SELECT pg_try_advisory_xact_lock(73194107)")):
                return {"status": "busy", "imported": 0}
            instant = now()
            latest = await expected_session(guard, instant)
            # Include missed days of active Yahoo contests, not just today's close.
            from investiq.models.contest import Contest, ContestRules

            earliest = await guard.scalar(
                select(Contest.starts_at)
                .join(ContestRules, ContestRules.contest_id == Contest.id)
                .join(
                    Instrument,
                    Instrument.id
                    == ContestRules.rules["benchmark_id"].astext.cast(Instrument.id.type),
                )
                .where(
                    Instrument.data_kind == "yahoo",
                    Contest.status.not_in(["draft", "completed", "cancelled"]),
                )
                .order_by(Contest.starts_at)
                .limit(1)
            )
            from datetime import timedelta

            default_start = latest.session_date - timedelta(days=7)
            if earliest:
                default_start = min(default_start, earliest.astimezone(EXCHANGE_TZ).date())
            first, last = start or default_start, end or latest.session_date
            if first > last or (start is not None and (last - first).days > 31):
                raise AppError(
                    422, "invalid_market_range", "Import an ordered range of up to 32 days"
                )
            completed = select(IngestionRun.session_date).where(
                IngestionRun.provider == YAHOO_PROVIDER,
                IngestionRun.dataset_version == YAHOO_DATASET,
                IngestionRun.status == "succeeded",
            )
            days = (
                await guard.scalars(
                    select(ExchangeSession.session_date)
                    .where(
                        ExchangeSession.exchange == "NSE",
                        ExchangeSession.status == "open",
                        ExchangeSession.available_at <= instant,
                        ExchangeSession.session_date.between(first, last),
                        ExchangeSession.session_date.not_in(completed),
                    )
                    .order_by(ExchangeSession.session_date.desc())
                    .limit(limit)
                )
            ).all()
            imported, errors = 0, []
            for day in days:
                try:
                    await self.ingest(YahooMarketProvider(self.settings.yahoo_timeout_seconds), day)
                    imported += 1
                except AppError as exc:
                    errors.append({"session_date": day.isoformat(), "code": exc.code})
            return {
                "status": "blocked" if errors else "ready",
                "imported": imported,
                "errors": errors,
            }

    async def seed_fixtures(self) -> list[UUID]:
        ensure_market_mode(self.settings)
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

    async def seed_public_fixtures(self) -> list[UUID]:
        """Release only already-published entries from the fixed, reviewed scenario."""
        ensure_market_mode(self.settings)
        provider = PublicContestFixtureProvider()
        instant = now()
        due = [
            date.fromisoformat(day)
            for day in sorted(public_fixture_document()["prices"])
            if datetime.combine(date.fromisoformat(day), time(18), EXCHANGE_TZ) <= instant
        ]
        return [await self.ingest(provider, day) for day in due]

    async def _run(
        self, db: AsyncSession, provider: MarketDataProvider, session_date: date, started: datetime
    ) -> tuple[IngestionRun, bool]:
        identifier = await db.scalar(
            insert(IngestionRun)
            .values(
                provider=provider.provider,
                dataset_version=provider.dataset_version,
                session_date=session_date,
                data_kind="yahoo" if provider.provider == YAHOO_PROVIDER else "fixture",
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
        ensure_market_mode(self.settings)
        started = now()
        if provider.provider == YAHOO_PROVIDER:
            async with self.factory() as db:
                existing = await db.scalar(
                    select(IngestionRun).where(
                        IngestionRun.provider == provider.provider,
                        IngestionRun.dataset_version == provider.dataset_version,
                        IngestionRun.session_date == session_date,
                        IngestionRun.status == "succeeded",
                    )
                )
                if existing:
                    return existing.id
        try:
            received = await asyncio.wait_for(
                provider.fetch_eod(session_date),
                timeout=self.settings.yahoo_timeout_seconds + 1
                if provider.provider == YAHOO_PROVIDER
                else 10,
            )
            batch = ProviderBatch.model_validate(received.model_dump())
            if (
                batch.provider != provider.provider
                or batch.dataset_version != provider.dataset_version
                or batch.session_date != session_date
                or batch.data_kind
                != ("yahoo" if provider.provider == YAHOO_PROVIDER else "fixture")
                or (
                    provider.provider == YAHOO_PROVIDER
                    and provider.dataset_version != YAHOO_DATASET
                )
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
                            select(Instrument.id).where(Instrument.data_kind == batch.data_kind)
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
                    if run.content_hash != checksum and batch.data_kind != "yahoo":
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
                            open=point.open,
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
