import asyncio
import time
from datetime import timedelta
from decimal import Decimal
from typing import Any, TypedDict
from uuid import UUID, uuid4

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy import and_, func, or_, select

from investiq.adapters.coach import LangChainCoach
from investiq.ai.evidence import validate_plan
from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.core.security import now
from investiq.db.session import postgres_url
from investiq.models.coach import CoachAttempt, CoachJob
from investiq.schemas.coach import CoachEvidence, CoachPlan
from investiq.services.coach import CoachService


class CoachState(TypedDict, total=False):
    job_id: str
    evidence: dict[str, Any]
    plan: dict[str, Any]
    report: dict[str, Any]


def checkpoint_url(settings: Settings) -> str:
    return postgres_url(settings)


async def setup_checkpoints(settings: Settings) -> None:
    async with await AsyncConnection.connect(
        checkpoint_url(settings),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options="-csearch_path=investiq_ai",
    ) as conn:
        saver = AsyncPostgresSaver(conn)
        await saver.setup()


def workflow(
    service: CoachService,
    saver: AsyncPostgresSaver,
    identifier: UUID,
    token: UUID,
    number: int,
    provider: str,
    model: str,
) -> Any:
    async def authorized_evidence() -> CoachEvidence:
        async with service.factory() as db, db.begin():
            job = await db.get(CoachJob, identifier)
            if not job or job.status != "running" or job.lease_token != token:
                raise AppError(409, "lease_lost", "Report attempt no longer owns this job")
            return await service.worker_evidence(db, job)

    async def authorize(state: CoachState) -> dict[str, Any]:
        await authorized_evidence()
        return {"job_id": str(identifier)}

    async def evidence_node(state: CoachState) -> dict[str, Any]:
        return {"evidence": (await authorized_evidence()).model_dump(mode="json")}

    async def retrieve(state: CoachState) -> dict[str, Any]:
        evidence = CoachEvidence.model_validate(state["evidence"])
        if not evidence.lessons:
            raise AppError(
                503, "coach_lessons_unavailable", "Approved lesson citations are unavailable"
            )
        return {}

    async def generate(state: CoachState) -> dict[str, Any]:
        from investiq.services.ai_budget import reserve_generation

        # Recheck on resumes too: authorization nodes may already be checkpointed.
        await authorized_evidence()
        evidence = CoachEvidence.model_validate(state["evidence"])
        adapter = service.provider or LangChainCoach(service.settings, provider, model)
        await reserve_generation(service.identity)
        result = await adapter.generate(evidence)
        async with service.factory() as db, db.begin():
            attempt = await db.get(CoachAttempt, (identifier, number))
            assert attempt is not None
            attempt.input_tokens, attempt.output_tokens, attempt.latency_ms = (
                result.input_tokens,
                result.output_tokens,
                result.latency_ms,
            )
            attempt.estimated_cost_usd = Decimal(0) if provider == "ollama" else None
        # Validate inside generation before it becomes a reusable successful checkpoint.
        validate_plan(evidence, result.plan)
        return {"plan": result.plan.model_dump(mode="json")}

    async def validate(state: CoachState) -> dict[str, Any]:
        body = validate_plan(
            CoachEvidence.model_validate(state["evidence"]), CoachPlan.model_validate(state["plan"])
        )
        return {"report": body.model_dump(mode="json")}

    async def persist(state: CoachState) -> dict[str, Any]:
        from investiq.schemas.coach import ReportBody

        await service.save_report(identifier, token, ReportBody.model_validate(state["report"]))
        return {}

    graph = StateGraph(CoachState)
    for name, node in [
        ("authorize", authorize),
        ("load_evidence", evidence_node),
        ("retrieve", retrieve),
        ("generate", generate),
        ("validate", validate),
        ("persist", persist),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "authorize")
    for left, right in [
        ("authorize", "load_evidence"),
        ("load_evidence", "retrieve"),
        ("retrieve", "generate"),
        ("generate", "validate"),
        ("validate", "persist"),
    ]:
        graph.add_edge(left, right)
    graph.add_edge("persist", END)
    return graph.compile(checkpointer=saver)


