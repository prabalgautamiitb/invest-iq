"""Disposable, loopback-only frontend sandbox. Never imported by the production application."""

import asyncio
import json
import os
import secrets
import signal
import socket
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import asyncpg
import uvicorn
from e2e_server import BrowserTestServer
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, EmailStr, SecretStr
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.adapters.mail import Mailer
from investiq.ai.workflow import setup_checkpoints
from investiq.ai.workflow import sweep as coach_sweep
from investiq.core.config import Settings
from investiq.db.session import make_engine
from investiq.main import create_app
from investiq.models.identity import AuditEvent, User
from investiq.schemas.contest import ContestInput
from investiq.services.learning_seed import seed_curriculum
from investiq.services.market_ingestion import MarketIngestionService
from investiq.services.rewards_seed import seed_rewards

API_ORIGIN = "http://127.0.0.1:8082"
FRONTEND_ORIGIN = "http://127.0.0.1:5175"
STAGES = [
    (
        "entry",
        "Entry open — create contests and confirm portfolios",
        datetime(2026, 10, 14, 13, tzinfo=UTC),
    ),
    ("started", "Entry locked — contest running", datetime(2026, 10, 15, 3, 45, tzinfo=UTC)),
    (
        "close",
        "First session closed — prices await publication",
        datetime(2026, 10, 15, 10, tzinfo=UTC),
    ),
    ("valued", "First valuation — standings available", datetime(2026, 10, 15, 13, tzinfo=UTC)),
    ("final", "Final valuation — contest completed", datetime(2026, 10, 16, 13, tzinfo=UTC)),
]


class SandboxSettings(Settings):
    @property
    def cookie_name(self) -> str:
        # Cookies are shared across ports: isolate this browser session from the normal application.
        return "investiq_manual_sandbox_session"


class StageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: str


class PromoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


def application(settings: Settings, token: str, mailer: Mailer | None = None) -> FastAPI:
    clock = [STAGES[0][2]]
    index = [0]
    control_lock = asyncio.Lock()
    app = create_app(
        settings, mailer=mailer, market_clock=lambda: clock[0], contest_clock=lambda: clock[0]
    )

    def local(request: Request, *, mutation: bool = False) -> None:
        if (
            request.client is None
            or request.client.host not in {"127.0.0.1", "::1"}
            or request.headers.get("host") != "127.0.0.1:8082"
        ):
            raise HTTPException(404)
        if mutation and (
            request.headers.get("origin") != API_ORIGIN
            or request.headers.get("sec-fetch-site") == "cross-site"
            or not secrets.compare_digest(request.headers.get("x-sandbox-token", ""), token)
        ):
            raise HTTPException(403, "Open the local sandbox control page to use these controls")

    # Suggest fixed fixture dates only in this disposable application.
    @app.get("/api/v1/contest-template", response_model=ContestInput)
    async def template() -> ContestInput:
        result = await app.state.contests.template()
        return result.model_copy(
            update={
                "name": "Sandbox public simulation",
                "entry_opens_at": STAGES[0][2],
                "entry_closes_at": datetime(2026, 10, 15, 3, 40, tzinfo=UTC),
                "starts_at": STAGES[1][2],
                "ends_at": datetime(2026, 10, 16, 10, tzinfo=UTC),
            }
        )

    app.router.routes.insert(0, app.router.routes.pop())

    @app.get("/__sandbox__", response_class=HTMLResponse, include_in_schema=False)
    async def panel(request: Request) -> HTMLResponse:
        local(request)
        html = PANEL.replace("__TOKEN__", json.dumps(token)).replace(
            "__STAGES__",
            json.dumps([{"id": identifier, "label": label} for identifier, label, _ in STAGES]),
        )
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'self'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'",
            },
        )

    @app.get("/__sandbox__/state", include_in_schema=False)
    async def state(request: Request) -> dict[str, object]:
        local(request)
        return {"stage": STAGES[index[0]][0], "stage_index": index[0], "time": clock[0].isoformat()}

    @app.post("/__sandbox__/advance", include_in_schema=False)
    async def advance(data: StageInput, request: Request) -> dict[str, object]:
        local(request, mutation=True)
        target = next((i for i, stage in enumerate(STAGES) if stage[0] == data.stage), None)
        if target is None:
            raise HTTPException(422, "Select a listed simulation stage")
        async with control_lock:
            if target < index[0]:
                raise HTTPException(
                    409, "Published results are immutable. Restart this sandbox for a fresh run."
                )
            clock[0], index[0] = STAGES[target][2], target
            # Run the actual valuation service; never inject ranks or calculated values.
            outcome = await app.state.valuations.sweep()
            return {"stage": data.stage, "time": clock[0].isoformat(), "valuation": outcome}

    @app.post("/__sandbox__/promote", include_in_schema=False)
    async def promote(data: PromoteInput, request: Request) -> dict[str, str]:
        local(request, mutation=True)
        async with app.state.sessions() as db, db.begin():
            user = await db.scalar(
                select(User).where(User.email == str(data.email).lower()).with_for_update()
            )
            if not user or not user.active or not user.email_verified_at:
                raise HTTPException(422, "Register and verify this account in the sandbox first")
            if user.role != "admin":
                user.role = "admin"
                db.add(
                    AuditEvent(
                        actor_id=user.id, action="sandbox.admin_promoted", resource_id=user.id
                    )
                )
        return {
            "message": "Sandbox admin enabled. Reload the frontend to refresh its account role."
        }

    @app.post("/__sandbox__/martin", include_in_schema=False)
    async def work_martin(request: Request) -> dict[str, int]:
        local(request, mutation=True)
        async with control_lock:
            result: dict[str, int] = await app.state.martin.sweep()
            return result

    @app.post("/__sandbox__/coach", include_in_schema=False)
    async def work_coach(request: Request) -> dict[str, int]:
        local(request, mutation=True)
        async with control_lock:
            # Real configured Ollama adapter; no browser-test mock or fabricated reports.
            return await coach_sweep(app.state.coach)

    return app


