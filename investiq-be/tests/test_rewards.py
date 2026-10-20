import asyncio
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.core.security import now
from investiq.db.session import make_engine
from investiq.main import create_app
from investiq.models.learning import LessonCompletion, QuizAttempt, XpEvent
from investiq.models.rewards import CoinAccount, CoinLedger, Redemption, RewardInventory, RewardItem
from investiq.services.learning_seed import seed_curriculum
from investiq.services.rewards import reconcile_earnings
from investiq.services.rewards_seed import seed_rewards
from tests.conftest import CapturedMailer, migrated_database
from tests.helpers import test_client as api_client
from tests.test_contest import verified
from tests.test_identity import csrf, register
from tests.test_learning import enroll, input_for
from tests.test_learning import submit as submit_quiz


@pytest_asyncio.fixture
async def rewards_settings():
    async with migrated_database() as url:
        settings = Settings(
            database_url=SecretStr(url),
            environment="test",
            auth_rate_limit=10000,
            csrf_rate_limit=10000,
            rate_limit_prefix=str(uuid4()),
        )
        engine = make_engine(settings)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            await seed_curriculum(factory, settings)
            await seed_rewards(factory, settings)
        finally:
            await engine.dispose()
        yield settings


async def complete(app, client, index=0, wrong=False, key=None):
    courses = (await client.get("/api/v1/courses")).json()["items"]
    lessons = [(course, lesson) for course in courses for lesson in course["lessons"]]
    course, lesson = lessons[index]
    await enroll(client, course)
    response = await submit_quiz(
        client, lesson["id"], await input_for(app, client, lesson["id"], wrong), key
    )
    assert response.status_code == 201, response.text
    return response.json()


async def cheapest(client):
    return min((await client.get("/api/v1/rewards")).json()["items"], key=lambda item: item["cost"])


async def redeem(client, item, key=None, headers=None, **extra):
    return await client.post(
        "/api/v1/me/redemptions",
        json={"item_id": item["id"], "item_version": item["version"], **extra},
        headers={**(headers or await csrf(client)), "Idempotency-Key": key or str(uuid4())},
    )


async def wallet(client):
    response = await client.get("/api/v1/me/coins")
    assert response.status_code == 200, response.text
    return response.json()


async def test_catalogue_empty_wallet_filters_validation_and_auth(rewards_settings):
    mailer = CapturedMailer()
    app = create_app(rewards_settings, mailer)
    async with api_client(app) as client:
        page = (await client.get("/api/v1/rewards")).json()
        assert len(page["items"]) == 6 and all(i["mode"] == "sandbox" for i in page["items"])
        assert (await client.get("/api/v1/me/coins")).status_code == 401
        assert (await client.get("/api/v1/me/coins/ledger")).status_code == 401
        first = (await client.get("/api/v1/rewards?limit=1")).json()
        second = (
            await client.get("/api/v1/rewards", params={"limit": 1, "cursor": first["next_cursor"]})
        ).json()
        assert first["items"][0]["id"] != second["items"][0]["id"]
        assert (
            await client.get(
                "/api/v1/rewards", params={"category": "digital", "cursor": first["next_cursor"]}
            )
        ).status_code == 422
        assert (await client.get("/api/v1/rewards?cursor=broken")).status_code == 422
        digital = (await client.get("/api/v1/rewards?category=digital")).json()["items"]
        assert len(digital) == 2 and all(i["category"] == "digital" for i in digital)
        assert len((await client.get("/api/v1/rewards?query=notebook")).json()["items"]) == 1
        await register(client)
        empty = await wallet(client)
        assert (
            empty["balance"] == empty["lifetime_earned"] == 0 and empty["tier"]["name"] == "Bronze"
        )
        assert (await client.get("/api/v1/me/redemptions")).json()["items"] == []
        assert (await redeem(client, page["items"][0])).status_code == 403
        with pytest.raises(AppError):
            await seed_rewards(
                app.state.sessions,
                rewards_settings.model_copy(update={"environment": "production"}),
            )


