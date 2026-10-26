import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from investiq.adapters.coach import CoachProvider
from investiq.ai.evidence import PROMPT_VERSION, build_evidence
from investiq.core.errors import AppError
from investiq.core.security import Principal, now
from investiq.models.coach import CoachAttempt, CoachJob, CoachReflection, CoachReport, CoachRequest
from investiq.models.contest import Contest, ContestMembership
from investiq.models.identity import AuditEvent, User
from investiq.models.learning import LessonVersion
from investiq.models.valuation import ValuationRecord, ValuationRun
from investiq.schemas.coach import (
    CoachEvidence,
    CoachJobOut,
    CoachSettingsOut,
    CreateCoachInput,
    JobPage,
    LessonEvidence,
    ReflectionInput,
    ReflectionOut,
    ReflectionPage,
    ReportBody,
    UsageOut,
)
from investiq.services.market import decode_cursor, encode_cursor, fingerprint
from investiq.services.valuation import ValuationService


def evidence_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class CoachService:
    def __init__(self, valuations: ValuationService, provider: CoachProvider | None = None) -> None:
        self.valuations, self.identity, self.factory = (
            valuations,
            valuations.contests.identity,
            valuations.factory,
        )
        self.settings, self.provider = self.identity.settings, provider

    def configuration(self) -> CoachSettingsOut:
        provider = self.settings.ai_provider
        model = self.settings.gemini_model if provider == "gemini" else self.settings.ollama_model
        enabled = (
            provider != "disabled"
            and bool(model)
            and (provider != "gemini" or bool(self.settings.gemini_api_key.get_secret_value()))
        )
        return CoachSettingsOut(
            enabled=enabled, provider=provider, model=model if enabled else "", max_attempts=3
        )

    async def source(
        self, db: AsyncSession, principal: Principal, contest_id: UUID
    ) -> CoachEvidence:
        user = await self.valuations.contests.actor(db, principal)
        contest = await self.valuations.contests.load(db, contest_id, user)
        member = await db.scalar(
            select(ContestMembership).where(
                ContestMembership.contest_id == contest.id, ContestMembership.user_id == user.id
            )
        )
        if not member:
            raise AppError(
                404, "performance_not_found", "Join this contest to view your own report evidence"
            )
        row = (
            await db.execute(
                select(ValuationRecord, ValuationRun)
                .join(ValuationRun, ValuationRun.id == ValuationRecord.run_id)
                .where(
                    ValuationRecord.membership_id == member.id, ValuationRun.status == "succeeded"
                )
                .order_by(ValuationRun.session_date.desc())
                .limit(1)
            )
        ).first()
        if not row:
            raise AppError(
                409,
                "coach_evidence_pending",
                "A confirmed portfolio and at least one published valuation are required "
                "before a coach report",
            )
        record, run = row
        return await self.record_evidence(db, record, run, contest)

    async def record_evidence(
        self, db: AsyncSession, record: ValuationRecord, run: ValuationRun, contest: Contest
    ) -> CoachEvidence:
        latest_run, _, current, final, _ = await self.valuations.board_state(db, contest)
        current = current and latest_run is not None and latest_run.id == run.id
        final = final and latest_run is not None and latest_run.id == run.id
        versions = (
            await db.scalars(
                select(LessonVersion)
                .where(LessonVersion.published_at <= now())
                .order_by(LessonVersion.version.desc(), LessonVersion.lesson_id)
            )
        ).all()
        latest: dict[UUID, LessonVersion] = {}
        for version in versions:
            if version.lesson_id not in latest:
                latest[version.lesson_id] = version
        # Published lessons only: no community, journal, answer keys or arbitrary web retrieval.
        lessons = [
            LessonEvidence(
                lesson_id=v.lesson_id,
                version_id=v.id,
                version=v.version,
                title=v.title,
                paragraphs=v.paragraphs,
            )
            for v in list(latest.values())[:12]
        ]
        return build_evidence(
            record,
            run,
            final=final,
            current=current,
            lessons=lessons,
            data_kind="yahoo"
            if await self.valuations.contests.data_kind(db, contest) == "yahoo"
            else "synthetic",
        )

    async def evidence(self, principal: Principal, contest_id: UUID) -> CoachEvidence:
        async with self.factory() as db, db.begin():
            return await self.source(db, principal, contest_id)

    async def output(self, db: AsyncSession, job: CoachJob) -> CoachJobOut:
        report = await db.get(CoachReport, job.id)
        evidence = CoachEvidence.model_validate(job.evidence)
        return CoachJobOut(
            id=job.id,
            contest_id=job.contest_id,
            session_date=evidence.session_date,
            status=job.status,
            provider=job.provider,
            model=job.model,
            prompt_version=job.prompt_version,
            evidence_hash=job.evidence_hash,
            generation=job.generation,
            attempts=job.attempts,
            error_code=job.error_code,
            created_at=job.created_at,
            updated_at=job.updated_at,
            next_attempt_at=job.next_attempt_at,
            evidence=evidence,
            report=ReportBody.model_validate(report.body) if report else None,
        )

    async def create(self, principal: Principal, data: CreateCoachInput, key: UUID) -> CoachJobOut:
        digest = fingerprint(data.model_dump(mode="json"))
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            if not user.email_verified_at:
                raise AppError(
                    403, "verification_required", "Verify your email to request a coach report"
                )
            request = await db.get(CoachRequest, (user.id, key))
            if request:
                if request.request_hash != digest:
                    raise AppError(
                        409,
                        "idempotency_conflict",
                        "This request key was already used for another contest",
                    )
                job = await db.get(CoachJob, request.job_id)
                assert job is not None
                return await self.output(db, job)
            config = self.configuration()
            if not config.enabled:
                raise AppError(
                    503,
                    "coach_disabled",
                    "AI generation is unavailable; deterministic report evidence is still "
                    "accessible",
                )
            evidence = await self.source(db, principal, data.contest_id)
            if not evidence.lessons:
                raise AppError(
                    503,
                    "coach_lessons_unavailable",
                    "Initialize the approved learning curriculum before requesting an AI report",
                )
            job = await db.scalar(
                select(CoachJob)
                .where(
                    CoachJob.user_id == user.id,
                    CoachJob.record_id == evidence.record_id,
                    CoachJob.provider == config.provider,
                    CoachJob.model == config.model,
                    CoachJob.prompt_version == PROMPT_VERSION,
                )
                .order_by(CoachJob.generation.desc())
                .limit(1)
            )
            generation = job.generation + 1 if job and job.status == "failed" else 1
            if job and job.status == "failed":
                job = None
            if not job:
                active = await db.scalar(
                    select(func.count())
                    .select_from(CoachJob)
                    .where(
                        CoachJob.user_id == user.id,
                        CoachJob.status.in_(["queued", "running", "retry"]),
                    )
                )
                if active:
                    raise AppError(
                        409,
                        "coach_job_active",
                        "Wait for your current coach request to finish before starting another",
                    )
                payload = evidence.model_dump(mode="json")
                job = CoachJob(
                    user_id=user.id,
                    generation=generation,
                    contest_id=data.contest_id,
                    record_id=evidence.record_id,
                    provider=config.provider,
                    model=config.model,
                    prompt_version=PROMPT_VERSION,
                    evidence_hash=evidence_hash(payload),
                    evidence=payload,
                )
                db.add(job)
                await db.flush()
                db.add(AuditEvent(actor_id=user.id, action="coach.request", resource_id=job.id))
            db.add(CoachRequest(user_id=user.id, key=key, job_id=job.id, request_hash=digest))
            await db.flush()
            return await self.output(db, job)

    async def own_job(self, db: AsyncSession, principal: Principal, identifier: UUID) -> CoachJob:
        user = await self.identity.authenticated_user(db, principal)
        job = await db.scalar(
            select(CoachJob).where(CoachJob.id == identifier, CoachJob.user_id == user.id)
        )
        if not job:
            raise AppError(404, "coach_job_not_found", "Coach report not found")
        return job

    async def get(self, principal: Principal, identifier: UUID) -> CoachJobOut:
        async with self.factory() as db, db.begin():
            return await self.output(db, await self.own_job(db, principal, identifier))

    async def history(
        self, principal: Principal, contest_id: UUID | None, cursor: str | None, limit: int
    ) -> JobPage:
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            query = select(CoachJob).where(CoachJob.user_id == user.id)
            if contest_id:
                query = query.where(CoachJob.contest_id == contest_id)
            context = fingerprint({"coach_history": str(user.id), "contest": str(contest_id)})
            if cursor:
                value, identifier = decode_cursor(cursor, context)
                query = query.where(
                    tuple_(CoachJob.created_at, CoachJob.id)
                    < tuple_(self.cursor_time(value), identifier)
                )
            rows = list(
                (
                    await db.scalars(
                        query.order_by(CoachJob.created_at.desc(), CoachJob.id.desc()).limit(
                            limit + 1
                        )
                    )
                ).all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            return JobPage(
                items=[await self.output(db, row) for row in rows],
                next_cursor=encode_cursor(rows[-1].created_at.isoformat(), rows[-1].id, context)
                if more
                else None,
            )

    @staticmethod
    def cursor_time(value: str) -> datetime:
        try:
            result = datetime.fromisoformat(value)
            if result.tzinfo is None:
                raise ValueError
            return result
        except ValueError:
            raise AppError(422, "invalid_cursor", "Invalid coach history cursor") from None

    async def usage(self, principal: Principal, identifier: UUID) -> list[UsageOut]:
        async with self.factory() as db, db.begin():
            job = await self.own_job(db, principal, identifier)
            rows = (
                await db.scalars(
                    select(CoachAttempt)
                    .where(CoachAttempt.job_id == job.id)
                    .order_by(CoachAttempt.number)
                )
            ).all()
            return [
                UsageOut(
                    attempt=r.number,
                    provider=job.provider,
                    model=job.model,
                    input_tokens=r.input_tokens,
                    output_tokens=r.output_tokens,
                    latency_ms=r.latency_ms,
                    estimated_cost_usd=r.estimated_cost_usd,
                    error_code=r.error_code,
                )
                for r in rows
            ]

    async def worker_evidence(self, db: AsyncSession, job: CoachJob) -> CoachEvidence:
        user = await db.get(User, job.user_id)
        row = (
            await db.execute(
                select(ValuationRecord, ValuationRun, ContestMembership)
                .join(ValuationRun, ValuationRun.id == ValuationRecord.run_id)
                .join(ContestMembership, ContestMembership.id == ValuationRecord.membership_id)
                .where(
                    ValuationRecord.id == job.record_id,
                    ContestMembership.user_id == job.user_id,
                    ContestMembership.contest_id == job.contest_id,
                    ValuationRun.contest_id == job.contest_id,
                    ValuationRun.status == "succeeded",
                )
            )
        ).first()
        if not user or not user.active or not user.email_verified_at or not row:
            raise AppError(403, "authorization_revoked", "The report owner is no longer authorized")
        if evidence_hash(job.evidence) != job.evidence_hash:
            raise AppError(409, "evidence_invalid", "Stored evidence failed validation")
        return CoachEvidence.model_validate(job.evidence)

    async def save_report(self, identifier: UUID, token: UUID, body: ReportBody) -> None:
        async with self.factory() as db, db.begin():
            job = await db.scalar(
                select(CoachJob).where(CoachJob.id == identifier).with_for_update()
            )
            if not job or job.status != "running" or job.lease_token != token:
                raise AppError(409, "lease_lost", "This report attempt no longer owns the job")
            await self.worker_evidence(db, job)
            existing = await db.get(CoachReport, job.id)
            if not existing:
                db.add(
                    CoachReport(
                        job_id=job.id, user_id=job.user_id, body=body.model_dump(mode="json")
                    )
                )
                db.add(
                    AuditEvent(
                        actor_id=job.user_id, action="coach.report_saved", resource_id=job.id
                    )
                )
            job.status, job.error_code = "succeeded", None
            job.lease_token, job.leased_until = None, None
            job.updated_at = now()

    async def reflect(
        self, principal: Principal, data: ReflectionInput, key: UUID
    ) -> ReflectionOut:
        async with self.factory() as db, db.begin():
            user = await self.valuations.contests.actor(db, principal)
            member = await db.scalar(
                select(ContestMembership).where(
                    ContestMembership.user_id == user.id,
                    ContestMembership.contest_id == data.contest_id,
                )
            )
            if not member:
                raise AppError(
                    404, "performance_not_found", "Join this contest before saving a reflection"
                )
            old = await db.scalar(
                select(CoachReflection).where(
                    CoachReflection.user_id == user.id, CoachReflection.request_key == key
                )
            )
            if old:
                if old.body != data.body or old.contest_id != data.contest_id:
                    raise AppError(
                        409,
                        "idempotency_conflict",
                        "This request key was used for another reflection",
                    )
                return ReflectionOut.model_validate(old)
            row = CoachReflection(
                user_id=user.id, contest_id=data.contest_id, request_key=key, body=data.body
            )
            db.add(row)
            await db.flush()
            return ReflectionOut.model_validate(row)

    async def reflections(
        self, principal: Principal, contest_id: UUID, cursor: str | None, limit: int
    ) -> ReflectionPage:
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            query = select(CoachReflection).where(
                CoachReflection.user_id == user.id, CoachReflection.contest_id == contest_id
            )
            context = fingerprint({"reflections": str(user.id), "contest": str(contest_id)})
            if cursor:
                value, identifier = decode_cursor(cursor, context)
                query = query.where(
                    tuple_(CoachReflection.created_at, CoachReflection.id)
                    < tuple_(self.cursor_time(value), identifier)
                )
            rows = list(
                (
                    await db.scalars(
                        query.order_by(
                            CoachReflection.created_at.desc(), CoachReflection.id.desc()
                        ).limit(limit + 1)
                    )
                ).all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            return ReflectionPage(
                items=[ReflectionOut.model_validate(row) for row in rows],
                next_cursor=encode_cursor(rows[-1].created_at.isoformat(), rows[-1].id, context)
                if more
                else None,
            )
