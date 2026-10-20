import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from investiq.analytics.portfolio import allocate
from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.main import create_app
from investiq.models.contest import ContestMembership
from investiq.models.market import Instrument, PriceSnapshot
from investiq.models.portfolio import PortfolioSubmission, SubmissionHolding
from investiq.schemas.contest import RulesInput
from investiq.schemas.portfolio import DraftInput, PositionInput
from tests.conftest import CapturedMailer
from tests.helpers import test_client as api_client
from tests.test_contest import ANCHOR, create, payload, publish, verified
from tests.test_identity import csrf, register


def config(settings):
    return settings.model_copy(
        update={
            "auth_rate_limit": 10000,
            "csrf_rate_limit": 10000,
            "rate_limit_prefix": str(uuid4()),
        }
    )


async def league(client):
    data = await payload(client)
    contest = await create(client, data)
    await publish(client, contest["id"])
    assert (
        await client.post(f"/api/v1/contests/{contest['id']}/entries", headers=await csrf(client))
    ).status_code == 200
    return contest, data


def weights(data, revision=0):
    return {
        "expected_revision": revision,
        "mode": "weight",
        "positions": [
            {"instrument_id": i, "weight_pct": "20"}
            for i in data["rules"]["eligible_instrument_ids"][:5]
        ],
    }


async def save(client, path, data):
    response = await client.put(path + "/portfolio/draft", headers=await csrf(client), json=data)
    assert response.status_code == 200, response.text
    return response.json()


