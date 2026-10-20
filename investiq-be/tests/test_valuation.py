import asyncio
import os
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from investiq.analytics.valuation import ValuedHolding, value_portfolio
from investiq.core.config import Settings
from investiq.main import create_app
from investiq.models.identity import AuditEvent
from investiq.models.market import PriceSnapshot
from investiq.models.valuation import (
    ContestFinalization,
    ValuationPrice,
    ValuationRecord,
    ValuationRun,
)
from tests.conftest import CapturedMailer
from tests.helpers import test_client as api_client
from tests.test_contest import create, payload, publish, verified
from tests.test_identity import csrf
from tests.test_portfolio import config, preview, save, submit, weights

ENTRY = datetime(2026, 10, 14, 13, tzinfo=UTC)
FIRST = datetime(2026, 10, 15, 13, tzinfo=UTC)
FINAL = datetime(2026, 10, 16, 13, tzinfo=UTC)


async def scenario(client, private=False):
    data = await payload(client)
    data.update(
        entry_opens_at="2026-10-14T12:40:00Z",
        entry_closes_at="2026-10-15T03:40:00Z",
        starts_at="2026-10-15T03:45:00Z",
        ends_at="2026-10-16T10:00:00Z",
        visibility="private" if private else "public",
    )
    c = await create(client, data)
    await publish(client, c["id"])
    path = "/api/v1/contests/" + c["id"]
    assert (await client.post(path + "/entries", headers=await csrf(client))).status_code == 200
    await save(client, path, weights(data))
    reviewed = await preview(client, path, 1)
    accepted = await submit(client, path, reviewed)
    assert accepted.status_code == 201, accepted.text
    return c, data, path, accepted.json()


def test_deterministic_valuation_drawdown_fee_cash_and_contributions():
    a, b = uuid4(), uuid4()
    holdings = [
        ValuedHolding(a, "A", 10, Decimal("100"), Decimal("12"), uuid4()),
        ValuedHolding(b, "B", 10, Decimal("100"), Decimal("8"), uuid4()),
    ]
    result = value_portfolio(
        Decimal("1000"), Decimal("799.8"), Decimal(".2"), Decimal("100"), Decimal("105"), holdings
    )
    assert result.total_value == Decimal("999.8") and result.pnl == Decimal("-.2")
    assert result.return_pct == Decimal("-.02000000")
    assert result.benchmark_return_pct == 5 and result.excess_return_pct == Decimal("-5.02")
    assert result.max_drawdown_pct == Decimal(".02")
    assert result.concentration_hhi == Decimal(".52")
    assert result.sector_count == 2 and result.holding_count == 2
    assert sum(Decimal(p["pnl"]) for p in result.positions) == 0
    # A prior market peak remains part of the daily close drawdown path.
    drawdown = value_portfolio(
        Decimal("1000"),
        Decimal("799.8"),
        Decimal(".2"),
        Decimal("100"),
        Decimal("105"),
        holdings,
        Decimal("1100"),
        Decimal("2"),
    )
    assert drawdown.peak_value == 1100 and drawdown.max_drawdown_pct > 9


