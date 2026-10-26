"""Lifetime overview from each contest's latest close and its last value-changing AI report."""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import aliased

from investiq.ai.evidence import PROMPT_VERSION
from investiq.analytics.investor_habits import assess_habits
from investiq.core.security import Principal, now
from investiq.models.coach import CoachJob, CoachReport
from investiq.models.contest import Contest, ContestMembership
from investiq.models.identity import AuditEvent, User
from investiq.models.learning import LessonVersion
from investiq.models.valuation import ValuationPrice, ValuationRecord, ValuationRun
from investiq.schemas.coach import CoachOverviewOut, ReportBody
from investiq.services.coach import evidence_hash

if TYPE_CHECKING:
    from investiq.services.coach import CoachService


def changed_sources(instant: datetime, user_id: UUID | None = None) -> Select[UUID, UUID, UUID]:
    """Find the most recent close that changed value, including A -> B -> A reversals."""
    query = (
        select(
            ValuationRecord.id.label("record_id"),
            ValuationRecord.membership_id,
            ContestMembership.user_id,
            ContestMembership.contest_id,
            ValuationRun.session_date,
            ValuationRecord.total_value,
            ValuationRecord.submission_id,
            func.lag(ValuationRecord.total_value)
            .over(partition_by=ValuationRecord.membership_id, order_by=ValuationRun.session_date)
            .label("previous_value"),
            func.lag(ValuationRecord.submission_id)
            .over(partition_by=ValuationRecord.membership_id, order_by=ValuationRun.session_date)
            .label("previous_submission"),
        )
        .join(ValuationRun, ValuationRun.id == ValuationRecord.run_id)
        .join(ContestMembership, ContestMembership.id == ValuationRecord.membership_id)
        .where(ValuationRun.status == "succeeded", ValuationRun.available_at <= instant)
    )
    if user_id is not None:
        query = query.where(ContestMembership.user_id == user_id)
    history = query.subquery()
    changed = (
        select(history)
        .where(
            or_(
                history.c.previous_value.is_(None),
                history.c.previous_value != history.c.total_value,
                history.c.previous_submission != history.c.submission_id,
            )
        )
        .ext(distinct_on(history.c.membership_id))
        .order_by(history.c.membership_id, history.c.session_date.desc())
        .subquery()
    )
    return select(changed.c.record_id, changed.c.user_id, changed.c.contest_id)


def compatible_sources(instant: datetime, user_id: UUID | None = None) -> Select[UUID, UUID]:
    """Reports from any close in the current unchanged-value streak remain usable."""
    targets = changed_sources(instant, user_id).subquery()
    anchor, anchor_run = aliased(ValuationRecord), aliased(ValuationRun)
    source, source_run = aliased(ValuationRecord), aliased(ValuationRun)
    return (
        select(targets.c.record_id.label("anchor_id"), source.id.label("record_id"))
        .select_from(targets)
        .join(anchor, anchor.id == targets.c.record_id)
        .join(anchor_run, anchor_run.id == anchor.run_id)
        .join(
            source,
            and_(
                source.membership_id == anchor.membership_id,
                source.total_value == anchor.total_value,
                source.submission_id == anchor.submission_id,
            ),
        )
        .join(source_run, source_run.id == source.run_id)
        .where(
            source_run.status == "succeeded",
            source_run.available_at <= instant,
            source_run.session_date >= anchor_run.session_date,
        )
    )


async def queue_daily(service: "CoachService", limit: int = 100) -> int:
    """Discover new closing values even when the user has not opened AI Insights."""
    config = service.configuration()
    if not config.enabled:
        return 0
    targets = changed_sources(service.valuations.clock()).subquery()
    compatible = compatible_sources(service.valuations.clock()).subquery()
    known_ids = (
        select(compatible.c.record_id)
        .where(compatible.c.anchor_id == targets.c.record_id)
        .correlate(targets)
    )
    async with service.factory() as db:
        candidates = (
            await db.execute(
                select(targets.c.record_id, targets.c.user_id, targets.c.contest_id)
                .join(User, User.id == targets.c.user_id)
                .where(
                    User.active.is_(True),
                    User.email_verified_at.is_not(None),
                    ~exists().where(
                        CoachJob.user_id == targets.c.user_id,
                        CoachJob.record_id.in_(known_ids),
                        CoachJob.provider == config.provider,
                        CoachJob.model == config.model,
                        CoachJob.prompt_version == PROMPT_VERSION,
                    ),
                )
                .order_by(targets.c.record_id)
                .limit(limit)
            )
        ).all()
    queued = 0
    for record_id, user_id, contest_id in candidates:
        async with service.factory() as db, db.begin():
            # Manual requests lock the same user, preventing duplicate or concurrent jobs.
            user = await db.scalar(
                select(User).where(User.id == user_id).with_for_update(skip_locked=True)
            )
            if not user or not user.active or not user.email_verified_at:
                continue
            existing = await db.scalar(
                select(CoachJob.id)
                .where(
                    CoachJob.user_id == user_id,
                    or_(
                        CoachJob.status.in_(["queued", "running", "retry"]),
                        and_(
                            CoachJob.record_id.in_(
                                select(compatible.c.record_id).where(
                                    compatible.c.anchor_id == record_id
                                )
                            ),
                            CoachJob.provider == config.provider,
                            CoachJob.model == config.model,
                            CoachJob.prompt_version == PROMPT_VERSION,
                        ),
                    ),
                )
                .limit(1)
            )
            if existing:
                continue
            record = await db.get(ValuationRecord, record_id)
            contest = await db.get(Contest, contest_id)
            assert record is not None and contest is not None
            run = await db.get(ValuationRun, record.run_id)
            assert run is not None
            evidence = await service.record_evidence(db, record, run, contest)
            if not evidence.lessons:
                continue
            payload = evidence.model_dump(mode="json")
            job = CoachJob(
                user_id=user_id,
                contest_id=contest_id,
                record_id=record_id,
                provider=config.provider,
                model=config.model,
                prompt_version=PROMPT_VERSION,
                evidence_hash=evidence_hash(payload),
                evidence=payload,
            )
            db.add(job)
            await db.flush()
            db.add(AuditEvent(actor_id=user_id, action="coach.daily_requested", resource_id=job.id))
            queued += 1
    return queued