async def preview(client, path, revision):
    response = await client.post(
        path + "/portfolio/preview", headers=await csrf(client), json={"draft_revision": revision}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def submit(client, path, reviewed, key=None):
    return await client.post(
        path + "/submissions",
        headers={**await csrf(client), "Idempotency-Key": key or str(uuid4())},
        json={
            "draft_revision": reviewed["draft_revision"],
            "preview_hash": reviewed["preview_hash"],
        },
    )


def rules(**changes):
    identifiers = [uuid4() for _ in range(5)]
    return RulesInput(benchmark_id=uuid4(), eligible_instrument_ids=identifiers, **changes)


def test_decimal_allocation_fee_reserve_floor_and_residual_cash():
    r = rules(capital=Decimal("1000.00"))
    positions = [PositionInput(instrument_id=i, weight_pct="20") for i in r.eligible_instrument_ids]
    result = allocate(r, positions, {i: Decimal("3.3333") for i in r.eligible_instrument_ids})
    assert set(result.quantities.values()) == {59}
    assert result.notional == Decimal("983.3235")
    assert result.fee == Decimal("0.98")
    assert result.cash == Decimal("15.6965")
    assert result.notional + result.fee + result.cash == r.capital
    # Target weights need not spend all capital. Residual cash is an explicit rule.
    smaller = [PositionInput(instrument_id=i, weight_pct="10") for i in r.eligible_instrument_ids]
    assert (
        allocate(r, smaller, {i: Decimal("3.3333") for i in r.eligible_instrument_ids}).cash > 500
    )
    quantity = [PositionInput(instrument_id=i, quantity=1) for i in r.eligible_instrument_ids]
    half_paise = allocate(r, quantity, {i: Decimal("1.0000") for i in r.eligible_instrument_ids})
    assert half_paise.fee == Decimal("0.01")


@pytest.mark.parametrize(
    "case,code",
    [
        ("count", "holding_count"),
        ("zero_shares", "invalid_share_count"),
        ("position", "position_limit"),
        ("capital", "insufficient_capital"),
        ("weights", "weight_total"),
    ],
)
def test_allocation_rejects_invalid_economics(case, code):
    r = rules(capital=Decimal("1000.00"), max_position_bps=10000 if case == "capital" else 2500)
    positions = [PositionInput(instrument_id=i, quantity=1) for i in r.eligible_instrument_ids]
    prices = {i: Decimal("10") for i in r.eligible_instrument_ids}
    if case == "count":
        positions.pop()
    if case == "position":
        prices[positions[0].instrument_id] = Decimal("250.0001")
    if case == "capital":
        prices = {i: Decimal("200") for i in r.eligible_instrument_ids}
    if case in {"weights", "zero_shares"}:
        positions = [
            PositionInput(instrument_id=i, weight_pct="21" if case == "weights" else "0.0001")
            for i in r.eligible_instrument_ids
        ]
    with pytest.raises(AppError) as rejected:
        allocate(r, positions, prices)
    assert rejected.value.code == code


@pytest.mark.parametrize(
    "position",
    [
        {"quantity": 0},
        {"quantity": -1},
        {"quantity": 1.2},
        {"quantity": True},
        {"weight_pct": "NaN"},
        {"weight_pct": "Infinity"},
        {"weight_pct": 20.0},
        {"weight_pct": "0"},
        {"quantity": 1, "weight_pct": "20"},
        {"quantity": 1000000001},
    ],
)
def test_input_rejects_ambiguous_or_nonexact_allocations(position):
    with pytest.raises(ValidationError):
        PositionInput(instrument_id=uuid4(), **position)


@pytest.mark.integration
async def test_draft_review_immutable_versions_history_and_retry_after_lock(
    market_settings: Settings,
):
    mailer, clock = CapturedMailer(), [ANCHOR]
    app = create_app(config(market_settings), mailer, contest_clock=lambda: clock[0])
    async with api_client(app) as client:
        await verified(client, mailer)
        c, data = await league(client)
        path = "/api/v1/contests/" + c["id"]
        empty = (await client.get(path + "/portfolio/draft")).json()
        assert empty["revision"] == 0 and empty["id"] is None
        draft = await save(client, path, weights(data))
        assert draft["revision"] == 1 and draft["rule_id"] == c["rule_id"]
        reviewed = await preview(client, path, 1)
        assert reviewed["price_session_date"] == "2026-10-16"
        assert reviewed["benchmark"]["price_snapshot_id"]
        assert sum(Decimal(reviewed[k]) for k in ["notional", "fee", "cash"]) == Decimal("1000000")
        key = str(uuid4())
        response = await submit(client, path, reviewed, key)
        assert response.status_code == 201, response.text
        first = response.json()
        assert first["version"] == 1 and first["is_latest"]
        assert (await submit(client, path, reviewed, key)).json()["id"] == first["id"]
        assert (await submit(client, path, reviewed)).status_code == 409
        second_draft = await save(client, path, weights(data, 1))
        assert second_draft["revision"] == 2
        second_preview = await preview(client, path, 2)
        second = await submit(client, path, second_preview)
        assert second.status_code == 201, second.text
        assert second.json()["version"] == 2
        assert (await submit(client, path, second_preview, key)).status_code == 409
        page = (await client.get(path + "/submissions", params={"limit": 1})).json()
        assert page["items"][0]["version"] == 2
        older = (
            await client.get(
                path + "/submissions", params={"cursor": page["next_cursor"], "limit": 1}
            )
        ).json()
        assert older["items"][0]["id"] == first["id"] and not older["items"][0]["is_latest"]
        clock[0] = datetime(2026, 10, 19, 3, 40, tzinfo=UTC)
        assert (await client.get(path + "/portfolio/draft")).json()["editable"] is False
        assert (
            await client.put(
                path + "/portfolio/draft", headers=await csrf(client), json=weights(data, 2)
            )
        ).status_code == 409
        assert (await submit(client, path, reviewed, key)).json()["id"] == first["id"]
        assert (
            await client.post(
                path + "/portfolio/preview", headers=await csrf(client), json={"draft_revision": 2}
            )
        ).status_code == 409
        # Both copied holdings and header resist direct SQL mutation/deletion/appending.
        async with app.state.sessions() as db:
            for statement in [
                update(PortfolioSubmission).values(cash=0),
                delete(PortfolioSubmission),
                update(SubmissionHolding).values(quantity=2),
                delete(SubmissionHolding),
            ]:
                with pytest.raises(IntegrityError):
                    await db.execute(statement)
                    await db.commit()
                await db.rollback()
            existing = await db.scalar(select(SubmissionHolding).limit(1))
            with pytest.raises(IntegrityError):
                values = {
                    col.name: getattr(existing, col.name)
                    for col in SubmissionHolding.__table__.columns
                }
                values["instrument_id"] = UUID(data["rules"]["eligible_instrument_ids"][5])
                await db.execute(insert(SubmissionHolding).values(**values))
                await db.commit()
            await db.rollback()
            # An incomplete, unsealed construction cannot commit even through direct SQL.
            previous = await db.scalar(select(PortfolioSubmission).limit(1))
            values = {
                col.name: getattr(previous, col.name)
                for col in PortfolioSubmission.__table__.columns
            }
            values.update(
                id=uuid4(), version=99, draft_revision=99, idempotency_key=uuid4(), sealed=False
            )
            with pytest.raises(IntegrityError):
                await db.execute(insert(PortfolioSubmission).values(**values))
                await db.commit()
            await db.rollback()
            assert await db.scalar(select(func.count()).select_from(PortfolioSubmission)) == 2


@pytest.mark.integration
async def test_concurrent_submission_and_optimistic_draft_saves(market_settings: Settings):
    app = create_app(config(market_settings), CapturedMailer(), contest_clock=lambda: ANCHOR)
    async with api_client(app) as client:
        await verified(client, app.state.identity.mailer)
        c, data = await league(client)
        path = "/api/v1/contests/" + c["id"]
        await save(client, path, weights(data))
        reviewed = await preview(client, path, 1)
        key, headers = str(uuid4()), await csrf(client)
        body = {"draft_revision": 1, "preview_hash": reviewed["preview_hash"]}
        calls = [
            client.post(
                path + "/submissions", headers={**headers, "Idempotency-Key": key}, json=body
            )
            for _ in range(3)
        ]
        results = await asyncio.gather(*calls)
        assert all(r.status_code == 201 for r in results), [r.text for r in results]
        assert len({r.json()["id"] for r in results}) == 1
        drafts = await asyncio.gather(
            *[
                client.put(path + "/portfolio/draft", headers=headers, json=weights(data, 1))
                for _ in range(2)
            ]
        )
        assert sorted(r.status_code for r in drafts) == [200, 409]
        new = await preview(client, path, 2)
        results = await asyncio.gather(submit(client, path, new), submit(client, path, new))
        assert sorted(r.status_code for r in results) == [201, 409]
        assert len((await client.get(path + "/submissions")).json()["items"]) == 2


@pytest.mark.integration
async def test_access_validation_private_isolation_and_failed_submission_rollback(
    market_settings: Settings,
):
    settings, mailer = config(market_settings), CapturedMailer()
    app = create_app(settings, mailer, contest_clock=lambda: ANCHOR)
    async with (
        api_client(app) as owner,
        api_client(create_app(settings, mailer, contest_clock=lambda: ANCHOR)) as other,
    ):
        await verified(owner, mailer)
        c, data = await league(owner)
        path = "/api/v1/contests/" + c["id"]
        assert (await other.get(path + "/portfolio/draft")).status_code == 401
        await register(other)
        assert (await other.get(path + "/portfolio/draft")).status_code == 403
        await other.post(
            "/api/v1/auth/verification/complete",
            headers=await csrf(other),
            json={"token": mailer.messages[-1][2]},
        )
        assert (await other.get(path + "/portfolio/draft")).status_code == 404
        headers = await csrf(owner)
        assert (await owner.put(path + "/portfolio/draft", json=weights(data))).status_code == 403
        for bad in [
            {**weights(data), "user_id": str(uuid4())},
            {
                **weights(data),
                "positions": [{"instrument_id": str(uuid4()), "quantity": 1}],
                "mode": "quantity",
            },
            {**weights(data), "positions": weights(data)["positions"] * 2},
        ]:
            assert (
                await owner.put(path + "/portfolio/draft", headers=headers, json=bad)
            ).status_code == 422
        assert (await owner.get(path + "/portfolio/draft")).json()["revision"] == 0
        await save(
            owner,
            path,
            {
                "expected_revision": 0,
                "mode": "quantity",
                "positions": [
                    {"instrument_id": i, "quantity": 1}
                    for i in data["rules"]["eligible_instrument_ids"][:4]
                ],
            },
        )
        bad = await owner.post(
            path + "/portfolio/preview", headers=headers, json={"draft_revision": 1}
        )
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "holding_count"
        await save(owner, path, weights(data, 1))
        reviewed = await preview(owner, path, 2)
        # Another member sees their own empty draft, never the host's positions/history.
        assert (await other.post(path + "/entries", headers=await csrf(other))).status_code == 200
        assert (await other.get(path + "/portfolio/draft")).json()["revision"] == 0
        assert (await other.get(path + "/submissions")).json()["items"] == []
        assert (await submit(other, path, reviewed)).status_code == 409
        # Client prices/ranks/fees are not part of the accepted contract.
        assert (
            await owner.post(
                path + "/submissions",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={"draft_revision": 2, "preview_hash": reviewed["preview_hash"], "fee": "0"},
            )
        ).status_code == 422
        # Changing the quote after review requires another review and creates nothing.
        snapshot_id = UUID(reviewed["holdings"][0]["price_snapshot_id"])
        async with app.state.sessions() as db, db.begin():
            await db.execute(
                update(PriceSnapshot)
                .where(PriceSnapshot.id == snapshot_id)
                .values(close=PriceSnapshot.close + 1)
            )
        stale = await submit(owner, path, reviewed)
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "preview_changed"
        current = await preview(owner, path, 2)
        submitted = (await submit(owner, path, current)).json()
        async with app.state.sessions() as db, db.begin():
            await db.execute(
                update(PriceSnapshot)
                .where(PriceSnapshot.id == snapshot_id)
                .values(close=PriceSnapshot.close + 1)
            )
        assert (await owner.get(path + "/submissions")).json()["items"][0]["holdings"] == submitted[
            "holdings"
        ]
        # No fallback to another day when a required current benchmark is missing.
        benchmark_id = UUID(data["rules"]["benchmark_id"])
        await save(owner, path, weights(data, 2))
        async with app.state.sessions() as db, db.begin():
            await db.execute(
                update(Instrument).where(Instrument.id == benchmark_id).values(active=False)
            )
        result = await owner.post(
            path + "/portfolio/preview", headers=headers, json={"draft_revision": 3}
        )
        assert (
            result.status_code == 409 and result.json()["error"]["code"] == "market_data_incomplete"
        )
        async with app.state.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(PortfolioSubmission)) == 1
            assert await db.scalar(select(func.count()).select_from(ContestMembership)) == 2


