import asyncio
import base64
import json
import traceback
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.adapters.market import FixtureMarketProvider, fixture_document
from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.db.session import make_engine
from investiq.main import create_app
from investiq.models.market import ExchangeSession, IngestionRun, Instrument, PriceSnapshot
from investiq.schemas.market import PricePoint, ProviderBatch
from investiq.services.exchange_calendar import expected_session
from investiq.services.market import decode_cursor, fingerprint
from investiq.services.market_ingestion import MarketIngestionService, content_hash
from tests.helpers import test_client as api_client

ANCHOR = datetime(2026, 10, 18, 12, tzinfo=UTC)
DAY = date(2026, 10, 16)
DOCUMENT = fixture_document()
IDENTIFIER = DOCUMENT["instruments"][0]["id"]


class BatchProvider:
    provider = "investiq-synthetic"
    dataset_version = "fixture-v1"

    def __init__(self, batch: ProviderBatch) -> None:
        self.batch = batch

    async def fetch_eod(self, session_date: date) -> ProviderBatch:
        return self.batch


@pytest.mark.integration
async def test_catalogue_search_filters_and_stable_pagination(market_settings: Settings) -> None:
    async with api_client(create_app(market_settings, market_clock=lambda: ANCHOR)) as client:
        sectors = (await client.get("/api/v1/sectors")).json()["items"]
        it = next(s["id"] for s in sectors if s["name"] == "IT")
        results, cursor = [], None
        while True:
            params = {"limit": 3, "sort": "symbol"}
            if cursor:
                params["cursor"] = cursor
            response = await client.get("/api/v1/instruments", params=params)
            assert response.status_code == 200
            data = response.json()
            results.extend(data["items"])
            cursor = data["next_cursor"]
            if cursor is None:
                break
        assert len(results) == len({i["id"] for i in results}) == 16
        assert [i["symbol"] for i in results] == sorted(i["symbol"] for i in results)
        matches = (
            await client.get(
                "/api/v1/instruments",
                params={
                    "query": " info ",
                    "sector": it,
                    "market_cap": "large",
                },
            )
        ).json()["items"]
        assert [m["symbol"] for m in matches] == ["INFY"]
        reverse = (await client.get("/api/v1/instruments", params={"sort": "-name"})).json()[
            "items"
        ]
        assert [m["name"] for m in reverse] == sorted((m["name"] for m in reverse), reverse=True)
        assert (await client.get("/api/v1/instruments", params={"query": "%"})).json()[
            "items"
        ] == []
        benchmarks = (await client.get("/api/v1/instruments", params={"kind": "benchmark"})).json()[
            "items"
        ]
        assert len(benchmarks) == 1 and benchmarks[0]["currency"] == "POINTS"
        first = (await client.get("/api/v1/instruments", params={"limit": 1})).json()
        invalid = await client.get(
            "/api/v1/instruments",
            params={
                "cursor": first["next_cursor"],
                "sort": "-name",
            },
        )
        assert invalid.status_code == 422
        for params in (
            {"cursor": "not-valid"},
            {"limit": 101},
            {"market_cap": "mega"},
            {"sort": "DROP TABLE users"},
        ):
            assert (await client.get("/api/v1/instruments", params=params)).status_code == 422


