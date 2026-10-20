from uuid import UUID

import pytest
from pydantic import BaseModel

from investiq.api import health
from investiq.core.config import Settings
from investiq.main import create_app
from tests.helpers import test_client as api_client


async def test_liveness_and_request_ids() -> None:
    async with api_client(create_app(Settings(_env_file=None))) as client:
        first = await client.get("/api/v1/health/live", headers={"X-Request-ID": "untrusted"})
        second = await client.get("/api/v1/health/live")
        assert first.status_code == 200
        assert first.json() == {"status": "ok"}
        UUID(first.headers["x-request-id"])
        assert first.headers["x-request-id"] != second.headers["x-request-id"]
        assert first.headers["x-content-type-options"] == "nosniff"


async def test_errors_do_not_leak_inputs_or_exceptions() -> None:
    class Input(BaseModel):
        password: int

    app = create_app(Settings(_env_file=None))

    @app.post("/validation-probe")
    async def validation_probe(body: Input) -> dict[str, int]:
        return {"value": body.password}

    @app.get("/failure-probe")
    async def failure_probe() -> None:
        raise RuntimeError("SECRET_DATABASE_PASSWORD")

    async with api_client(app) as client:
        invalid = await client.post("/validation-probe", json={"password": "SECRET_USER_PASSWORD"})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "validation_error"
        assert "SECRET_USER_PASSWORD" not in invalid.text
        missing = await client.get("/missing")
        assert missing.status_code == 404
        assert missing.json()["request_id"] == missing.headers["x-request-id"]
        failed = await client.get("/failure-probe", headers={"Origin": "http://localhost:5173"})
        assert failed.status_code == 500
        assert failed.json()["error"]["code"] == "internal_error"
        assert "SECRET_DATABASE_PASSWORD" not in failed.text
        assert failed.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_cors_only_allows_configured_origins() -> None:
    async with api_client(create_app(Settings(_env_file=None))) as client:
        allowed = await client.options(
            "/api/v1/health/live",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-CSRF-Token",
            },
        )
        denied = await client.get("/api/v1/health/live", headers={"Origin": "https://evil.example"})
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-credentials"] == "true"
        assert "access-control-allow-origin" not in denied.headers


@pytest.mark.parametrize("failed_dependency", ["postgresql", "redis"])
async def test_readiness_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch, failed_dependency: str
) -> None:
    async def success(resource: object) -> None:
        pass

    async def failure(resource: object) -> None:
        raise RuntimeError("SECRET_CONNECTION_STRING")

    monkeypatch.setattr(
        health, "check_database", failure if failed_dependency == "postgresql" else success
    )
    monkeypatch.setattr(health, "check_redis", failure if failed_dependency == "redis" else success)
    async with api_client(create_app(Settings(_env_file=None))) as client:
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"][failed_dependency] == "unavailable"
        assert "SECRET_CONNECTION_STRING" not in response.text


async def test_readiness_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def stalled(resource: object) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(health, "check_database", stalled)
    monkeypatch.setattr(health, "check_redis", stalled)
    async with api_client(
        create_app(Settings(_env_file=None, dependency_timeout_seconds=0.02))
    ) as client:
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"] == {"postgresql": "unavailable", "redis": "unavailable"}


async def test_production_disables_docs() -> None:
    async with api_client(create_app(Settings(_env_file=None, environment="production"))) as client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404
