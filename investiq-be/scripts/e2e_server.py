"""Disposable PostgreSQL-backed API used only by the frontend browser suite."""

import asyncio
import os
import signal
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import uvicorn
from fastapi import HTTPException, Request
from pydantic import AwareDatetime, BaseModel, SecretStr
from sqlalchemy import update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.adapters.coach import CoachGeneration
from investiq.adapters.martin import MartinGeneration
from investiq.ai.workflow import setup_checkpoints, sweep
from investiq.core.config import Settings
from investiq.db.session import make_engine
from investiq.main import create_app
from investiq.models.identity import User
from investiq.schemas.coach import CoachEvidence, CoachPlan
from investiq.schemas.martin import MartinPlan
from investiq.services.learning_seed import seed_curriculum
from investiq.services.market_ingestion import MarketIngestionService
from investiq.services.rewards_seed import seed_rewards


class BrowserMartin:
    async def generate(self, question, sources, history):
        personal = any(word in question.lower().split() for word in ["i", "my", "mine"])
        kinds = {"performance", "status"} if personal else {"lesson"}
        source = next((s for s in sources if s.kind in kinds), sources[0])
        return MartinGeneration(
            MartinPlan(
                intent="personal_assessment" if personal else "explanation",
                reply="Your allocation needs a review of concentration and sector spread."
                if personal
                else (
                    "Diversification spreads exposure across holdings. "
                    "Its benefits depend on the assets."
                ),
                source_ids=[source.id],
                follow_up="Which part would you like to explore?",
            ),
            100,
            20,
            10,
        )


class BrowserCoach:
    async def generate(self, evidence: CoachEvidence) -> CoachGeneration:
        return CoachGeneration(
            CoachPlan(
                focus_fact_ids=["return", "benchmark"],
                worked_fact_ids=[f.id for f in evidence.facts if f.category == "worked"],
                review_fact_ids=["allocation-review"],
                lesson_version_ids=[str(evidence.lessons[0].version_id)],
                reflection="evidence",
            ),
            100,
            50,
            10,
        )


class BrowserClock(BaseModel):
    at: AwareDatetime


class BrowserTestServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        # Uvicorn normally re-raises SIGTERM after shutdown, before our DB teardown can run.
        # This test harness must return normally so its outer finally removes the database.
        previous = {
            sig: signal.signal(sig, self.handle_exit) for sig in (signal.SIGTERM, signal.SIGINT)
        }
        try:
            yield
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


async def main() -> None:
    base = make_url(Settings().database_url.get_secret_value())
    database = "investiq_browser_test_" + uuid4().hex
    admin_url = base.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    test_url = base.set(database=database).render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
    finally:
        await admin.close()
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
            env={**os.environ, "INVESTIQ_DATABASE_URL": test_url},
        )
        if await process.wait() != 0:
            raise RuntimeError("Browser test migration failed")
        settings = Settings(
            database_url=SecretStr(test_url),
            environment="test",
            market_data_mode="fixture",
            auth_rate_limit=10000,
            csrf_rate_limit=10000,
            ai_request_limit=1000,
            martin_request_limit=1000,
            ollama_model="browser-test-only",
            rate_limit_prefix=f"investiq:browser:{uuid4()}",
            frontend_url="http://127.0.0.1:5174",
            cors_origins=["http://127.0.0.1:5174", "http://admin.localhost:5174"],
        )
        engine = make_engine(settings)
        try:
            await MarketIngestionService(
                async_sessionmaker(engine, expire_on_commit=False), settings
            ).seed_fixtures()
            await seed_curriculum(async_sessionmaker(engine, expire_on_commit=False), settings)
            await seed_rewards(async_sessionmaker(engine, expire_on_commit=False), settings)
            await setup_checkpoints(settings)
        finally:
            await engine.dispose()
        clock = [datetime(2026, 10, 18, 12, tzinfo=UTC)]
        application = create_app(
            settings,
            market_clock=lambda: clock[0],
            contest_clock=lambda: clock[0],
            coach_provider=BrowserCoach(),
            martin_provider=BrowserMartin(),
        )

        def harness_only(request: Request) -> None:
            if (
                request.headers.get("x-investiq-browser-test") != "local-disposable-only"
                or request.client is None
                or request.client.host not in {"127.0.0.1", "::1"}
            ):
                raise HTTPException(404)

        # Test harness only: this script is not shipped in the API image or imported by main.py.
        @application.post("/__browser__/clock", include_in_schema=False)
        async def browser_clock(data: BrowserClock, request: Request) -> dict[str, str]:
            harness_only(request)
            clock[0] = data.at
            return {"current_time": data.at.isoformat()}

        @application.post("/__browser__/admin/{identifier}", include_in_schema=False)
        async def browser_admin(identifier: UUID, request: Request) -> dict[str, str]:
            harness_only(request)
            async with application.state.sessions() as db, db.begin():
                await db.execute(update(User).where(User.id == identifier).values(role="admin"))
            return {"status": "test_admin_ready"}

        @application.post("/__browser__/value/{identifier}", include_in_schema=False)
        async def browser_value(identifier: UUID, request: Request) -> object:
            harness_only(request)
            return await application.state.valuations.evaluate(identifier)

        @application.post("/__browser__/martin-work", include_in_schema=False)
        async def browser_martin_work(request: Request) -> object:
            harness_only(request)
            return await application.state.martin.sweep()

        @application.post("/__browser__/coach-work", include_in_schema=False)
        async def browser_coach_work(request: Request) -> object:
            harness_only(request)
            return await sweep(application.state.coach)

        await BrowserTestServer(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=8081,
                access_log=False,
            )
        ).serve()
    finally:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        finally:
            await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