@pytest.mark.integration
async def test_current_eod_required_and_no_future_publications_or_stale_fallback(
    market_settings: Settings,
):
    mailer, clock = CapturedMailer(), [ANCHOR]
    app = create_app(config(market_settings), mailer, contest_clock=lambda: clock[0])
    async with api_client(app) as client:
        await verified(client, mailer)
        c, data = await league(client)
        path = "/api/v1/contests/" + c["id"]
        await save(client, path, weights(data))
        reviewed = await preview(client, path, 1)
        target = UUID(reviewed["holdings"][0]["price_snapshot_id"])
        async with app.state.sessions() as db, db.begin():
            await db.execute(
                update(PriceSnapshot)
                .where(PriceSnapshot.id == target)
                .values(source_published_at=datetime(2026, 10, 19, 0, tzinfo=UTC))
            )
        result = await client.post(
            path + "/portfolio/preview", headers=await csrf(client), json={"draft_revision": 1}
        )
        assert (
            result.status_code == 409 and result.json()["error"]["code"] == "market_data_incomplete"
        )
        # Yesterday's snapshots exist, but are not silently substituted for this missing point.
        clock[0] = datetime(2026, 10, 19, 3, 39, tzinfo=UTC)
        assert (
            await client.post(
                path + "/portfolio/preview", headers=await csrf(client), json={"draft_revision": 1}
            )
        ).status_code == 200
        clock[0] = datetime(2026, 10, 19, 3, 40, tzinfo=UTC)
        assert (await submit(client, path, reviewed)).status_code == 409
        async with app.state.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(PortfolioSubmission)) == 0


