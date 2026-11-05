import asyncio
import os
import sys
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from investiq.core.config import Settings
from investiq.main import create_app
from investiq.models.contest import ContestMembership
from investiq.models.market import PriceSnapshot
from investiq.models.wallet import VirtualWallet, WalletEntry, WalletPosition
from tests.conftest import CapturedMailer
from tests.helpers import test_client as api_client
from tests.test_contest import ANCHOR, create, payload, publish, verified
from tests.test_identity import csrf, register
from tests.test_portfolio import config
from tests.test_valuation import ENTRY, FINAL, FIRST, scenario

pytestmark = pytest.mark.integration


async def funds(client):
    response = await client.get("/api/v1/me/wallet")
    assert response.status_code == 200, response.text
    return response.json()


async def overall(client):
    response = await client.get("/api/v1/me/portfolio")
    assert response.status_code == 200, response.text
    return response.json()


async def contest(client, capital="600000", **changes):
    data = await payload(client, **changes)
    data["rules"]["capital"] = capital
    result = await create(client, data)
    await publish(client, result["id"])
    return result, "/api/v1/contests/" + result["id"]


async def test_registration_grants_once_and_wallet_is_private(market_settings: Settings):
    settings, mailer = config(market_settings), CapturedMailer()
    app = create_app(settings, mailer)
    async with api_client(app) as alice, api_client(create_app(settings, mailer)) as bob:
        assert (await alice.get("/api/v1/me/wallet")).status_code == 401
        assert (await alice.get("/api/v1/me/portfolio")).status_code == 401
        user = await register(alice, "wallet-register@example.com")
        for _ in range(3):
            wallet = await funds(alice)
            assert Decimal(wallet["available"]) == 1000000
            assert Decimal(wallet["total_value"]) == 1000000
            assert len(wallet["recent_entries"]) == 1
        portfolio = await overall(alice)
        assert Decimal(portfolio["total_value"]) == 1000000
        assert portfolio["series"] == [{"session_date": None, "total_value": "1000000.0000"}]
        await register(bob, "wallet-other@example.com")
        assert wallet["recent_entries"][0]["id"] != (await funds(bob))["recent_entries"][0]["id"]
        assert (await bob.get("/api/v1/me/wallet/" + user["id"])).status_code == 404
        async with app.state.sessions() as db:
            assert await db.get(VirtualWallet, UUID(user["id"])) is not None


async def test_concurrent_entries_cannot_double_spend_and_cancel_refunds_once(
    market_settings: Settings,
):
    settings, mailer = config(market_settings), CapturedMailer()
    app = create_app(settings, mailer, contest_clock=lambda: ANCHOR)
    async with api_client(app) as client:
        await verified(client, mailer)
        a, first = await contest(client)
        b, second = await contest(client)
        headers = await csrf(client)
        results = await asyncio.gather(
            client.post(first + "/entries", headers=headers),
            client.post(second + "/entries", headers=headers),
        )
        assert sorted(r.status_code for r in results) == [200, 409]
        rejected = next(r for r in results if r.status_code == 409)
        assert rejected.json()["error"]["code"] == "insufficient_wallet_balance"
        winner = first if results[0].status_code == 200 else second
        assert (await client.post(winner + "/entries", headers=headers)).status_code == 200
        wallet = await funds(client)
        assert Decimal(wallet["available"]) == 400000
        assert Decimal(wallet["reserved_capital"]) == Decimal(wallet["invested_value"]) == 600000
        assert Decimal(wallet["total_value"]) == 1000000
        assert Decimal((await overall(client))["total_value"]) == 1000000
        assert len(wallet["positions"]) == 1
        # An entry that cannot be funded must not consume a seat.
        loser = second if winner == first else first
        assert (await client.get(loser)).json()["member_count"] == 0
        for _ in range(2):
            assert (
                await client.post(
                    winner + "/transitions", headers=headers, json={"action": "cancel"}
                )
            ).status_code == 200
        wallet = await funds(client)
        assert Decimal(wallet["available"]) == 1000000 and not wallet["positions"]
        assert [e["kind"] for e in wallet["recent_entries"]].count("cancellation") == 1
        assert sum(Decimal(e["amount"]) for e in wallet["recent_entries"]) == 1000000
        async with app.state.sessions() as db:
            for statement in [
                update(WalletEntry).values(amount=0),
                update(WalletPosition).values(current_value=0),
                update(VirtualWallet).values(available=-1),
            ]:
                with pytest.raises(IntegrityError):
                    await db.execute(statement)
                    await db.commit()
                await db.rollback()