async def overview(service: "CoachService", principal: Principal) -> CoachOverviewOut:
    async with service.factory() as db, db.begin():
        user = await service.identity.authenticated_user(db, principal)
        count = await db.scalar(
            select(func.count())
            .select_from(ContestMembership)
            .where(ContestMembership.user_id == user.id)
        )
        result = CoachOverviewOut(status="no_contests", contest_count=count or 0)
        if not count:
            return result
        result.status = "awaiting_results"
        rows = (
            await db.execute(
                select(ValuationRecord, ValuationRun, Contest)
                .join(ValuationRun, ValuationRun.id == ValuationRecord.run_id)
                .join(ContestMembership, ContestMembership.id == ValuationRecord.membership_id)
                .join(Contest, Contest.id == ContestMembership.contest_id)
                .where(
                    ContestMembership.user_id == user.id,
                    ValuationRun.status == "succeeded",
                    ValuationRun.available_at <= service.valuations.clock(),
                )
                .ext(distinct_on(ValuationRecord.membership_id))
                .order_by(ValuationRecord.membership_id, ValuationRun.session_date.desc())
            )
        ).all()
        if not rows:
            return result
        result.valued_contests = len(rows)
        result.completed_contests = sum(c.status == "completed" for _, _, c in rows)
        result.profitable_contests = sum(r.pnl > 0 for r, _, _ in rows)
        result.outperforming_contests = sum(r.excess_return_pct > 0 for r, _, _ in rows)
        result.latest_session_date = max(run.session_date for _, run, _ in rows)
        result.earliest_session_date = min(run.session_date for _, run, _ in rows)
        result.updated_at = max(run.evaluated_at for _, run, _ in rows)
        capital = sum((r.capital for r, _, _ in rows), Decimal(0))
        pnl = sum((r.pnl for r, _, _ in rows), Decimal(0))
        result.combined_return_pct = (pnl / capital * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        noun = "contest" if len(rows) == 1 else "contests"
        direction = (
            "up"
            if result.combined_return_pct > 0
            else "down"
            if result.combined_return_pct < 0
            else "close to unchanged"
        )
        change = f"{abs(result.combined_return_pct)}% " if result.combined_return_pct else ""
        result.summary = (
            f"Across {len(rows)} {noun}, your latest virtual portfolios are {direction} "
            f"{change}overall. This takes each contest's starting money into account."
        )
        frozen_sectors = (
            await db.execute(
                select(
                    ValuationPrice.run_id, ValuationPrice.instrument_id, ValuationPrice.sector_id
                ).where(ValuationPrice.run_id.in_([run.id for _, run, _ in rows]))
            )
        ).all()
        sector_map = {
            (run_id, str(instrument_id)): sector_id
            for run_id, instrument_id, sector_id in frozen_sectors
        }
        result.strengths, result.improvements, result.learning_stage, result.learning_summary = (
            assess_habits([(record, run, contest) for record, run, contest in rows], sector_map)
        )
        config = service.configuration()
        if not config.enabled or not await db.scalar(
            select(LessonVersion.id).where(LessonVersion.published_at <= now()).limit(1)
        ):
            result.status = "disabled"
            return result
        if not user.email_verified_at:
            result.status = "verification_required"
            return result
        source_rows = (await db.execute(changed_sources(service.valuations.clock(), user.id))).all()
        compatible_rows = (
            await db.execute(compatible_sources(service.valuations.clock(), user.id))
        ).all()
        source_to_anchor = {record_id: anchor_id for anchor_id, record_id in compatible_rows}
        record_ids = list(source_to_anchor)
        jobs = (
            await db.scalars(
                select(CoachJob)
                .where(
                    CoachJob.user_id == user.id,
                    CoachJob.record_id.in_(record_ids),
                    CoachJob.provider == config.provider,
                    CoachJob.model == config.model,
                    CoachJob.prompt_version == PROMPT_VERSION,
                )
                .order_by(CoachJob.created_at.desc(), CoachJob.generation.desc())
            )
        ).all()
        latest_jobs: dict[UUID, CoachJob] = {}
        for saved_job in jobs:
            latest_jobs.setdefault(source_to_anchor[saved_job.record_id], saved_job)
        for record_id, _, _contest_id in source_rows:
            job = latest_jobs.get(record_id)
            report = (
                await db.get(CoachReport, job.id) if job and job.status == "succeeded" else None
            )
            if report and job:
                result.reports_ready += 1
                result.updated_at = max(result.updated_at, report.created_at)
                ReportBody.model_validate(report.body)
            elif job and job.status == "failed":
                result.failed_reports += 1
            else:
                result.pending_reports += 1
        result.status = (
            "updating" if result.pending_reports else "failed" if result.failed_reports else "ready"
        )
        return result