@pytest.mark.integration
async def test_custom_rules_empty_draft_quantity_submission_and_new_exclusion(
    market_settings: Settings,
):
    import json
    from importlib.resources import files

    from investiq.models.market import MarketExclusion

    mailer = CapturedMailer()
    app = create_app(config(market_settings), mailer, contest_clock=lambda: ANCHOR)
    async with api_client(app) as client:
        await verified(client, mailer)
        data = await payload(client)
        data["rules"].update(
            min_holdings=2,
            max_holdings=3,
            max_position_bps=7000,
            simulated_cost_bps=25,
            capital="500000.00",
        )
        c = await create(client, data)
        await publish(client, c["id"])
        path = "/api/v1/contests/" + c["id"]
        await client.post(path + "/entries", headers=await csrf(client))
        empty = await save(
            client, path, {"expected_revision": 0, "mode": "quantity", "positions": []}
        )
        assert empty["revision"] == 1
        allocations = [
            {"instrument_id": i, "quantity": 10}
            for i in data["rules"]["eligible_instrument_ids"][:2]
        ]
        await save(
            client, path, {"expected_revision": 1, "mode": "quantity", "positions": allocations}
        )
        p = await preview(client, path, 2)
        assert len(p["holdings"]) == 2 and Decimal(p["capital"]) == 500000
        response = await submit(client, path, p)
        assert response.status_code == 201, response.text
        # New corporate-action constraints are checked despite the original frozen whitelist.
        async with app.state.sessions() as db, db.begin():
            db.add(
                MarketExclusion(
                    id=uuid4(),
                    instrument_id=UUID(allocations[0]["instrument_id"]),
                    starts_on=ANCHOR.date(),
                    ends_on=None,
                    reason="New unsupported corporate action",
                    source="test",
                )
            )
        invalid = await client.put(
            path + "/portfolio/draft",
            headers=await csrf(client),
            json={"expected_revision": 2, "mode": "quantity", "positions": allocations},
        )
        assert invalid.status_code == 422
        assert (await client.get(path + "/portfolio/draft")).json()["revision"] == 2
        # The versioned starter data is valid typed input, never automatically stored as activity.
        example = json.loads(
            files("investiq.data").joinpath("portfolio_draft_fixture_v1.json").read_text()
        )
        assert len(DraftInput.model_validate(example).positions) == 5
