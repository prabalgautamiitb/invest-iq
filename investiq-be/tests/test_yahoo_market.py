from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select

from investiq.adapters.yahoo_market import (
    YahooMarketProvider,
    yahoo_catalogue,
    yahoo_pricing_instruments,
)
from investiq.core.errors import AppError
from investiq.main import create_app
from investiq.models.market import IngestionRun, PriceSnapshot
from investiq.services.market_ingestion import MarketIngestionService
from tests.conftest import CapturedMailer
from tests.helpers import test_client as api_client
from tests.test_contest import verified
from tests.test_identity import csrf
from tests.test_platform_contests import config, create, role
from tests.test_portfolio import preview, save, submit, weights

DAY = date(2026, 10, 14)
INSTANT = datetime(2026, 10, 14, 13, tzinfo=UTC)


def bars(day=DAY, multiplier=Decimal(1)):
    return {
        i["ticker"]: [
            {
                "session_date": day.isoformat(),
                "open": "25000" if i["kind"] == "benchmark" else "100",
                "close": str(
                    (Decimal(25000) if i["kind"] == "benchmark" else Decimal(100)) * multiplier
                ),
                "split": "0",
            }
        ]
        for i in yahoo_pricing_instruments()
    }


@pytest.mark.parametrize("fault", ["missing", "wrong_day", "nan", "negative", "split", "duplicate"])
async def test_yahoo_provider_rejects_unusable_or_wrong_session_data(fault):
    values = deepcopy(bars())
    ticker = next(iter(values))
    row = values[ticker][0]
    if fault == "missing":
        del values[ticker]
    elif fault == "wrong_day":
        row["session_date"] = "2026-10-13"
    elif fault == "nan":
        row["close"] = "NaN"
    elif fault == "negative":
        row["open"] = "-1"
    elif fault == "split":
        row["split"] = "2"
    else:
        values[ticker].append(row)
    provider = YahooMarketProvider(loader=lambda tickers, day: values, clock=lambda: INSTANT)
    with pytest.raises(AppError) as failure:
        await provider.fetch_eod(DAY)
    assert failure.value.code in {"market_data_incomplete", "unsupported_corporate_action"}


async def test_yahoo_provider_keeps_index_ticker_and_does_not_fetch_before_publication():
    calls = []

    def load(tickers, day):
        calls.append(tickers)
        assert "^NSEI" in tickers and "^NSEI.NS" not in tickers
        return bars(day)

    provider = YahooMarketProvider(loader=load, clock=lambda: INSTANT)
    batch = await provider.fetch_eod(DAY)
    assert batch.data_kind == "yahoo" and len(batch.points) == 52
    assert all(p.open is not None for p in batch.points)
    assert batch.source_published_at == INSTANT
    assert batch.observed_at == datetime(2026, 10, 14, 10, tzinfo=UTC)
    early = YahooMarketProvider(loader=load, clock=lambda: datetime(2026, 10, 14, 11, tzinfo=UTC))
    with pytest.raises(AppError) as failure:
        await early.fetch_eod(DAY)
    assert failure.value.code == "session_not_published" and len(calls) == 1


