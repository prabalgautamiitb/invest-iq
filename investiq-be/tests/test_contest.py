import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from investiq.core.config import Settings
from investiq.main import create_app
from investiq.models.contest import Contest, ContestMembership, ContestRules
from investiq.models.identity import User
from tests.conftest import CapturedMailer
from tests.helpers import test_client as api_client
from tests.test_identity import csrf, register

pytestmark = pytest.mark.integration
ANCHOR = datetime(2026, 10, 18, 12, tzinfo=UTC)


async def verified(client, mailer, address=None):
    address = address or f"contest-{uuid4().hex}@example.com"
    user = await register(client, address)
    response = await client.post(
        "/api/v1/auth/verification/complete",
        headers=await csrf(client),
        json={"token": mailer.token(address, "verification")},
    )
    assert response.status_code == 200
    return user


async def payload(client, **overrides):
    instruments = (await client.get("/api/v1/instruments", params={"limit": 100})).json()["items"]
    benchmark = (await client.get("/api/v1/instruments", params={"kind": "benchmark"})).json()[
        "items"
    ][0]["id"]
    return dict(
        name="Phase 4 learning league",
        description="Fixture simulation, no prizes.",
        visibility="public",
        level="beginner",
        capacity=10,
        entry_opens_at="2026-10-17T00:00:00Z",
        entry_closes_at="2026-10-19T03:40:00Z",
        starts_at="2026-10-19T03:45:00Z",
        ends_at="2026-10-23T10:00:00Z",
        rules=dict(
            capital="1000000.00",
            benchmark_id=benchmark,
            eligible_instrument_ids=[i["id"] for i in instruments],
        ),
        **overrides,
    )


