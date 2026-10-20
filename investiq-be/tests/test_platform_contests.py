import asyncio
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from investiq.adapters.market import PublicContestFixtureProvider, public_fixture_document
from investiq.main import create_app
from investiq.models.contest import Contest, ContestMembership
from investiq.models.identity import AuditEvent, User
from investiq.models.market import IngestionRun, PriceSnapshot
from investiq.services.market_ingestion import MarketIngestionService
from tests.conftest import CapturedMailer
from tests.helpers import test_client as api_client
from tests.test_contest import publish, verified
from tests.test_identity import csrf
from tests.test_portfolio import preview, save, submit, weights

ANCHOR = datetime(2026, 10, 14, 13, tzinfo=UTC)


def config(settings):
    return settings.model_copy(
        update={
            "auth_rate_limit": 10000,
            "csrf_rate_limit": 10000,
            "rate_limit_prefix": str(uuid4()),
        }
    )


def historical(data):
    return {
        **data,
        "name": "InvestIQ October public challenge",
        "visibility": "public",
        "entry_opens_at": "2026-10-14T12:40:00Z",
        "entry_closes_at": "2026-10-15T03:40:00Z",
        "starts_at": "2026-10-15T03:45:00Z",
        "ends_at": "2026-10-16T10:00:00Z",
    }


async def payload(client):
    return (await client.get("/api/v1/contest-template")).json()


async def role(app, user, value):
    async with app.state.sessions() as db, db.begin():
        await db.execute(update(User).where(User.id == UUID(user["id"])).values(role=value))


async def create(client, data, key=None):
    return await client.post(
        "/api/v1/admin/contests",
        json=data,
        headers={**await csrf(client), "Idempotency-Key": key or str(uuid4())},
    )


async def test_platform_authority_visibility_retry_and_shared_admin_management(market_settings):
    settings = config(market_settings)
    mailer = CapturedMailer()
    app = create_app(settings, mailer, contest_clock=lambda: ANCHOR, market_clock=lambda: ANCHOR)
    async with (
        api_client(app) as admin,
        api_client(create_app(settings, mailer, contest_clock=lambda: ANCHOR)) as other,
        api_client(create_app(settings, mailer, contest_clock=lambda: ANCHOR)) as guest,
    ):
        admin_user = await verified(admin, mailer)
        other_user = await verified(other, mailer)
        data = historical(await payload(admin))
        assert (await create(admin, data)).status_code == 403
        assert (await admin.get("/api/v1/contests?scope=managed")).status_code == 403
        assert (
            await admin.post(
                "/api/v1/contests",
                json={**data, "organizer": "platform"},
                headers={**await csrf(admin), "Idempotency-Key": str(uuid4())},
            )
        ).status_code == 422
        await role(app, admin_user, "admin")
        assert (await create(admin, {**data, "visibility": "private"})).status_code == 422
        key = str(uuid4())
        response = await create(admin, data, key)
        assert response.status_code == 201, response.text
        contest = response.json()
        identifier = contest["id"]
        assert contest["organizer"] == "platform" and contest["can_manage"]
        assert (await create(admin, data, key)).json() == contest
        assert (await create(admin, {**data, "name": "Changed"}, key)).status_code == 409
        assert (await guest.get("/api/v1/contests/" + identifier)).status_code == 404
        assert (await other.get("/api/v1/contests/" + identifier)).status_code == 404
        await role(app, other_user, "admin")
        shared = (await other.get("/api/v1/contests/" + identifier)).json()
        assert shared["can_manage"] and not shared["is_owner"]
        assert len((await other.get("/api/v1/contests?scope=managed")).json()["items"]) == 1
        revised = await other.put(
            "/api/v1/contests/" + identifier,
            json={**data, "name": "InvestIQ reviewed challenge"},
            headers=await csrf(other),
        )
        assert revised.status_code == 200, revised.text
        assert (
            await other.put(
                "/api/v1/contests/" + identifier,
                json={**data, "visibility": "private"},
                headers=await csrf(other),
            )
        ).status_code == 422
        await publish(other, identifier)
        visible = (await guest.get("/api/v1/contests?organizer=platform")).json()["items"]
        assert len(visible) == 1 and not visible[0]["can_manage"]
        await role(app, admin_user, "user")
        # A stale session principal and original creator ID cannot restore admin authority.
        assert (
            await admin.post(
                f"/api/v1/contests/{identifier}/transitions",
                headers=await csrf(admin),
                json={"action": "cancel"},
            )
        ).status_code == 403
        assert (
            await other.post(
                f"/api/v1/contests/{identifier}/transitions",
                headers=await csrf(other),
                json={"action": "cancel"},
            )
        ).status_code == 200
        async with app.state.sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "platform_contest_created")
                )
                == 1
            )
            assert await db.scalar(select(func.count()).select_from(ContestMembership)) == 0