async def test_yahoo_prices_flow_from_import_to_submission_valuation_and_final_standings(
    market_settings,
):
    settings = config(market_settings).model_copy(update={"market_data_mode": "yahoo"})
    clock = [INSTANT]
    app = create_app(
        settings, CapturedMailer(), market_clock=lambda: clock[0], contest_clock=lambda: clock[0]
    )
    async with api_client(app) as client:
        service = MarketIngestionService(app.state.sessions, settings)
        await service.seed_yahoo_catalogue()
        provider = YahooMarketProvider(
            loader=lambda tickers, day: bars(day), clock=lambda: clock[0]
        )
        first = await service.ingest(provider, DAY)
        # A retry must retain the original publication, even if the upstream data changes.
        retry = YahooMarketProvider(
            loader=lambda tickers, day: bars(day, Decimal(9)), clock=lambda: clock[0]
        )
        assert await service.ingest(retry, DAY) == first
        user = await verified(client, app.state.identity.mailer)
        await role(app, user, "admin")
        catalogue = (await client.get("/api/v1/instruments", params={"limit": 100})).json()["items"]
        assert len(catalogue) == 50 and all(i["data_kind"] == "yahoo" for i in catalogue)
        fixture = (await client.get("/api/v1/instruments", params={"data_kind": "fixture"})).json()[
            "items"
        ]
        assert set(i["id"] for i in fixture).isdisjoint(i["id"] for i in catalogue)
        mixed = await client.get(
            "/api/v1/quotes", params={"instrument_ids": catalogue[0]["id"] + "," + fixture[0]["id"]}
        )
        assert mixed.status_code == 422 and mixed.json()["error"]["code"] == "mixed_market_sources"
        status = (await client.get("/api/v1/market/status")).json()
        assert status["mode"] == "yahoo" and status["latest_session_date"] == DAY.isoformat()
        quotes = (
            await client.get("/api/v1/quotes", params={"instrument_ids": catalogue[0]["id"]})
        ).json()
        assert quotes["data_kind"] == "yahoo" and quotes["all_current"]
        assert Decimal(quotes["items"][0]["close"]) == 100
        assert Decimal(quotes["items"][0]["open"]) == 100
        assert Decimal(quotes["items"][0]["day_change_pct"]) == 0
        assert (await client.get("/api/v1/contest-simulation-sessions")).json() == []
        data = (await client.get("/api/v1/contest-template")).json()
        data.update(visibility="public", ends_at="2026-10-16T10:00:00Z")
        response = await create(client, data)
        assert response.status_code == 201, response.text
        c = response.json()
        assert c["market_data_kind"] == "yahoo"
        path = "/api/v1/contests/" + c["id"]
        assert (
            await client.post(
                path + "/transitions", json={"action": "publish"}, headers=await csrf(client)
            )
        ).status_code == 200
        assert (await client.post(path + "/entries", headers=await csrf(client))).status_code == 200
        await save(client, path, weights(data))
        reviewed = await preview(client, path, 1)
        assert (
            reviewed["data_kind"] == "yahoo" and reviewed["benchmark"]["source"] == "yahoo-finance"
        )
        assert (await submit(client, path, reviewed)).status_code == 201
        clock[0] = datetime(2026, 10, 15, 13, tzinfo=UTC)
        blocked = await app.state.valuations.evaluate(UUID(c["id"]))
        assert blocked["status"] == "blocked"
        day = date(2026, 10, 15)
        await service.ingest(
            YahooMarketProvider(
                loader=lambda tickers, day: bars(day, Decimal("1.05")), clock=lambda: clock[0]
            ),
            day,
        )
        assert (await app.state.valuations.evaluate(UUID(c["id"])))["processed"] == 1
        board = (await client.get(path + "/leaderboard")).json()
        assert board["data_kind"] == "yahoo" and len(board["items"]) == 1
        assert Decimal(board["items"][0]["return_pct"]) > 4
        performance = (await client.get(path + "/performance")).json()
        assert performance["market_data_kind"] == "yahoo"
        assert performance["metrics"]["rank"] == 1
        clock[0] = datetime(2026, 10, 16, 13, tzinfo=UTC)
        await service.ingest(
            YahooMarketProvider(
                loader=lambda tickers, day: bars(day, Decimal("1.10")), clock=lambda: clock[0]
            ),
            date(2026, 10, 16),
        )
        assert (await app.state.valuations.evaluate(UUID(c["id"])))["status"] == "completed"
        assert (await client.get(path + "/leaderboard")).json()["is_final"]
        async with app.state.sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(IngestionRun)
                    .where(IngestionRun.provider == "yahoo-finance")
                )
                == 3
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(PriceSnapshot)
                    .where(PriceSnapshot.run_id == first)
                )
                == 52
            )


async def test_yahoo_scheduler_imports_only_missing_completed_sessions(
    market_settings, monkeypatch
):
    import investiq.adapters.yahoo_market as adapter
    import investiq.services.market_ingestion as ingestion

    settings = config(market_settings).model_copy(update={"market_data_mode": "yahoo"})
    instant = datetime(2026, 10, 16, 11, tzinfo=UTC)  # Before our 18:00 policy.
    monkeypatch.setattr(ingestion, "now", lambda: instant)

    def factory(timeout):
        return YahooMarketProvider(
            timeout, loader=lambda tickers, day: bars(day), clock=lambda: instant
        )

    monkeypatch.setattr(adapter, "YahooMarketProvider", factory)
    app = create_app(settings)
    async with api_client(app):
        service = MarketIngestionService(app.state.sessions, settings)
        first = await service.sync_yahoo(date(2026, 10, 14), date(2026, 10, 16), limit=3)
        assert first == {"status": "ready", "imported": 2, "errors": []}
        assert (await service.sync_yahoo(date(2026, 10, 14), date(2026, 10, 16), limit=3))[
            "imported"
        ] == 0