@pytest.mark.integration
async def test_common_snapshots_latest_submission_privacy_and_concurrent_finalization(
    market_settings: Settings,
):
    settings, mailer, clock = config(market_settings), CapturedMailer(), [ENTRY]
    app = create_app(settings, mailer, contest_clock=lambda: clock[0])
    async with (
        api_client(app) as alice,
        api_client(create_app(settings, mailer, contest_clock=lambda: clock[0])) as bob,
        api_client(create_app(settings, mailer, contest_clock=lambda: clock[0])) as guest,
    ):
        await verified(alice, mailer, "valuation-alice@example.com")
        c, data, path, first = await scenario(alice)
        await verified(bob, mailer, "valuation-bob@example.com")
        await bob.post(path + "/entries", headers=await csrf(bob))
        await save(bob, path, weights(data))
        await submit(bob, path, await preview(bob, path, 1))
        # Alice's second accepted snapshot is used, even with a newer unsubmitted draft.
        await save(
            alice,
            path,
            {
                "expected_revision": 1,
                "mode": "quantity",
                "positions": [
                    {"instrument_id": i, "quantity": 10}
                    for i in data["rules"]["eligible_instrument_ids"][:5]
                ],
            },
        )
        accepted = (await submit(alice, path, await preview(alice, path, 2))).json()
        await save(alice, path, weights(data, 2))
        clock[0] = datetime(2026, 10, 15, 12, 29, tzinfo=UTC)
        assert (await app.state.valuations.evaluate(UUID(c["id"])))["status"] == "waiting"
        clock[0] = FIRST
        value = await app.state.valuations.evaluate(UUID(c["id"]))
        assert value["processed"] == 1
        board = (await guest.get(path + "/leaderboard")).json()
        assert board["participant_count"] == 2 and board["is_current"] and not board["is_final"]
        assert [r["rank"] for r in board["items"]] == [1, 2]
        assert all(r["label"].startswith("Learner ") for r in board["items"])
        assert "email" not in str(board) and "positions" not in str(board)
        own = (await alice.get(path + "/performance")).json()
        assert own["metrics"]["submission_id"] == accepted["id"] != first["id"]
        assert own["metrics"]["capital"] == "1000000.0000"
        assert len(own["metrics"]["positions"]) == 5
        await alice.patch("/api/v1/me/privacy", headers=await csrf(alice), json={"public": True})
        board = (await guest.get(path + "/leaderboard", params={"limit": 1})).json()
        assert board["next_cursor"]
        assert (
            await guest.get(
                path + "/leaderboard", params={"limit": 1, "cursor": board["next_cursor"]}
            )
        ).json()["items"][0]["rank"] == 2
        assert (
            await bob.get(path + "/leaderboard", params={"cursor": board["next_cursor"]})
        ).status_code == 422
        assert (await guest.get(path + "/performance")).status_code == 401
        clock[0] = datetime(2026, 10, 16, 10, 1, tzinfo=UTC)
        assert (await app.state.valuations.evaluate(UUID(c["id"])))["status"] == "waiting"
        assert (await alice.get(path)).json()["status"] == "settling"
        clock[0] = FINAL
        results = await asyncio.gather(
            *[app.state.valuations.evaluate(UUID(c["id"])) for _ in range(4)]
        )
        assert all(r["status"] == "completed" for r in results)
        assert len({r["run_id"] for r in results}) == 1
        final = (await alice.get(path + "/leaderboard")).json()
        assert final["is_final"] and final["session_date"] == "2026-10-16"
        assert (await alice.get(path)).json()["status"] == "completed"
        own = (await alice.get(path + "/performance", params={"limit": 1})).json()
        assert own["next_cursor"] and len(own["series"]) == 1
        assert (
            len(
                (
                    await alice.get(path + "/performance", params={"cursor": own["next_cursor"]})
                ).json()["series"]
            )
            == 1
        )
        dashboard = (await alice.get("/api/v1/me/dashboard")).json()
        assert (
            dashboard["joined_count"]
            == dashboard["completed_count"]
            == dashboard["valued_count"]
            == 1
        )
        assert len((await alice.get("/api/v1/me/contest-history")).json()["items"]) == 1
        async with app.state.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(ValuationRun)) == 2
            assert await db.scalar(select(func.count()).select_from(ValuationRecord)) == 4
            assert await db.scalar(select(func.count()).select_from(ContestFinalization)) == 1
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "contest_results_finalized")
                )
                == 1
            )
            for statement in [
                update(ValuationRun).values(participant_count=0),
                delete(ValuationRecord),
                update(ValuationPrice).values(price=1),
                delete(ContestFinalization),
            ]:
                with pytest.raises(IntegrityError):
                    await db.execute(statement)
                    await db.commit()
                await db.rollback()
        # Source corrections cannot rewrite a completed, copied snapshot.
        async with app.state.sessions() as db, db.begin():
            await db.execute(update(PriceSnapshot).values(close=PriceSnapshot.close + 10))
        assert (await alice.get(path + "/leaderboard")).json() == final