async def test_genuine_learning_credits_ledger_tiers_redemption_retries_and_privacy(
    rewards_settings,
):
    mailer = CapturedMailer()
    app = create_app(rewards_settings, mailer)
    async with api_client(app) as alice, api_client(create_app(rewards_settings, mailer)) as bob:
        await verified(alice, mailer)
        await verified(bob, mailer)
        assert not (await complete(app, alice, 0, wrong=True))["passed"]
        assert (await wallet(alice))["balance"] == 0
        key = str(uuid4())
        await complete(app, alice, 0, key=key)
        await complete(app, alice, 0, key=key)
        await complete(app, alice, 0)
        assert (await wallet(alice))["balance"] == 50
        await complete(app, alice, 1)
        rich = await wallet(alice)
        assert (
            rich["balance"] == rich["lifetime_earned"] == 100 and rich["tier"]["name"] == "Silver"
        )
        item = await cheapest(alice)
        key = str(uuid4())
        response = await redeem(alice, item, key)
        assert response.status_code == 201, response.text
        original = response.json()
        assert original["status"] == "sandbox_confirmed" and original["balance_after"] == 50
        assert (await wallet(alice))["tier"]["name"] == "Silver"
        await complete(app, alice, 2)
        assert (await redeem(alice, item, key)).json() == original
        assert (await wallet(alice))["balance"] == 100
        assert (await redeem(alice, item, item_version=item["version"] + 1)).status_code == 409
        assert (await redeem(alice, item, cost=1)).status_code == 422
        assert (await redeem(alice, item, shipping_address="real address")).status_code == 422
        assert (
            await alice.post(
                "/api/v1/me/redemptions", json={"item_id": item["id"], "item_version": 1}
            )
        ).status_code == 403
        assert (await redeem(alice, item)).status_code == 201
        assert (await wallet(alice))["balance"] == 50 and (await wallet(alice))[
            "lifetime_earned"
        ] == 150
        history = (await alice.get("/api/v1/me/redemptions?limit=1")).json()
        assert len(history["items"]) == 1 and history["next_cursor"]
        assert (
            await bob.get("/api/v1/me/redemptions", params={"cursor": history["next_cursor"]})
        ).status_code == 422
        ledger = (await alice.get("/api/v1/me/coins/ledger?limit=2")).json()
        assert [i["sequence"] for i in ledger["items"]] == [5, 4] and ledger["next_cursor"]
        assert (
            await bob.get("/api/v1/me/coins/ledger", params={"cursor": ledger["next_cursor"]})
        ).status_code == 422
        assert (await wallet(bob))["balance"] == 0
        assert (await bob.get("/api/v1/me/coins/ledger")).json()["items"] == []
        assert (await bob.get("/api/v1/me/redemptions")).json()["items"] == []
        await seed_rewards(app.state.sessions, rewards_settings)
        current = (await alice.get("/api/v1/rewards/" + item["id"])).json()
        assert current["remaining"] == item["remaining"] - 2
        async with app.state.sessions() as db, db.begin():
            await db.execute(
                update(RewardItem).where(RewardItem.id == UUID(item["id"])).values(active=False)
            )
        await seed_rewards(app.state.sessions, rewards_settings)
        assert (await alice.get("/api/v1/rewards/" + item["id"])).status_code == 404
        assert (await redeem(alice, item, key)).json() == original
        assert (await redeem(alice, item)).status_code == 404
        other = (await alice.get("/api/v1/rewards")).json()["items"][0]
        assert (await redeem(alice, other, key)).status_code == 409


async def test_duplicate_and_competing_redemptions_do_not_double_spend(rewards_settings):
    mailer = CapturedMailer()
    app = create_app(rewards_settings, mailer)
    async with api_client(app) as client:
        await verified(client, mailer)
        await complete(app, client)
        item = await cheapest(client)
        headers = await csrf(client)
        key = str(uuid4())
        replies = await asyncio.gather(*(redeem(client, item, key, headers) for _ in range(8)))
        assert all(r.status_code == 201 for r in replies), [r.text for r in replies]
        assert (
            len({r.json()["id"] for r in replies}) == 1 and (await wallet(client))["balance"] == 0
        )
        await complete(app, client, 1)
        replies = await asyncio.gather(*(redeem(client, item, headers=headers) for _ in range(8)))
        assert sum(r.status_code == 201 for r in replies) == 1
        assert all(r.status_code in {201, 409} for r in replies)
        assert (await wallet(client))["balance"] == 0 and (await wallet(client))[
            "lifetime_earned"
        ] == 100
        async with app.state.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Redemption)) == 2
            assert await db.scalar(select(func.count()).select_from(CoinLedger)) == 4