async def test_yahoo_publish_uses_calendar_not_fixed_fixture_dates_and_freezes_source(
    market_settings,
):
    settings = config(market_settings).model_copy(update={"market_data_mode": "yahoo"})
    instant = datetime(2026, 10, 23, 13, tzinfo=UTC)
    app = create_app(
        settings, CapturedMailer(), market_clock=lambda: instant, contest_clock=lambda: instant
    )
    async with api_client(app) as client:
        service = MarketIngestionService(app.state.sessions, settings)
        await service.seed_yahoo_catalogue()
        await service.ingest(
            YahooMarketProvider(loader=lambda tickers, day: bars(day), clock=lambda: instant),
            date(2026, 10, 23),
        )
        user = await verified(client, app.state.identity.mailer)
        await role(app, user, "admin")
        data = (await client.get("/api/v1/contest-template")).json()
        data.update(
            visibility="public",
            entry_closes_at="2026-10-27T03:40:00Z",
            starts_at="2026-10-27T03:45:00Z",
            ends_at="2026-10-30T10:00:00Z",
        )
        created = await create(client, data)
        assert created.status_code == 201, created.text
        path = "/api/v1/contests/" + created.json()["id"]
        # Cross-source edits are rejected even while the contest is still a draft.
        fixture = (
            await client.get("/api/v1/instruments", params={"data_kind": "fixture", "limit": 100})
        ).json()["items"]
        benchmark = (
            await client.get(
                "/api/v1/instruments", params={"data_kind": "fixture", "kind": "benchmark"}
            )
        ).json()["items"][0]
        changed = deepcopy(data)
        changed["rules"]["benchmark_id"] = benchmark["id"]
        changed["rules"]["eligible_instrument_ids"] = [i["id"] for i in fixture]
        response = await client.put(path, json=changed, headers=await csrf(client))
        assert (
            response.status_code == 409
            and response.json()["error"]["code"] == "price_source_frozen"
        )
        response = await client.post(
            path + "/transitions", json={"action": "publish"}, headers=await csrf(client)
        )
        assert response.status_code == 200, response.text
        assert response.json()["market_data_kind"] == "yahoo"


async def test_existing_fixture_portfolio_survives_switch_to_yahoo(market_settings):
    from tests.test_contest import create as community_create
    from tests.test_contest import publish

    settings = config(market_settings)
    clock = [INSTANT]
    app = create_app(
        settings, CapturedMailer(), market_clock=lambda: clock[0], contest_clock=lambda: clock[0]
    )
    async with api_client(app) as client:
        await verified(client, app.state.identity.mailer)
        data = (await client.get("/api/v1/contest-template")).json()
        contest = await community_create(client, data)
        await publish(client, contest["id"])
        assert (
            await client.post(
                "/api/v1/contests/" + contest["id"] + "/entries", headers=await csrf(client)
            )
        ).status_code == 200
        path = "/api/v1/contests/" + contest["id"]
        await save(client, path, weights(data))
        before = await preview(client, path, 1)
        settings.market_data_mode = "yahoo"
        service = MarketIngestionService(app.state.sessions, settings)
        await service.seed_yahoo_catalogue()
        await service.ingest(
            YahooMarketProvider(loader=lambda tickers, day: bars(day), clock=lambda: clock[0]), DAY
        )
        after = await preview(client, path, 1)
        assert before["preview_hash"] == after["preview_hash"]
        assert after["data_kind"] == "fixture"
        assert all(h["source"] == "investiq-synthetic" for h in after["holdings"])
        assert (await submit(client, path, after)).status_code == 201
        clock[0] = datetime(2026, 10, 15, 13, tzinfo=UTC)
        assert (await app.state.valuations.evaluate(UUID(contest["id"])))["processed"] == 1
        assert (await client.get(path + "/leaderboard")).json()["data_kind"] == "fixture"