@pytest.mark.integration
async def test_eod_quotes_decimal_provenance_and_publication_cutoff(
    market_settings: Settings,
) -> None:
    async with api_client(create_app(market_settings, market_clock=lambda: ANCHOR)) as client:
        response = await client.get(
            "/api/v1/quotes",
            params={
                "instrument_ids": IDENTIFIER,
                "require_complete": True,
            },
        )
        assert response.status_code == 200, response.text
        body, quote = response.json(), response.json()["items"][0]
        assert body["expected_session_date"] == "2026-10-16"  # Sunday reuses reviewed Friday.
        assert quote["close"] == "2947.4000"
        assert quote["observed_at"].startswith("2026-10-16T10:00:00")
        assert quote["source_published_at"].startswith("2026-10-16T12:30:00")
        assert quote["ingested_at"] is not None and quote["source"] == "investiq-synthetic"
        assert quote["data_kind"] == "fixture" and quote["eligible_for_live_use"] is False
        before = await client.get(
            "/api/v1/quotes",
            params={
                "instrument_ids": IDENTIFIER,
                "as_of": "2026-10-16T12:29:59Z",
            },
        )
        assert before.json()["expected_session_date"] == "2026-10-15"
        assert before.json()["items"][0]["close"] == "2917.9260"
        at_close = await client.get(
            "/api/v1/quotes",
            params={
                "instrument_ids": IDENTIFIER,
                "as_of": "2026-10-16T12:30:00Z",
            },
        )
        assert at_close.json()["items"][0]["session_date"] == "2026-10-16"
        benchmark_id = DOCUMENT["instruments"][16]["id"]
        benchmark = (
            await client.get("/api/v1/quotes", params={"instrument_ids": benchmark_id})
        ).json()["items"][0]
        assert benchmark["currency"] == "POINTS" and benchmark["close"] == "25000.0000"