@pytest.mark.parametrize("factor", [Decimal("0.8"), Decimal("1.2")])
async def test_daily_values_and_final_profit_or_loss_return_exactly_once(
    market_settings: Settings, factor: Decimal
):
    settings, mailer, clock = config(market_settings), CapturedMailer(), [ENTRY]
    app = create_app(settings, mailer, contest_clock=lambda: clock[0])
    async with api_client(app) as client:
        await verified(client, mailer)
        c, _, path, _ = await scenario(client)
        assert Decimal((await funds(client))["available"]) == 0
        clock[0] = FIRST
        assert (await app.state.valuations.evaluate(UUID(c["id"])))["processed"] == 1
        metrics = (await client.get(path + "/performance")).json()["metrics"]
        wallet = await funds(client)
        assert Decimal(wallet["invested_value"]) == Decimal(metrics["total_value"])
        assert Decimal(wallet["available"]) == 0  # Unrealized gains are never spendable.
        first_total = Decimal(wallet["total_value"])
        portfolio = await overall(client)
        assert Decimal(portfolio["total_value"]) == first_total
        assert len(portfolio["series"]) == 2
        assert Decimal(portfolio["series"][-1]["total_value"]) == first_total
        assert (await app.state.valuations.evaluate(UUID(c["id"])))["processed"] == 0
        assert Decimal((await funds(client))["total_value"]) == first_total
        async with app.state.sessions() as db, db.begin():
            await db.execute(
                update(PriceSnapshot)
                .where(PriceSnapshot.session_date == FINAL.date())
                .values(close=PriceSnapshot.close * factor)
            )
        clock[0] = FINAL
        results = await asyncio.gather(
            *[app.state.valuations.evaluate(UUID(c["id"])) for _ in range(3)]
        )
        assert all(r["status"] == "completed" for r in results)
        metrics = (await client.get(path + "/performance")).json()["metrics"]
        wallet = await funds(client)
        final = Decimal(metrics["total_value"])
        assert Decimal(wallet["available"]) == Decimal(wallet["total_value"]) == final
        assert (final > 1000000) == (factor > 1)
        assert Decimal(wallet["pnl"]) == final - 1000000
        assert Decimal(wallet["invested_value"]) == 0 and not wallet["positions"]
        assert [e["kind"] for e in wallet["recent_entries"]].count("settlement") == 1
        assert sum(Decimal(e["amount"]) for e in wallet["recent_entries"]) == final
        portfolio = await overall(client)
        assert Decimal(portfolio["total_value"]) == final
        assert Decimal(portfolio["series"][-1]["total_value"]) == final
        assert len(portfolio["series"]) == 3
        # Reinvesting funds transfers principal; it must not create another capital grant.
        clock[0] = ANCHOR
        _, next_path = await contest(client, "500000")
        assert (
            await client.post(next_path + "/entries", headers=await csrf(client))
        ).status_code == 200
        reinvested = await overall(client)
        assert Decimal(reinvested["total_value"]) == final
        assert reinvested["series"] == portfolio["series"]


async def test_unsubmitted_entry_refund_and_invitation_uses_same_budget(market_settings: Settings):
    settings, mailer, clock = config(market_settings), CapturedMailer(), [ENTRY]
    app = create_app(settings, mailer, contest_clock=lambda: clock[0])
    async with (
        api_client(app) as host,
        api_client(create_app(settings, mailer, contest_clock=lambda: clock[0])) as member,
    ):
        await verified(host, mailer, "wallet-host@example.com")
        # Create the same dates as the real valuation scenario, without a submitted portfolio.
        data = await payload(host)
        data.update(
            entry_opens_at="2026-10-14T12:40:00Z",
            entry_closes_at="2026-10-15T03:40:00Z",
            starts_at="2026-10-15T03:45:00Z",
            ends_at="2026-10-16T10:00:00Z",
            visibility="private",
        )
        c = await create(host, data)
        await publish(host, c["id"])
        path = "/api/v1/contests/" + c["id"]
        await verified(member, mailer, "wallet-member@example.com")
        response = await host.post(
            path + "/invitations",
            headers=await csrf(host),
            json={"email": "wallet-member@example.com"},
        )
        assert response.status_code == 201, response.text
        invitation = response.json()
        response = await member.post(
            f"/api/v1/contest-invitations/{invitation['id']}/accept", headers=await csrf(member)
        )
        assert response.status_code == 200, response.text
        assert Decimal((await funds(member))["available"]) == 0
        second = await create(host, {**data, "name": "Insufficient invitation capital"})
        await publish(host, second["id"])
        second_path = "/api/v1/contests/" + second["id"]
        invited = await host.post(
            second_path + "/invitations",
            headers=await csrf(host),
            json={"email": "wallet-member@example.com"},
        )
        invitation_id = invited.json()["id"]
        rejected = await member.post(
            f"/api/v1/contest-invitations/{invitation_id}/accept", headers=await csrf(member)
        )
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "insufficient_wallet_balance"
        pending = (await member.get("/api/v1/me/contest-invitations")).json()["items"]
        assert any(i["id"] == invitation_id and i["status"] == "pending" for i in pending)
        assert (await host.get(second_path)).json()["member_count"] == 0
        clock[0] = FINAL
        assert (await app.state.valuations.evaluate(UUID(c["id"])))["status"] == "completed"
        wallet = await funds(member)
        assert Decimal(wallet["available"]) == 1000000
        assert wallet["recent_entries"][0]["kind"] == "no_submission"