@pytest.mark.integration
async def test_missing_price_blocks_everyone_retry_backfills_and_private_access(
    market_settings: Settings,
):
    settings, mailer, clock = config(market_settings), CapturedMailer(), [ENTRY]
    app = create_app(settings, mailer, contest_clock=lambda: clock[0])
    async with (
        api_client(app) as owner,
        api_client(create_app(settings, mailer, contest_clock=lambda: clock[0])) as outsider,
    ):
        await verified(owner, mailer)
        c, data, path, _ = await scenario(owner, private=True)
        assert (await outsider.get(path + "/leaderboard")).status_code == 404
        await verified(outsider, mailer)
        assert (await outsider.get(path + "/performance")).status_code == 404
        target = UUID(data["rules"]["eligible_instrument_ids"][0])
        async with app.state.sessions() as db, db.begin():
            point = await db.scalar(
                select(PriceSnapshot).where(
                    PriceSnapshot.instrument_id == target,
                    PriceSnapshot.session_date == date(2026, 10, 15),
                )
            )
            original = {
                col.name: getattr(point, col.name) for col in PriceSnapshot.__table__.columns
            }
            await db.execute(delete(PriceSnapshot).where(PriceSnapshot.id == point.id))
        clock[0] = FINAL
        for attempt in (1, 2):
            result = await app.state.valuations.evaluate(UUID(c["id"]))
            assert (
                result["status"] == "blocked" and result["error_code"] == "market_data_incomplete"
            )
            async with app.state.sessions() as db:
                run = await db.scalar(select(ValuationRun))
                assert run.attempts == attempt and run.status == "blocked"
                assert await db.scalar(select(func.count()).select_from(ValuationRecord)) == 0
                assert await db.scalar(select(func.count()).select_from(ValuationPrice)) == 0
        board = (await owner.get(path + "/leaderboard")).json()
        assert (
            not board["is_current"]
            and board["items"] == []
            and board["error_code"] == "market_data_incomplete"
        )
        assert (await owner.get(path)).json()["status"] == "settling"
        async with app.state.sessions() as db, db.begin():
            await db.execute(insert(PriceSnapshot).values(**original))
        assert (await app.state.valuations.evaluate(UUID(c["id"])))["status"] == "completed"
        assert (await owner.get(path + "/leaderboard")).json()["participant_count"] == 1


@pytest.mark.integration
async def test_persisted_stale_snapshot_and_cancelled_contest_do_not_finalize(
    market_settings: Settings,
):
    mailer, clock = CapturedMailer(), [ENTRY]
    app = create_app(config(market_settings), mailer, contest_clock=lambda: clock[0])
    async with api_client(app) as client:
        await verified(client, mailer)
        c, data, path, _ = await scenario(client)
        clock[0] = FIRST
        await app.state.valuations.evaluate(UUID(c["id"]))
        clock[0] = FINAL
        async with app.state.sessions() as db, db.begin():
            await db.execute(
                delete(PriceSnapshot).where(
                    PriceSnapshot.instrument_id == UUID(data["rules"]["benchmark_id"]),
                    PriceSnapshot.session_date == date(2026, 10, 16),
                )
            )
        await app.state.valuations.evaluate(UUID(c["id"]))
        board = (await client.get(path + "/leaderboard")).json()
        assert (
            board["session_date"] == "2026-10-15" and board["expected_session_date"] == "2026-10-16"
        )
        assert (
            not board["is_current"] and not board["is_final"] and board["job_status"] == "blocked"
        )
        assert not (await client.get("/api/v1/me/dashboard")).json()["all_valued_current"]
        # A separately cancelled contest never receives a ranking or completion record.
        clock[0] = ENTRY
        c2 = await create(client, await payload(client))
        await publish(client, c2["id"])
        await client.post(
            f"/api/v1/contests/{c2['id']}/transitions",
            headers=await csrf(client),
            json={"action": "cancel"},
        )
        clock[0] = FINAL
        assert (await app.state.valuations.evaluate(UUID(c2["id"])))["status"] == "waiting"


