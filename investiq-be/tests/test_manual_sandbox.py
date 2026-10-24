import importlib
from pathlib import Path
from uuid import UUID, uuid4

import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.db.session import make_engine
from investiq.services.learning_seed import seed_curriculum
from investiq.services.market_ingestion import MarketIngestionService
from investiq.services.rewards_seed import seed_rewards
from tests.conftest import CapturedMailer, migrated_database
from tests.helpers import test_client as api_client
from tests.test_contest import verified
from tests.test_identity import csrf
from tests.test_portfolio import preview, save, submit, weights

SCRIPTS = str(Path("scripts").resolve())


@pytest_asyncio.fixture
async def sandbox(monkeypatch):
    monkeypatch.syspath_prepend(SCRIPTS)
    module = importlib.import_module("manual_sandbox")
    async with migrated_database() as url:
        settings = module.SandboxSettings(
            database_url=SecretStr(url),
            environment="test",
            auth_rate_limit=10000,
            csrf_rate_limit=10000,
            rate_limit_prefix=str(uuid4()),
            cors_origins=["http://localhost:5173", module.FRONTEND_ORIGIN],
            frontend_url=module.FRONTEND_ORIGIN,
        )
        engine = make_engine(settings)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            await MarketIngestionService(factory, settings).seed_fixtures()
            await seed_curriculum(factory, settings)
            await seed_rewards(factory, settings)
        finally:
            await engine.dispose()
        app = module.application(settings, "test-control-token", CapturedMailer())
        yield module, app


def control_headers():
    return {"Origin": "http://127.0.0.1:8082", "X-Sandbox-Token": "test-control-token"}


async def test_sandbox_admin_frontend_schedule_submission_and_clocked_final_results(sandbox):
    module, app = sandbox
    async with api_client(app, base_url=module.API_ORIGIN) as client:
        user = await verified(client, app.state.identity.mailer)
        assert "investiq_manual_sandbox_session" in client.cookies
        assert "investiq_dev_session" not in client.cookies
        promoted = await client.post(
            "/__sandbox__/promote", json={"email": user["email"]}, headers=control_headers()
        )
        assert promoted.status_code == 200, promoted.text
        assert (await client.get("/api/v1/me")).json()["role"] == "admin"
        data = (await client.get("/api/v1/contest-template")).json()
        assert data["starts_at"].startswith("2026-10-15T03:45")
        assert data["ends_at"].startswith("2026-10-16T10:00")
        data["visibility"] = "public"
        created = await client.post(
            "/api/v1/admin/contests",
            json=data,
            headers={**await csrf(client), "Idempotency-Key": str(uuid4())},
        )
        assert created.status_code == 201, created.text
        contest = created.json()
        path = "/api/v1/contests/" + contest["id"]
        assert (
            await client.post(
                path + "/transitions", json={"action": "publish"}, headers=await csrf(client)
            )
        ).status_code == 200
        assert (await client.post(path + "/entries", headers=await csrf(client))).status_code == 200
        await save(client, path, weights(data))
        reviewed = await preview(client, path, 1)
        assert (await submit(client, path, reviewed)).status_code == 201
        assert (await client.get(path + "/leaderboard")).json()["items"] == []
        for stage in ["started", "close"]:
            response = await client.post(
                "/__sandbox__/advance", json={"stage": stage}, headers=control_headers()
            )
            assert response.status_code == 200, response.text
            assert (await client.get(path + "/leaderboard")).json()["items"] == []
        await client.post(
            "/__sandbox__/advance", json={"stage": "valued"}, headers=control_headers()
        )
        board = (await client.get(path + "/leaderboard")).json()
        assert board["session_date"] == "2026-10-15" and board["items"][0]["rank"] == 1
        first_value = board["items"][0]["total_value"]
        await client.post(
            "/__sandbox__/advance", json={"stage": "final"}, headers=control_headers()
        )
        board = (await client.get(path + "/leaderboard")).json()
        assert board["is_final"] and board["contest_status"] == "completed"
        assert board["session_date"] == "2026-10-16"
        assert board["items"][0]["total_value"] != first_value
        assert (
            await client.post(
                "/__sandbox__/advance", json={"stage": "entry"}, headers=control_headers()
            )
        ).status_code == 409
        assert UUID(contest["id"])


async def test_sandbox_controls_reject_missing_token_cross_origin_and_non_loopback_host(sandbox):
    module, app = sandbox
    async with api_client(app, base_url=module.API_ORIGIN) as client:
        response = await client.get("/__sandbox__")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        for headers in [
            {},
            {"Origin": module.API_ORIGIN},
            {**control_headers(), "Origin": "https://attacker.invalid"},
        ]:
            assert (
                await client.post("/__sandbox__/advance", json={"stage": "final"}, headers=headers)
            ).status_code == 403
        assert (
            await client.get("/__sandbox__", headers={"Host": "attacker.invalid"})
        ).status_code == 404
        assert (
            await client.post(
                "/__sandbox__/advance", json={"stage": "unknown"}, headers=control_headers()
            )
        ).status_code == 422
        assert (await client.get("/__sandbox__/state")).json()["stage"] == "entry"
        assert (
            await client.post(
                "/__sandbox__/promote",
                json={"email": "unknown@example.com"},
                headers=control_headers(),
            )
        ).status_code == 422