PANEL = Path(__file__).with_suffix(".html").read_text()


@asynccontextmanager
async def database() -> AsyncIterator[SandboxSettings]:
    base = make_url(Settings().database_url.get_secret_value())
    name = "investiq_manual_sandbox_" + uuid4().hex
    admin_url = base.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    url = base.set(database=name).render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
            env={**os.environ, "INVESTIQ_DATABASE_URL": url},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        if process.returncode:
            raise RuntimeError("Sandbox migration failed; verify the local PostgreSQL setup")
        settings = SandboxSettings(
            database_url=SecretStr(url),
            environment="development",
            auth_rate_limit=1000,
            csrf_rate_limit=1000,
            ai_request_limit=100,
            rate_limit_prefix="investiq:manual:" + uuid4().hex,
            public_contest_fixtures_enabled=False,
            market_data_mode="fixture",
            frontend_url=FRONTEND_ORIGIN,
            cors_origins=[FRONTEND_ORIGIN],
            smtp_host="127.0.0.1",
            smtp_port=1025,
            smtp_starttls=False,
            smtp_username="",
            smtp_password=SecretStr(""),
            ai_provider="ollama",
        )
        engine = make_engine(settings)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            await MarketIngestionService(factory, settings).seed_fixtures()
            await seed_curriculum(factory, settings)
            await seed_rewards(factory, settings)
            await setup_checkpoints(settings)
        finally:
            await engine.dispose()
        yield settings
    finally:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        finally:
            await admin.close()


async def main(backend: Path) -> None:
    # Resolve imports/migrations relative to the backend, regardless of the caller's directory.
    os.chdir(backend)
    for port in [8082, 5175]:
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", port))
            except OSError:
                raise RuntimeError(
                    f"Port {port} is already in use; stop the previous sandbox first"
                ) from None
    async with database() as settings:
        frontend = await asyncio.create_subprocess_exec(
            "npm",
            "run",
            "dev",
            "--",
            "--port",
            "5175",
            "--strictPort",
            cwd=backend.parent / "investiq-fe",
            env={**os.environ, "API_PROXY_TARGET": API_ORIGIN},
            start_new_session=True,
        )
        try:
            print(
                f"\nSandbox control page: {API_ORIGIN}/__sandbox__\n"
                f"Sandbox frontend: {FRONTEND_ORIGIN}\n"
                "Temporary data is deleted on Ctrl+C. Normal InvestIQ data is unaffected.\n",
                flush=True,
            )
            server = BrowserTestServer(
                uvicorn.Config(
                    application(settings, secrets.token_urlsafe(32)),
                    host="127.0.0.1",
                    port=8082,
                    access_log=False,
                )
            )

            async def monitor_frontend() -> None:
                await frontend.wait()
                server.should_exit = True

            monitor = asyncio.create_task(monitor_frontend())
            try:
                await server.serve()
            finally:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
        finally:
            if frontend.returncode is None:
                os.killpg(frontend.pid, signal.SIGTERM)
                await frontend.wait()


if __name__ == "__main__":
    asyncio.run(main(Path(__file__).resolve().parents[1]))