async def run_job(
    service: CoachService, identifier: UUID, token: UUID, number: int, provider: str, model: str
) -> None:
    config = service.configuration()
    if not config.enabled or provider != config.provider or model != config.model:
        raise AppError(
            503,
            "provider_configuration_changed",
            "Request a new report with the current AI provider configuration",
        )
    async with service.factory() as db, db.begin():
        job = await db.get(CoachJob, identifier)
        assert job is not None
        await service.worker_evidence(db, job)
        owner = job.user_id
    async with await AsyncConnection.connect(
        checkpoint_url(service.settings),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options="-csearch_path=investiq_ai",
    ) as conn:
        graph = workflow(
            service, AsyncPostgresSaver(conn), identifier, token, number, provider, model
        )
        graph_config = {
            "configurable": {"thread_id": f"coach:{owner}:{identifier}"},
            "recursion_limit": 12,
        }
        previous = await graph.aget_state(graph_config)
        await graph.ainvoke(None if previous.values else {"job_id": str(identifier)}, graph_config)


async def sweep(service: CoachService, identifier: UUID | None = None) -> dict[str, int]:
    """Durable DB queue; one AI generation leaves the second Celery slot for valuation."""
    async with service.factory() as guard, guard.begin():
        if not await guard.scalar(select(func.pg_try_advisory_xact_lock(742020))):
            return {"processed": 0}
        async with service.factory() as db, db.begin():
            expired = (
                await db.scalars(
                    select(CoachJob)
                    .where(
                        CoachJob.status == "running",
                        CoachJob.leased_until < now(),
                        CoachJob.attempts >= 3,
                        *([CoachJob.id == identifier] if identifier else []),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(100)
                )
            ).all()
            for old in expired:
                old.status, old.error_code = "failed", "worker_lost"
                old.lease_token, old.leased_until = None, None
                old.updated_at = now()
                previous_attempt = await db.get(CoachAttempt, (old.id, old.attempts))
                if previous_attempt:
                    previous_attempt.error_code = "worker_lost"
            job = await db.scalar(
                select(CoachJob)
                .where(
                    CoachJob.attempts < 3,
                    *([CoachJob.id == identifier] if identifier else []),
                    or_(
                        and_(
                            CoachJob.status.in_(["queued", "retry"]),
                            CoachJob.next_attempt_at <= now(),
                        ),
                        and_(CoachJob.status == "running", CoachJob.leased_until < now()),
                    ),
                )
                .order_by(CoachJob.created_at, CoachJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if not job:
                return {"processed": 0}
            if job.status == "running":
                previous_attempt = await db.get(CoachAttempt, (job.id, job.attempts))
                if previous_attempt:
                    previous_attempt.error_code = "worker_lost"
            job.status, job.error_code = "running", None
            job.attempts += 1
            job.lease_token, job.leased_until, job.updated_at = (
                uuid4(),
                now() + timedelta(seconds=120),
                now(),
            )
            db.add(CoachAttempt(job_id=job.id, number=job.attempts))
            identifier, token, number, provider, model = (
                job.id,
                job.lease_token,
                job.attempts,
                job.provider,
                job.model,
            )
        started = time.perf_counter()
        try:
            async with asyncio.timeout(75):
                await run_job(service, identifier, token, number, provider, model)
        except Exception as exc:
            code = (
                exc.code
                if isinstance(exc, AppError)
                else "job_timeout"
                if isinstance(exc, TimeoutError)
                else "coach_processing_failed"
            )
            async with service.factory() as db, db.begin():
                job = await db.get(CoachJob, identifier, with_for_update=True)
                if job and job.status == "running" and job.lease_token == token:
                    terminal = number >= 3 or code in {
                        "authorization_revoked",
                        "evidence_invalid",
                        "provider_configuration_changed",
                        "daily_ai_limit",
                    }
                    job.status, job.error_code = "failed" if terminal else "retry", code
                    job.next_attempt_at, job.updated_at = (
                        now() + timedelta(seconds=10 * 2 ** (number - 1)),
                        now(),
                    )
                    job.lease_token, job.leased_until = None, None
                    attempt = await db.get(CoachAttempt, (identifier, number))
                    assert attempt is not None
                    attempt.error_code = code
                    if attempt.latency_ms is None:
                        attempt.latency_ms = int((time.perf_counter() - started) * 1000)
        return {"processed": 1}