async def test_two_accounts_cannot_oversell_last_inventory_unit(rewards_settings):
    mailer = CapturedMailer()
    app = create_app(rewards_settings, mailer)
    async with api_client(app) as alice, api_client(create_app(rewards_settings, mailer)) as bob:
        await verified(alice, mailer)
        await verified(bob, mailer)
        await complete(app, alice)
        await complete(app, bob)
        identifier = uuid4()
        async with app.state.sessions() as db, db.begin():
            db.add(
                RewardItem(
                    id=identifier,
                    slug="last-unit",
                    name="Last sandbox unit",
                    description="Test catalogue stock",
                    category="digital",
                    cost=50,
                    version=1,
                    active=True,
                )
            )
            await db.flush()
            db.add(RewardInventory(item_id=identifier, capacity=1, remaining=1))
        item = {"id": str(identifier), "version": 1}
        headers = await asyncio.gather(csrf(alice), csrf(bob))
        replies = await asyncio.gather(
            redeem(alice, item, headers=headers[0]), redeem(bob, item, headers=headers[1])
        )
        assert sorted(r.status_code for r in replies) == [201, 409], [r.text for r in replies]
        assert sorted([(await wallet(alice))["balance"], (await wallet(bob))["balance"]]) == [0, 50]
        async with app.state.sessions() as db:
            assert (await db.get(RewardInventory, identifier)).remaining == 0
            assert await db.scalar(select(func.count()).select_from(Redemption)) == 1


async def test_reconciliation_credits_existing_genuine_completions_once(
    rewards_settings, monkeypatch
):
    import investiq.services.learning as learning

    async def before_phase8(*args):
        return 0

    mailer = CapturedMailer()
    app = create_app(rewards_settings, mailer)
    async with api_client(app) as client:
        await verified(client, mailer)
        with monkeypatch.context() as context:
            context.setattr(learning, "credit_completions", before_phase8)
            await complete(app, client)
            await complete(app, client, 1)
        assert (await wallet(client))["balance"] == 0
        counts = await asyncio.gather(
            reconcile_earnings(app.state.sessions), reconcile_earnings(app.state.sessions)
        )
        assert sum(counts) == 2 and (await wallet(client))["balance"] == 100
        assert await reconcile_earnings(app.state.sessions) == 0
        await complete(app, client)
        assert (await wallet(client))["balance"] == 100


async def test_learning_and_coin_award_are_one_atomic_transaction(rewards_settings, monkeypatch):
    import investiq.services.learning as learning

    async def unavailable(*args):
        raise AppError(503, "coin_award_unavailable", "Retry the lesson submission")

    mailer = CapturedMailer()
    app = create_app(rewards_settings, mailer)
    async with api_client(app) as client:
        await verified(client, mailer)
        courses = (await client.get("/api/v1/courses")).json()["items"]
        course = courses[0]
        lesson = course["lessons"][0]
        await enroll(client, course)
        data = await input_for(app, client, lesson["id"])
        key = str(uuid4())
        with monkeypatch.context() as context:
            context.setattr(learning, "credit_completions", unavailable)
            response = await submit_quiz(client, lesson["id"], data, key)
            assert response.status_code == 503
        async with app.state.sessions() as db:
            for model in (QuizAttempt, LessonCompletion, XpEvent, CoinLedger):
                assert await db.scalar(select(func.count()).select_from(model)) == 0
        assert (await submit_quiz(client, lesson["id"], data, key)).status_code == 201
        assert (await wallet(client))["balance"] == 50


async def test_database_rejects_forged_totals_mutable_ledger_and_unbacked_redemption(
    rewards_settings,
):
    mailer = CapturedMailer()
    app = create_app(rewards_settings, mailer)
    async with api_client(app) as client:
        user = await verified(client, mailer)
        await complete(app, client)
        item = await cheapest(client)
        for statement in [
            update(CoinAccount).values(balance=500, lifetime_earned=500),
            update(CoinLedger).values(delta=999),
            delete(CoinLedger),
            update(RewardInventory).values(remaining=0),
        ]:
            with pytest.raises(IntegrityError):
                async with app.state.sessions() as db, db.begin():
                    await db.execute(statement)
        with pytest.raises(IntegrityError):
            async with app.state.sessions() as db, db.begin():
                db.add(
                    Redemption(
                        user_id=UUID(user["id"]),
                        item_id=UUID(item["id"]),
                        idempotency_key=uuid4(),
                        request_hash="a" * 64,
                        item_version=1,
                        item_name=item["name"],
                        cost=item["cost"],
                        balance_after=0,
                        created_at=now(),
                    )
                )
        assert (await wallet(client))["balance"] == 50
        assert (await client.get("/api/v1/me/redemptions")).json()["items"] == []