@pytest.mark.integration
async def test_real_redis_celery_worker_processes_durable_contest_work(market_settings: Settings):
    from investiq.jobs.valuation import app as celery_app

    settings, mailer = config(market_settings), CapturedMailer()
    app = create_app(settings, mailer, contest_clock=lambda: ENTRY)
    async with api_client(app) as client:
        await verified(client, mailer)
        c, _, _, _ = await scenario(client)
        queue = "investiq-test-" + uuid4().hex
        env = {
            **os.environ,
            "INVESTIQ_DATABASE_URL": settings.database_url.get_secret_value(),
            "INVESTIQ_CELERY_BROKER_URL": settings.celery_broker_url.get_secret_value(),
            "INVESTIQ_VALUATION_QUEUE": queue,
        }
        worker = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "celery",
            "-q",
            "-A",
            "investiq.jobs.valuation:app",
            "worker",
            "--pool=solo",
            "--concurrency=1",
            "--loglevel=WARNING",
            "--without-heartbeat",
            "--without-gossip",
            "--without-mingle",
            "--hostname=" + queue + "@localhost",
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.to_thread(
                celery_app.send_task, "investiq.valuation.scan", queue=queue, ignore_result=True
            )
            completed = False
            for _ in range(100):
                async with app.state.sessions() as db:
                    completed = await db.get(ContestFinalization, UUID(c["id"])) is not None
                if completed:
                    break
                assert worker.returncode is None, (
                    "Test worker exited before processing its isolated queue"
                )
                await asyncio.sleep(0.2)
            assert completed, "Celery worker did not finalize the historical fixture contest"
        finally:
            if worker.returncode is None:
                worker.terminate()
                try:
                    await asyncio.wait_for(worker.wait(), 10)
                except TimeoutError:
                    worker.kill()
                    await worker.wait()
            from redis.asyncio import Redis

            redis = Redis.from_url(settings.celery_broker_url.get_secret_value())
            await redis.delete("investiq:jobs:" + queue, "investiq:jobs:_kombu.binding." + queue)
            await redis.aclose()


@pytest.mark.integration
async def test_ties_use_stable_entry_order_empty_contests_and_incomplete_runs_cannot_commit(
    market_settings: Settings,
):
    settings, mailer, clock = config(market_settings), CapturedMailer(), [ENTRY]
    app = create_app(settings, mailer, contest_clock=lambda: clock[0])
    async with (
        api_client(app) as first,
        api_client(create_app(settings, mailer, contest_clock=lambda: clock[0])) as second,
    ):
        await verified(first, mailer)
        c, data, path, _ = await scenario(first)
        await verified(second, mailer)
        await second.post(path + "/entries", headers=await csrf(second))
        await save(second, path, weights(data))
        await submit(second, path, await preview(second, path, 1))
        # This published contest has no memberships or submissions: no fabricated winner.
        empty_data = await payload(first)
        empty_data.update(
            {k: data[k] for k in ["entry_opens_at", "entry_closes_at", "starts_at", "ends_at"]}
        )
        empty = await create(first, empty_data)
        await publish(first, empty["id"])
        clock[0] = FINAL
        await app.state.valuations.evaluate(UUID(c["id"]))
        board = (await first.get(path + "/leaderboard")).json()
        assert board["items"][0]["return_pct"] == board["items"][1]["return_pct"]
        assert [i["entry_id"] for i in board["items"]] == sorted(
            i["entry_id"] for i in board["items"]
        )
        assert (await app.state.valuations.evaluate(UUID(empty["id"])))["status"] == "completed"
        empty_board = (await first.get(f"/api/v1/contests/{empty['id']}/leaderboard")).json()
        assert (
            empty_board["is_final"]
            and empty_board["items"] == []
            and empty_board["participant_count"] == 0
        )
        async with app.state.sessions() as db:
            source = await db.scalar(select(ValuationPrice).limit(1))
            values = {
                col.name: getattr(source, col.name) for col in ValuationPrice.__table__.columns
            }
            values["instrument_id"] = UUID(data["rules"]["eligible_instrument_ids"][6])
            with pytest.raises(IntegrityError):
                await db.execute(insert(ValuationPrice).values(**values))
                await db.commit()
            await db.rollback()
            with pytest.raises(IntegrityError):
                db.add(
                    ValuationRun(
                        contest_id=UUID(c["id"]),
                        session_date=date(2026, 10, 19),
                        observed_at=FINAL,
                        available_at=FINAL,
                        status="succeeded",
                        attempts=1,
                        participant_count=1,
                        evidence_hash="0" * 64,
                        evaluated_at=FINAL,
                        calculation_version="eod-valuation-v1",
                    )
                )
                await db.commit()
            await db.rollback()


def test_extreme_price_evidence_is_flagged_instead_of_overflowing_persistence():
    from investiq.core.errors import AppError

    h = ValuedHolding(
        uuid4(), "EXTREME", 1000000000, Decimal("10"), Decimal("1000000000000000"), uuid4()
    )
    with pytest.raises(AppError) as rejected:
        value_portfolio(Decimal("100"), Decimal(0), Decimal(0), Decimal("100"), Decimal("100"), [h])
    assert rejected.value.code == "valuation_out_of_range"