async def create(client, data):
    response = await client.post(
        "/api/v1/contests",
        headers={**await csrf(client), "Idempotency-Key": str(uuid4())},
        json=data,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def publish(client, identifier):
    response = await client.post(
        f"/api/v1/contests/{identifier}/transitions",
        headers=await csrf(client),
        json={"action": "publish"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_creation_version_freeze_idempotency_and_authorization(market_settings: Settings):
    config = market_settings.model_copy(
        update={
            "auth_rate_limit": 10000,
            "csrf_rate_limit": 10000,
            "rate_limit_prefix": str(uuid4()),
        }
    )
    mailer = CapturedMailer()
    app = create_app(config, mailer, contest_clock=lambda: ANCHOR)
    async with (
        api_client(app) as owner,
        api_client(create_app(config, mailer, contest_clock=lambda: ANCHOR)) as other,
    ):
        await register(owner, "host@example.com")
        data = await payload(owner)
        headers = {**await csrf(owner), "Idempotency-Key": str(uuid4())}
        assert (await owner.post("/api/v1/contests", headers=headers, json=data)).status_code == 403
        assert (
            await owner.post(
                "/api/v1/auth/verification/complete",
                headers=await csrf(owner),
                json={"token": mailer.token("host@example.com", "verification")},
            )
        ).status_code == 200
        a = await owner.post("/api/v1/contests", headers=headers, json=data)
        assert a.status_code == 201, a.text
        identifier = a.json()["id"]
        assert (await owner.post("/api/v1/contests", headers=headers, json=data)).json()[
            "id"
        ] == identifier
        assert (
            await owner.post("/api/v1/contests", headers=headers, json={**data, "name": "Other"})
        ).status_code == 409
        assert (await other.get(f"/api/v1/contests/{identifier}")).status_code == 404
        assert (await other.get("/api/v1/contests")).json()["items"] == []
        await verified(other, mailer)
        assert (
            await other.put(f"/api/v1/contests/{identifier}", headers=await csrf(other), json=data)
        ).status_code == 404
        revised = await owner.put(
            f"/api/v1/contests/{identifier}",
            headers=await csrf(owner),
            json={**data, "name": "Revised league"},
        )
        assert revised.json()["rule_version"] == 2
        published = await publish(owner, identifier)
        assert published["status"] == "open" and published["member_count"] == 0
        assert published["rules"]["capital"] == "1000000.00"
        assert (
            await owner.put(f"/api/v1/contests/{identifier}", headers=await csrf(owner), json=data)
        ).status_code == 409
        assert (
            await other.post(
                f"/api/v1/contests/{identifier}/transitions",
                headers=await csrf(other),
                json={"action": "cancel"},
            )
        ).status_code == 403
        assert (
            await owner.post(f"/api/v1/contests/{identifier}/entries", json={})
        ).status_code == 403
        joined = await owner.post(
            f"/api/v1/contests/{identifier}/entries", headers=await csrf(owner)
        )
        assert joined.json()["member_count"] == 1
        assert (
            await owner.post(f"/api/v1/contests/{identifier}/entries", headers=await csrf(owner))
        ).json()["member_count"] == 1
        assert (await owner.get("/api/v1/me/contests")).json()["items"][0]["id"] == identifier
        async with app.state.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(ContestRules)) == 2
            member = await db.scalar(select(ContestMembership))
            assert str(member.rule_id) == published["rule_id"]
            with pytest.raises(IntegrityError):
                await db.execute(update(ContestRules).values(capital=1))
                await db.commit()
            await db.rollback()
            with pytest.raises(IntegrityError):
                await db.execute(
                    update(Contest).where(Contest.id == UUID(identifier)).values(capacity=1)
                )
                await db.commit()
            await db.rollback()


async def test_private_invitations_isolation_retries_revocation_and_expiry(
    market_settings: Settings,
):
    config = market_settings.model_copy(
        update={
            "auth_rate_limit": 10000,
            "csrf_rate_limit": 10000,
            "rate_limit_prefix": str(uuid4()),
        }
    )
    mailer = CapturedMailer()
    clock = [ANCHOR]
    app = create_app(config, mailer, contest_clock=lambda: clock[0])
    async with (
        api_client(app) as owner,
        api_client(create_app(config, mailer, contest_clock=lambda: clock[0])) as guest,
        api_client(create_app(config, mailer, contest_clock=lambda: clock[0])) as stranger,
    ):
        await verified(owner, mailer)
        await verified(guest, mailer, "guest@example.com")
        await verified(stranger, mailer)
        data = await payload(owner)
        data["visibility"] = "private"
        c = await create(owner, data)
        await publish(owner, c["id"])
        path = f"/api/v1/contests/{c['id']}"
        assert (await guest.get(path)).status_code == 404
        assert (await guest.post(path + "/entries", headers=await csrf(guest))).status_code == 404
        invitation = await owner.post(
            path + "/invitations", headers=await csrf(owner), json={"email": "GUEST@example.com"}
        )
        assert invitation.status_code == 201, invitation.text
        i = invitation.json()["id"]
        assert (await guest.get("/api/v1/me/contest-invitations")).json()["items"][0]["id"] == i
        assert (await stranger.get("/api/v1/contests")).json()["items"] == []
        assert (
            await stranger.post(
                f"/api/v1/contest-invitations/{i}/accept", headers=await csrf(stranger)
            )
        ).status_code == 404
        assert (await guest.get(path + "/invitations")).status_code == 403
        for _ in range(2):
            accepted = await guest.post(
                f"/api/v1/contest-invitations/{i}/accept", headers=await csrf(guest)
            )
            assert accepted.status_code == 200, accepted.text
        assert (await guest.get(path)).json()["joined"] is True
        assert (await owner.get(path)).json()["member_count"] == 1
        invitation2 = (
            await owner.post(
                path + "/invitations",
                headers=await csrf(owner),
                json={"email": "future@example.com"},
            )
        ).json()
        assert (
            await owner.post(
                f"/api/v1/contest-invitations/{invitation2['id']}/revoke", headers=await csrf(owner)
            )
        ).json()["status"] == "revoked"
        invitation3 = (
            await owner.post(
                path + "/invitations",
                headers=await csrf(owner),
                json={"email": "expiry@example.com"},
            )
        ).json()
        clock[0] = datetime(2026, 10, 19, 3, 40, tzinfo=UTC)
        assert (
            await owner.post(
                f"/api/v1/contest-invitations/{invitation3['id']}/revoke", headers=await csrf(owner)
            )
        ).status_code == 409
        assert (await owner.get(path + "/invitations")).json()["items"]
        assert (await owner.get(path)).json()["status"] == "locked"
        assert (
            await owner.post(
                path + "/transitions", headers=await csrf(owner), json={"action": "cancel"}
            )
        ).status_code == 409
        clock[0] = datetime(2026, 10, 19, 3, 45, tzinfo=UTC)
        assert (await owner.get(path)).json()["status"] == "running"
        clock[0] = datetime(2026, 10, 23, 10, tzinfo=UTC)
        assert (await owner.get(path)).json()["status"] == "settling"
        assert (
            await owner.post(
                path + "/transitions", headers=await csrf(owner), json={"action": "complete"}
            )
        ).status_code == 422


async def test_capacity_race_and_filter_pagination(market_settings: Settings):
    config = market_settings.model_copy(
        update={
            "auth_rate_limit": 10000,
            "csrf_rate_limit": 10000,
            "rate_limit_prefix": str(uuid4()),
        }
    )
    mailer = CapturedMailer()
    app = create_app(config, mailer, contest_clock=lambda: ANCHOR)
    async with (
        api_client(app) as a,
        api_client(create_app(config, mailer, contest_clock=lambda: ANCHOR)) as b,
    ):
        await verified(a, mailer)
        await verified(b, mailer)
        data = await payload(a)
        data["capacity"] = 1
        c = await create(a, data)
        await publish(a, c["id"])
        path = f"/api/v1/contests/{c['id']}"
        ah, bh = await csrf(a), await csrf(b)
        results = await asyncio.gather(
            a.post(path + "/entries", headers=ah), b.post(path + "/entries", headers=bh)
        )
        assert sorted(r.status_code for r in results) == [200, 409]
        assert (await a.get(path)).json()["member_count"] == 1
        for name in ["Alpha", "Zulu"]:
            d = await create(a, {**data, "name": name})
            await publish(a, d["id"])
        first = (await a.get("/api/v1/contests", params={"limit": 1})).json()
        assert first["items"][0]["name"] == "Alpha"
        assert (
            await a.get(
                "/api/v1/contests",
                params={"limit": 1, "cursor": first["next_cursor"], "sort": "-name"},
            )
        ).status_code == 422
        second = (
            await a.get("/api/v1/contests", params={"limit": 1, "cursor": first["next_cursor"]})
        ).json()
        assert second["items"][0]["id"] != first["items"][0]["id"]
        assert len((await a.get("/api/v1/contests", params={"query": "%"})).json()["items"]) == 0
        assert (
            len(
                (
                    await a.get(
                        "/api/v1/contests",
                        params={"status": "open", "level": "beginner", "visibility": "public"},
                    )
                ).json()["items"]
            )
            == 3
        )
        for invalid in [
            {**data, "starts_at": "2026-10-18T03:45:00Z"},
            {**data, "ends_at": "2027-01-01T10:00:00Z"},
            {**data, "rules": {**data["rules"], "eligible_instrument_ids": [str(uuid4())] * 5}},
            {**data, "rules": {**data["rules"], "capital": "NaN"}},
        ]:
            response = await a.post(
                "/api/v1/contests", headers={**ah, "Idempotency-Key": str(uuid4())}, json=invalid
            )
            assert response.status_code == 422, response.text
        cancelled = await a.post(path + "/transitions", headers=ah, json={"action": "cancel"})
        assert cancelled.json()["status"] == "cancelled"
        assert (
            await a.post(path + "/transitions", headers=ah, json={"action": "publish"})
        ).status_code == 409
        async with app.state.sessions() as db, db.begin():
            await db.execute(update(User).values(active=False))
        assert (await a.post(path + "/entries", headers=ah)).status_code == 401


async def test_template_seed_calendar_exclusions_and_terminal_invitations(
    market_settings: Settings,
):
    from investiq.models.contest import ContestEligibleInstrument
    from investiq.models.market import Instrument

    config = market_settings.model_copy(
        update={
            "auth_rate_limit": 10000,
            "csrf_rate_limit": 10000,
            "rate_limit_prefix": str(uuid4()),
        }
    )
    mailer = CapturedMailer()
    instant = [ANCHOR]
    app = create_app(config, mailer, contest_clock=lambda: instant[0])
    async with (
        api_client(app) as host,
        api_client(create_app(config, mailer, contest_clock=lambda: instant[0])) as guest,
    ):
        template = (await host.get("/api/v1/contest-template")).json()
        assert template["starts_at"] == "2026-10-19T03:45:00Z"
        assert template["ends_at"] == "2026-10-26T10:00:00Z"
        assert len(template["rules"]["eligible_instrument_ids"]) == 16
        from investiq.core.errors import AppError

        with pytest.raises(AppError) as missing:
            await app.state.contests.seed_draft("missing@example.com")
        assert missing.value.code == "verified_owner_required"
        await verified(host, mailer, "seed-owner@example.com")
        seeded = await app.state.contests.seed_draft("seed-owner@example.com")
        assert seeded.status == "draft" and seeded.member_count == 0
        assert (await app.state.contests.seed_draft("seed-owner@example.com")).id == seeded.id
        assert (await host.get("/api/v1/me/contests", params={"scope": "hosted"})).json()["items"][
            0
        ]["id"] == str(seeded.id)
        async with app.state.sessions() as db:
            blocked = await db.scalar(select(Instrument.id).where(Instrument.symbol == "FIXSPLIT"))
        bad = {
            **template,
            "rules": {
                **template["rules"],
                "eligible_instrument_ids": template["rules"]["eligible_instrument_ids"]
                + [str(blocked)],
            },
        }
        assert (
            await host.post(
                "/api/v1/contests",
                headers={**await csrf(host), "Idempotency-Key": str(uuid4())},
                json=bad,
            )
        ).status_code == 422
        await publish(host, str(seeded.id))
        async with app.state.sessions() as db:
            with pytest.raises(IntegrityError):
                db.add(ContestEligibleInstrument(rule_id=seeded.rule_id, instrument_id=blocked))
                await db.commit()
            await db.rollback()
        await register(guest, "decline@example.com")
        path = f"/api/v1/contests/{seeded.id}"
        invitation = (
            await host.post(
                path + "/invitations",
                headers=await csrf(host),
                json={"email": "decline@example.com"},
            )
        ).json()
        assert (await guest.get(path)).status_code == 404
        assert (await guest.get("/api/v1/me/contest-invitations")).status_code == 403
        assert (await guest.get("/api/v1/contests")).json()["items"] == []
        assert (
            await guest.post(
                "/api/v1/auth/verification/complete",
                headers=await csrf(guest),
                json={"token": mailer.token("decline@example.com", "verification")},
            )
        ).status_code == 200
        decline = f"/api/v1/contest-invitations/{invitation['id']}/decline"
        for _ in range(2):
            assert (await guest.post(decline, headers=await csrf(guest))).json()[
                "status"
            ] == "declined"
        assert (await guest.get(path)).status_code == 404
        invitation = (
            await host.post(
                path + "/invitations",
                headers=await csrf(host),
                json={"email": "expired@example.com"},
            )
        ).json()
        instant[0] = datetime(2027, 1, 1, tzinfo=UTC)
        assert (await host.get("/api/v1/contest-template")).status_code == 503
        assert (
            await host.post(
                f"/api/v1/contest-invitations/{invitation['id']}/revoke", headers=await csrf(host)
            )
        ).status_code == 409
        production = config.model_copy(update={"environment": "production"})
        app.state.contests.identity.settings = production
        with pytest.raises(AppError) as disabled:
            await app.state.contests.seed_draft("seed-owner@example.com")
        assert disabled.value.status == 503