@pytest.mark.integration
async def test_missing_stale_unknown_and_invalid_quote_requests(market_settings: Settings) -> None:
    engine = make_engine(market_settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db, db.begin():
            # Remove only this disposable test database's Friday point.
            row = await db.scalar(
                select(PriceSnapshot).where(
                    PriceSnapshot.instrument_id == UUID(IDENTIFIER),
                    PriceSnapshot.session_date == DAY,
                )
            )
            await db.delete(row)
        async with api_client(create_app(market_settings, market_clock=lambda: ANCHOR)) as client:
            data = (
                await client.get("/api/v1/quotes", params={"instrument_ids": IDENTIFIER})
            ).json()
            assert data["items"][0]["freshness"] == "stale"
            assert data["items"][0]["eligible_for_simulation"] is False
            strict = await client.get(
                "/api/v1/quotes", params={"instrument_ids": IDENTIFIER, "require_complete": True}
            )
            assert strict.status_code == 409
            past = await client.get(
                "/api/v1/quotes",
                params={
                    "instrument_ids": IDENTIFIER,
                    "as_of": "2026-10-02T13:00:00Z",
                },
            )
            assert past.json()["expected_session_date"] == "2026-10-01"
            assert past.json()["items"][0]["freshness"] == "missing"
            assert past.json()["items"][0]["close"] is None
            for params, status in [
                ({"instrument_ids": str(uuid4())}, 404),
                ({"instrument_ids": "INFY"}, 422),
                ({"instrument_ids": IDENTIFIER + "," + IDENTIFIER}, 422),
                ({"instrument_ids": IDENTIFIER, "as_of": "2026-10-16T12:30:00"}, 422),
                (
                    {
                        "instrument_ids": IDENTIFIER,
                        "as_of": (ANCHOR + timedelta(days=1)).isoformat(),
                    },
                    422,
                ),
            ]:
                assert (await client.get("/api/v1/quotes", params=params)).status_code == status
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_corporate_action_exclusion_and_inactive_instrument(
    market_settings: Settings,
) -> None:
    async with api_client(create_app(market_settings, market_clock=lambda: ANCHOR)) as client:
        excluded = (
            await client.get(
                "/api/v1/instruments",
                params={
                    "query": "FIXSPLIT",
                    "eligible_only": False,
                },
            )
        ).json()["items"][0]
        assert excluded["excluded"] is True
        assert (await client.get("/api/v1/instruments", params={"query": "FIXSPLIT"})).json()[
            "items"
        ] == []
        quote = (
            await client.get("/api/v1/quotes", params={"instrument_ids": excluded["id"]})
        ).json()["items"][0]
        assert quote["blocked_reason"].startswith("Synthetic split")
        assert quote["eligible_for_simulation"] is False
    engine = make_engine(market_settings)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                update(Instrument).where(Instrument.id == UUID(IDENTIFIER)).values(active=False)
            )
        async with api_client(create_app(market_settings, market_clock=lambda: ANCHOR)) as client:
            quote = (
                await client.get("/api/v1/quotes", params={"instrument_ids": IDENTIFIER})
            ).json()["items"][0]
            assert quote["blocked_reason"] == "Instrument is inactive"
            assert quote["eligible_for_simulation"] is False
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_calendar_holidays_special_sessions_and_coverage(market_settings: Settings) -> None:
    async with api_client(create_app(market_settings, market_clock=lambda: ANCHOR)) as client:
        october = (
            await client.get(
                "/api/v1/market/sessions",
                params={
                    "start_date": "2026-10-16",
                    "end_date": "2026-10-20",
                },
            )
        ).json()["items"]
        assert [r["status"] for r in october] == ["open", "closed", "closed", "open", "closed"]
        assert october[0]["opens_at"].startswith("2026-10-16T03:45:00")
        assert october[-1]["reason"] == "Dussehra"
        assert (
            await client.get(
                "/api/v1/market/sessions",
                params={
                    "start_date": "2026-12-31",
                    "end_date": "2027-01-01",
                },
            )
        ).status_code == 503
        assert (
            await client.get(
                "/api/v1/market/sessions",
                params={
                    "start_date": "2026-10-20",
                    "end_date": "2026-10-16",
                },
            )
        ).status_code == 422
    engine = make_engine(market_settings)
    try:
        async with async_sessionmaker(engine)() as db:
            holiday = await expected_session(db, datetime(2026, 10, 20, 12, tzinfo=UTC))
            assert holiday.session_date == date(2026, 10, 19)
            with pytest.raises(AppError, match="special exchange session"):
                await expected_session(db, datetime(2026, 11, 8, 12, tzinfo=UTC))
            with pytest.raises(AppError, match="No reviewed exchange calendar"):
                await expected_session(db, datetime(2027, 1, 1, 12, tzinfo=UTC))
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_idempotent_concurrent_ingestion_and_immutable_prices(
    market_settings: Settings,
) -> None:
    engine = make_engine(market_settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = MarketIngestionService(factory, market_settings)
    try:
        identifiers = await asyncio.gather(
            *[service.ingest(FixtureMarketProvider(), DAY) for _ in range(8)]
        )
        assert len(set(identifiers)) == 1
        batch = await FixtureMarketProvider().fetch_eod(DAY)
        equivalent = batch.model_copy(update={"points": tuple(reversed(batch.points))})
        assert content_hash(equivalent) == content_hash(batch)
        assert await service.ingest(BatchProvider(equivalent), DAY) == identifiers[0]
        changed = batch.model_copy(
            update={
                "points": (
                    PricePoint(
                        instrument_id=batch.points[0].instrument_id, close=Decimal("1.0000")
                    ),
                    *batch.points[1:],
                )
            }
        )
        with pytest.raises(AppError) as conflict:
            await service.ingest(BatchProvider(changed), DAY)
        assert conflict.value.code == "immutable_price_conflict"
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(IngestionRun)) == 3
            assert await db.scalar(select(func.count()).select_from(PriceSnapshot)) == 54
            run = await db.get(IngestionRun, identifiers[0])
            assert run.status == "succeeded" and run.attempts == 1
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_failed_incomplete_import_is_atomic_and_can_retry(market_settings: Settings) -> None:
    engine = make_engine(market_settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = MarketIngestionService(factory, market_settings)
    day = date(2026, 10, 13)
    original = await FixtureMarketProvider().fetch_eod(DAY)
    batch = original.model_copy(
        update={
            "session_date": day,
            "observed_at": datetime(2026, 10, 13, 10, tzinfo=UTC),
            "source_published_at": datetime(2026, 10, 13, 12, 30, tzinfo=UTC),
        }
    )
    try:
        incomplete = batch.model_copy(update={"points": batch.points[:-1]})
        with pytest.raises(AppError) as error:
            await service.ingest(BatchProvider(incomplete), day)
        assert error.value.code == "incomplete_provider_batch"
        async with factory() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(PriceSnapshot)
                    .where(PriceSnapshot.session_date == day)
                )
                == 0
            )
            run = await db.scalar(select(IngestionRun).where(IngestionRun.session_date == day))
            assert run.status == "failed" and run.point_count == 0
        identifier = await service.ingest(BatchProvider(batch), day)
        async with factory() as db:
            run = await db.get(IngestionRun, identifier)
            assert run.status == "succeeded" and run.attempts == 2
            assert run.point_count == 18
        duplicate = batch.model_copy(update={"points": (*batch.points[:-1], batch.points[0])})
        with pytest.raises(AppError) as error:
            await service.ingest(BatchProvider(duplicate), day)
        assert error.value.code == "incomplete_provider_batch"
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_database_constraints_reject_nan_and_incomplete_open_session(
    market_settings: Settings,
) -> None:
    engine = make_engine(market_settings)
    try:
        with pytest.raises(IntegrityError) as invalid:
            async with engine.begin() as conn:
                await conn.execute(
                    update(PriceSnapshot)
                    .where(PriceSnapshot.instrument_id == UUID(IDENTIFIER))
                    .values(close=Decimal("NaN"))
                )
        assert invalid.value.orig.sqlstate == "23514"
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    update(ExchangeSession)
                    .where(ExchangeSession.session_date == DAY)
                    .values(closes_at=None, available_at=None)
                )
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_fixture_market_is_disabled_in_production(market_settings: Settings) -> None:
    production = market_settings.model_copy(update={"environment": "production"})
    async with api_client(create_app(production)) as client:
        for path in (
            "/api/v1/instruments",
            "/api/v1/sectors",
            f"/api/v1/quotes?instrument_ids={IDENTIFIER}",
        ):
            assert (await client.get(path)).status_code == 503
    engine = make_engine(production)
    try:
        with pytest.raises(AppError) as error:
            await MarketIngestionService(async_sessionmaker(engine), production).seed_fixtures()
        assert error.value.code == "market_data_disabled"
    finally:
        await engine.dispose()