def test_nifty50_catalogue_matches_official_snapshot_and_preserves_legacy_ids():
    import csv
    import hashlib
    import json
    from importlib.resources import files

    document = yahoo_catalogue()
    raw = files("investiq.data").joinpath("nifty50_constituents_2026-10-25.csv").read_bytes()
    official = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    equities = [i for i in document["instruments"] if i["kind"] == "equity"]
    assert len(equities) == 50
    assert {i["symbol"] for i in equities} == {row["Symbol"] for row in official}
    assert document["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert len({i["id"] for i in yahoo_pricing_instruments()}) == 52
    assert {i["symbol"] for i in document["legacy_instruments"]} == {"WIPRO"}
    old = json.loads(files("investiq.data").joinpath("yahoo_catalogue_v1.json").read_text())
    ids = {i["symbol"]: i["id"] for i in yahoo_pricing_instruments()}
    assert all(ids[i["symbol"]] == i["id"] for i in old["instruments"])


async def test_expansion_imports_new_version_and_keeps_historical_cutoffs_consistent(
    market_settings, monkeypatch
):
    import json
    from importlib.resources import files
    from uuid import uuid4

    import investiq.adapters.yahoo_market as adapter
    import investiq.services.market_ingestion as ingestion

    settings = config(market_settings).model_copy(update={"market_data_mode": "yahoo"})
    app = create_app(
        settings, CapturedMailer(), market_clock=lambda: INSTANT, contest_clock=lambda: INSTANT
    )
    monkeypatch.setattr(ingestion, "now", lambda: INSTANT)
    old = json.loads(files("investiq.data").joinpath("yahoo_catalogue_v1.json").read_text())
    old_time = datetime(2026, 10, 14, 12, 40, tzinfo=UTC)
    legacy_id = uuid4()
    async with api_client(app) as client:
        service = MarketIngestionService(app.state.sessions, settings)
        await service.seed_yahoo_catalogue()
        async with app.state.sessions() as db, db.begin():
            db.add(
                IngestionRun(
                    id=legacy_id,
                    provider="yahoo-finance",
                    dataset_version="yahoo-eod-v1",
                    session_date=DAY,
                    data_kind="yahoo",
                    status="succeeded",
                    attempts=1,
                    point_count=11,
                    content_hash="0" * 64,
                    error_code=None,
                    started_at=old_time,
                    completed_at=old_time,
                )
            )
            await db.flush()
            for i in old["instruments"]:
                db.add(
                    PriceSnapshot(
                        run_id=legacy_id,
                        instrument_id=UUID(i["id"]),
                        session_date=DAY,
                        open=Decimal(100),
                        close=Decimal(100),
                        observed_at=datetime(2026, 10, 14, 10, tzinfo=UTC),
                        source_published_at=old_time,
                    )
                )

        def provider(timeout):
            return YahooMarketProvider(
                timeout,
                loader=lambda tickers, day: bars(day, Decimal("1.10")),
                clock=lambda: INSTANT,
            )

        monkeypatch.setattr(adapter, "YahooMarketProvider", provider)
        imported = await service.sync_yahoo(DAY, DAY)
        assert imported["imported"] == 1  # A smaller v1 batch must not skip the v2 import.
        current = (await client.get("/api/v1/instruments", params={"limit": 100})).json()["items"]
        assert len(current) == 50 and "WIPRO" not in {i["symbol"] for i in current}
        legacy = (
            await client.get("/api/v1/instruments", params={"limit": 100, "include_legacy": "true"})
        ).json()["items"]
        assert len(legacy) == 51 and "WIPRO" in {i["symbol"] for i in legacy}
        identifiers = ",".join(i["id"] for i in legacy)
        response = await client.get(
            "/api/v1/quotes", params={"instrument_ids": identifiers, "require_complete": "true"}
        )
        assert response.status_code == 200, response.text
        assert all(
            q["dataset_version"] == "yahoo-eod-v2" and Decimal(q["close"]) == 110
            for q in response.json()["items"]
        )
        history = await client.get(
            "/api/v1/quotes",
            params={
                "instrument_ids": ",".join(i["id"] for i in old["instruments"]),
                "as_of": "2026-10-14T12:50:00Z",
                "require_complete": "true",
            },
        )
        assert history.status_code == 200, history.text
        assert all(
            q["dataset_version"] == "yahoo-eod-v1" and Decimal(q["close"]) == 100
            for q in history.json()["items"]
        )
        template = (await client.get("/api/v1/contest-template")).json()
        assert set(template["rules"]["eligible_instrument_ids"]) == {i["id"] for i in current}

        from tests.test_contest import create as community_create
        from tests.test_contest import publish

        await verified(client, app.state.identity.mailer)
        contest = await community_create(client, template)
        path = "/api/v1/contests/" + contest["id"]
        await publish(client, contest["id"])
        assert (await client.post(path + "/entries", headers=await csrf(client))).status_code == 200
        await save(client, path, weights(template))
        reviewed = await preview(client, path, 1)
        assert reviewed["benchmark"]["dataset_version"] == "yahoo-eod-v2"
        assert all(h["dataset_version"] == "yahoo-eod-v2" for h in reviewed["holdings"])