async def test_two_funded_contests_aggregate_and_finalize_concurrently(market_settings: Settings):
    settings, mailer, clock = config(market_settings), CapturedMailer(), [ENTRY]
    app = create_app(settings, mailer, contest_clock=lambda: clock[0])
    async with api_client(app) as client:
        await verified(client, mailer)
        first, _, first_path, _ = await scenario(client, capital="500000")
        second, _, second_path, _ = await scenario(client, capital="500000")
        wallet = await funds(client)
        assert Decimal(wallet["available"]) == 0 and len(wallet["positions"]) == 2
        clock[0] = FIRST
        await app.state.valuations.evaluate(UUID(first["id"]))
        metrics = (await client.get(first_path + "/performance")).json()["metrics"]
        wallet = await funds(client)
        assert Decimal(wallet["total_value"]) == Decimal(metrics["total_value"]) + 500000
        clock[0] = FINAL
        results = await asyncio.wait_for(
            asyncio.gather(
                app.state.valuations.evaluate(UUID(first["id"])),
                app.state.valuations.evaluate(UUID(second["id"])),
            ),
            timeout=10,
        )
        assert all(r["status"] == "completed" for r in results)
        totals = [
            Decimal((await client.get(path + "/performance")).json()["metrics"]["total_value"])
            for path in [first_path, second_path]
        ]
        wallet = await funds(client)
        assert Decimal(wallet["total_value"]) == Decimal(wallet["available"]) == sum(totals)
        assert not wallet["positions"]
        assert [e["kind"] for e in wallet["recent_entries"]].count("settlement") == 2
        portfolio = await overall(client)
        assert Decimal(portfolio["total_value"]) == sum(totals)
        assert Decimal(portfolio["series"][-1]["total_value"]) == sum(totals)
        # Two concurrent contest snapshots create one overall point per market day.
        assert len(portfolio["series"]) == 3


async def test_legacy_membership_is_not_retroactively_charged(market_settings: Settings):
    settings, mailer = config(market_settings), CapturedMailer()
    app = create_app(settings, mailer, contest_clock=lambda: ANCHOR)
    async with api_client(app) as client:
        user = await verified(client, mailer)
        c, path = await contest(client, "1000000")
        async with app.state.sessions() as db, db.begin():
            db.add(
                ContestMembership(
                    contest_id=UUID(c["id"]), user_id=UUID(user["id"]), rule_id=UUID(c["rule_id"])
                )
            )
        assert (await client.post(path + "/entries", headers=await csrf(client))).status_code == 200
        wallet = await funds(client)
        assert Decimal(wallet["available"]) == 1000000
        assert wallet["legacy_contest_count"] == 1 and not wallet["positions"]
        assert not (await client.get(path)).json()["wallet_backed"]
        portfolio = await overall(client)
        assert Decimal(portfolio["total_value"]) == 1000000
        assert portfolio["legacy_contest_count"] == 1 and len(portfolio["series"]) == 1
        async with app.state.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(WalletPosition)) == 0
            assert await db.scalar(select(func.count()).select_from(WalletEntry)) == 1


async def test_migration_backfills_existing_users_without_funding_old_memberships(
    market_settings: Settings,
):
    settings, mailer = config(market_settings), CapturedMailer()
    app = create_app(settings, mailer, contest_clock=lambda: ANCHOR)
    async with api_client(app) as client:
        user = await verified(client, mailer)
        c, _ = await contest(client, "1000000")
        async with app.state.sessions() as db, db.begin():
            db.add(
                ContestMembership(
                    contest_id=UUID(c["id"]),
                    user_id=UUID(user["id"]),
                    rule_id=UUID(c["rule_id"]),
                )
            )
    for action, revision in [("downgrade", "0015_subscriptions"), ("upgrade", "head")]:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            action,
            revision,
            env={**os.environ, "INVESTIQ_DATABASE_URL": settings.database_url.get_secret_value()},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        assert process.returncode == 0, stderr.decode()
    app = create_app(settings, mailer, contest_clock=lambda: ANCHOR)
    async with api_client(app) as client:
        # The old session and membership survive migration; sign in using normal auth.
        from tests.test_identity import PASSWORD

        response = await client.post(
            "/api/v1/auth/login",
            headers=await csrf(client),
            json={"email": user["email"], "password": PASSWORD},
        )
        assert response.status_code == 200, response.text
        wallet = await funds(client)
        assert Decimal(wallet["available"]) == 1000000
        assert wallet["legacy_contest_count"] == 1 and not wallet["positions"]
        assert len(wallet["recent_entries"]) == 1