@pytest.mark.parametrize("price", [1.1, "NaN", "Infinity", "-1", "0", "1.12345"])
def test_provider_rejects_float_nonfinite_nonpositive_and_overprecision(price: object) -> None:
    with pytest.raises(ValidationError):
        PricePoint(instrument_id=uuid4(), close=price)


@pytest.mark.parametrize("identifier", [None, 123, [], "bad-uuid"])
def test_malformed_cursors_are_validation_errors(identifier: object) -> None:
    context = fingerprint({})
    cursor = base64.urlsafe_b64encode(json.dumps(["symbol", identifier, context]).encode()).decode()
    with pytest.raises(AppError) as error:
        decode_cursor(cursor, context)
    assert error.value.status == 422


@pytest.mark.integration
async def test_provider_failures_are_sanitized_and_bad_timestamps_never_publish(
    market_settings: Settings,
) -> None:
    class FailingProvider:
        provider = "investiq-synthetic"
        dataset_version = "fixture-v1"

        async def fetch_eod(self, session_date: date) -> ProviderBatch:
            raise RuntimeError("private provider credentials must never be recorded")

    engine = make_engine(market_settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = MarketIngestionService(factory, market_settings)
    day = date(2026, 10, 13)
    try:
        with pytest.raises(AppError) as failed:
            await service.ingest(FailingProvider(), day)
        assert failed.value.status == 503
        assert "credentials" not in failed.value.message
        assert "private provider credentials" not in "".join(
            traceback.format_exception(failed.value)
        )
        batch = (await FixtureMarketProvider().fetch_eod(DAY)).model_copy(
            update={"session_date": day}
        )
        with pytest.raises(AppError) as invalid:
            await service.ingest(BatchProvider(batch), day)
        assert invalid.value.code == "invalid_price_timestamp"
        async with factory() as db:
            run = await db.scalar(select(IngestionRun).where(IngestionRun.session_date == day))
            assert run.status == "failed" and run.attempts == 2
            assert run.error_code == "invalid_price_timestamp"
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(PriceSnapshot)
                    .where(PriceSnapshot.session_date == day)
                )
                == 0
            )
    finally:
        await engine.dispose()