async def test_every_verified_learner_can_join_submit_and_follow_platform_standings(
    market_settings,
):
    settings = config(market_settings)
    mailer = CapturedMailer()
    clock = [ANCHOR]
    app = create_app(
        settings, mailer, contest_clock=lambda: clock[0], market_clock=lambda: clock[0]
    )
    async with (
        api_client(app) as host,
        api_client(
            create_app(
                settings, mailer, contest_clock=lambda: clock[0], market_clock=lambda: clock[0]
            )
        ) as learner,
    ):
        host_user = await verified(host, mailer)
        await role(app, host_user, "admin")
        await verified(learner, mailer)
        data = historical(await payload(host))
        contest = (await create(host, data)).json()
        identifier = contest["id"]
        await publish(host, identifier)
        assert (
            await learner.post(
                f"/api/v1/contests/{identifier}/entries", headers=await csrf(learner)
            )
        ).status_code == 200
        path = "/api/v1/contests/" + identifier
        await save(learner, path, weights(data))
        reviewed = await preview(learner, path, 1)
        assert (await submit(learner, path, reviewed)).status_code == 201
        clock[0] = datetime(2026, 10, 15, 13, tzinfo=UTC)
        outcome = await app.state.valuations.evaluate(UUID(identifier))
        assert outcome["processed"] == 1
        board = (await learner.get(path + "/leaderboard")).json()
        assert (
            len(board["items"]) == 1
            and board["items"][0]["rank"] == 1
            and board["items"][0]["is_you"]
        )
        performance = (await learner.get(path + "/performance")).json()
        assert performance["metrics"]["rank"] == 1 and performance["metrics"]["total_value"]
        clock[0] = datetime(2026, 10, 16, 13, tzinfo=UTC)
        assert (await app.state.valuations.evaluate(UUID(identifier)))["status"] == "completed"
        assert (await learner.get(path + "/leaderboard")).json()["is_final"]


async def test_platform_publish_requires_covered_scenario_and_current_baseline(market_settings):
    settings = config(market_settings)
    mailer = CapturedMailer()
    app = create_app(settings, mailer, contest_clock=lambda: ANCHOR, market_clock=lambda: ANCHOR)
    async with api_client(app) as client:
        user = await verified(client, mailer)
        await role(app, user, "admin")
        data = await payload(client)
        data["visibility"] = "public"
        c = (await create(client, data)).json()
        response = await client.post(
            "/api/v1/contests/" + c["id"] + "/transitions",
            json={"action": "publish"},
            headers=await csrf(client),
        )
        assert (
            response.status_code == 422
            and response.json()["error"]["code"] == "scenario_coverage_missing"
        )
        data = historical(data)
        c = (await create(client, data)).json()
        async with app.state.sessions() as db, db.begin():
            await db.execute(
                delete(PriceSnapshot).where(
                    PriceSnapshot.session_date == date(2026, 10, 14),
                    PriceSnapshot.instrument_id == UUID(data["rules"]["benchmark_id"]),
                )
            )
        response = await client.post(
            "/api/v1/contests/" + c["id"] + "/transitions",
            json={"action": "publish"},
            headers=await csrf(client),
        )
        assert (
            response.status_code == 409
            and response.json()["error"]["code"] == "platform_prices_unavailable"
        )
        assert (await client.get("/api/v1/contests/" + c["id"])).json()["status"] == "draft"
        with pytest.raises(IntegrityError):
            async with app.state.sessions() as db, db.begin():
                await db.execute(
                    update(Contest).where(Contest.id == UUID(c["id"])).values(organizer="community")
                )
        with pytest.raises(IntegrityError):
            async with app.state.sessions() as db, db.begin():
                await db.execute(
                    update(Contest).where(Contest.id == UUID(c["id"])).values(visibility="private")
                )


async def test_fixed_public_scenario_publishes_only_due_prices_and_retries(
    market_settings, monkeypatch
):
    import investiq.services.market_ingestion as ingestion

    instant = datetime(2026, 10, 20, 12, tzinfo=UTC)
    monkeypatch.setattr(ingestion, "now", lambda: instant)
    settings = config(market_settings).model_copy(update={"public_contest_fixtures_enabled": True})
    mailer = CapturedMailer()
    app = create_app(settings, mailer, market_clock=lambda: instant, contest_clock=lambda: instant)
    async with api_client(app) as client:
        service = MarketIngestionService(app.state.sessions, market_settings)
        results = await asyncio.gather(
            service.seed_public_fixtures(), service.seed_public_fixtures()
        )
        assert results[0] == results[1] and len(results[0]) == 1
        async with app.state.sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(IngestionRun)
                    .where(IngestionRun.dataset_version == "public-fixture-v1")
                )
                == 1
            )
            assert await db.scalar(select(func.max(PriceSnapshot.session_date))) == date(
                2026, 10, 19
            )
        response = (await client.get("/api/v1/instruments", params={"limit": 100})).json()
        ids = ",".join(i["id"] for i in response["items"][:5])
        quotes = await client.get("/api/v1/quotes", params={"instrument_ids": ids})
        assert quotes.status_code == 200, quotes.text
        assert all(
            q["dataset_version"] == "public-fixture-v1" and q["session_date"] == "2026-10-19"
            for q in quotes.json()["items"]
        )
        assert "2026-11-06" in public_fixture_document()["prices"]
        batch = await PublicContestFixtureProvider().fetch_eod(date(2026, 10, 21))
        assert batch.source_published_at > instant

        # Verify accepted submissions and subsequent EOD valuation use the new scenario.
        user = await verified(client, mailer)
        await role(app, user, "admin")
        data = await payload(client)
        data["visibility"] = "public"
        response = await create(client, data)
        assert response.status_code == 201, response.text
        identifier = response.json()["id"]
        await publish(client, identifier)
        path = "/api/v1/contests/" + identifier
        assert (await client.post(path + "/entries", headers=await csrf(client))).status_code == 200
        await save(client, path, weights(data))
        reviewed = await preview(client, path, 1)
        accepted = await submit(client, path, reviewed)
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["price_session_date"] == "2026-10-19"
        instant = datetime(2026, 10, 21, 13, tzinfo=UTC)
        await service.seed_public_fixtures()
        result = await app.state.valuations.evaluate(UUID(identifier))
        assert result["processed"] == 1
        board = (await client.get(path + "/leaderboard")).json()
        assert board["session_date"] == "2026-10-21" and board["items"][0]["rank"] == 1
