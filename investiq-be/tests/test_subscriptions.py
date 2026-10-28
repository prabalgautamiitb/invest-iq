import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from investiq.core.config import Settings
from investiq.main import create_app
from investiq.models.identity import AuditEvent
from tests.conftest import CapturedMailer
from tests.helpers import test_client as api_client
from tests.test_identity import csrf, register

pytestmark = pytest.mark.integration


async def test_subscription_prices_persist_isolate_accounts_and_retry_without_extending(
    identity_settings: Settings,
) -> None:
    app = create_app(identity_settings, CapturedMailer())
    async with (
        api_client(app) as alice,
        api_client(create_app(identity_settings, CapturedMailer())) as bob,
    ):
        user = await register(alice)
        await register(bob)
        assert user["subscription"] is None
        headers = await csrf(alice)
        responses = await asyncio.gather(
            *[
                alice.post("/api/v1/me/subscription", headers=headers, json={"plan": "student"})
                for _ in range(2)
            ]
        )
        assert [r.status_code for r in responses] == [200, 200]
        subscription = responses[0].json()["subscription"]
        assert responses[1].json()["subscription"] == subscription
        assert subscription["plan"] == "student"
        assert subscription["monthly_price_inr"] == 99
        assert subscription["status"] == "active"
        assert not subscription["auto_renew"] and not subscription["payments_enabled"]
        assert (await alice.get("/api/v1/me")).json()["subscription"] == subscription
        assert (await bob.get("/api/v1/me")).json()["subscription"] is None
        different = await alice.post(
            "/api/v1/me/subscription", headers=headers, json={"plan": "standard"}
        )
        assert different.status_code == 409
        standard = await bob.post(
            "/api/v1/me/subscription", headers=await csrf(bob), json={"plan": "standard"}
        )
        assert standard.json()["subscription"]["monthly_price_inr"] == 199
        async with app.state.identity.factory() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.actor_id == user["id"],
                        AuditEvent.action == "subscription.started",
                    )
                )
                == 1
            )


@pytest.mark.parametrize(
    "start,end",
    [
        (datetime(2026, 1, 31, 10, tzinfo=UTC), datetime(2026, 2, 28, 10, tzinfo=UTC)),
        # This UTC instant is already 1 February in India.
        (datetime(2026, 1, 31, 20, tzinfo=UTC), datetime(2026, 2, 28, 20, tzinfo=UTC)),
    ],
)
async def test_subscription_calendar_month_expiry_and_manual_restart(
    identity_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    start: datetime,
    end: datetime,
) -> None:
    app = create_app(identity_settings, CapturedMailer())
    async with api_client(app) as client:
        await register(client)
        monkeypatch.setattr("investiq.services.identity.now", lambda: start)
        first = await client.post(
            "/api/v1/me/subscription", headers=await csrf(client), json={"plan": "student"}
        )
        assert first.status_code == 200
        assert datetime.fromisoformat(first.json()["subscription"]["ends_at"]) == end
        monkeypatch.setattr("investiq.services.identity.now", lambda: end)
        assert (await client.get("/api/v1/me")).json()["subscription"]["status"] == "expired"
        restart = await client.post(
            "/api/v1/me/subscription", headers=await csrf(client), json={"plan": "standard"}
        )
        assert restart.json()["subscription"]["plan"] == "standard"
        assert restart.json()["subscription"]["status"] == "active"
        assert datetime.fromisoformat(restart.json()["subscription"]["ends_at"]) > end
        assert datetime.fromisoformat(restart.json()["subscription"]["starts_at"]) == end
        assert end > start + timedelta(days=20)


async def test_subscription_requires_authentication_csrf_and_server_controlled_prices(
    identity_settings: Settings,
) -> None:
    app = create_app(identity_settings, CapturedMailer())
    async with api_client(app) as client:
        guest = await client.post(
            "/api/v1/me/subscription", headers=await csrf(client), json={"plan": "student"}
        )
        assert guest.status_code == 401
        await register(client)
        assert (
            await client.post("/api/v1/me/subscription", json={"plan": "student"})
        ).status_code == 403
        for body in [
            {"plan": "gold"},
            {"plan": "student", "price": 1},
            {"plan": "standard", "user_id": "other"},
        ]:
            result = await client.post(
                "/api/v1/me/subscription", headers=await csrf(client), json=body
            )
            assert result.status_code == 422
        assert (await client.get("/api/v1/me")).json()["subscription"] is None
