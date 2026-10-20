import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from investiq.adapters.market import EXCHANGE_TZ, FIXTURE_DATASETS
from investiq.analytics.valuation import ValuedHolding, value_portfolio
from investiq.core.errors import AppError
from investiq.core.security import Principal
from investiq.models.contest import Contest, ContestMembership
from investiq.models.identity import AuditEvent, Privacy, User
from investiq.models.market import (
    ExchangeSession,
    IngestionRun,
    Instrument,
    MarketExclusion,
    PriceSnapshot,
)
from investiq.models.portfolio import PortfolioSubmission, SubmissionHolding
from investiq.models.valuation import (
    ContestFinalization,
    ValuationPrice,
    ValuationRecord,
    ValuationRun,
)
from investiq.schemas.valuation import (
    ContestHistoryOut,
    DashboardItem,
    DashboardOut,
    LeaderboardOut,
    MetricsOut,
    PerformanceOut,
    RankOut,
    ResultsTimingOut,
)
from investiq.services.contest import ContestService, phase
from investiq.services.market import decode_cursor, encode_cursor, fingerprint
from investiq.services.market_ingestion import ensure_fixture_mode


class ValuationService:
    def __init__(self, contests: ContestService) -> None:
        self.contests, self.factory, self.clock = contests, contests.factory, contests.clock
        self.settings = contests.identity.settings

    async def sessions(self, db: AsyncSession, c: Contest) -> list[ExchangeSession]:
        first, last = (
            c.starts_at.astimezone(EXCHANGE_TZ).date(),
            c.ends_at.astimezone(EXCHANGE_TZ).date(),
        )
        days = (
            await db.scalars(
                select(ExchangeSession)
                .where(
                    ExchangeSession.exchange == "NSE",
                    ExchangeSession.session_date.between(first, last),
                )
                .order_by(ExchangeSession.session_date)
            )
        ).all()
        if len(days) != (last - first).days + 1 or not days:
            raise AppError(503, "calendar_unavailable", "Contest calendar coverage is incomplete")
        if (
            any(d.status == "unsupported" for d in days)
            or days[0].opens_at != c.starts_at
            or days[-1].closes_at != c.ends_at
        ):
            raise AppError(
                409, "unsupported_session", "Reviewed contest session boundaries changed"
            )
        return [d for d in days if d.status == "open"]

    async def latest_submissions(self, db: AsyncSession, c: Contest) -> list[PortfolioSubmission]:
        members = select(ContestMembership.id).where(ContestMembership.contest_id == c.id)
        versions = (
            select(
                PortfolioSubmission.membership_id,
                func.max(PortfolioSubmission.version).label("version"),
            )
            .where(
                PortfolioSubmission.membership_id.in_(members), PortfolioSubmission.sealed.is_(True)
            )
            .group_by(PortfolioSubmission.membership_id)
            .subquery()
        )
        return list(
            (
                await db.scalars(
                    select(PortfolioSubmission)
                    .join(
                        versions,
                        (PortfolioSubmission.membership_id == versions.c.membership_id)
                        & (PortfolioSubmission.version == versions.c.version),
                    )
                    .order_by(PortfolioSubmission.membership_id)
                )
            ).all()
        )

    async def evaluate(self, identifier: UUID, *, max_sessions: int = 10) -> dict[str, Any]:
        """Trusted worker/operator entry; clients cannot supply values, ranks or time."""
        ensure_fixture_mode(self.settings)
        processed = 0
        for _ in range(max_sessions):
            async with self.factory() as db, db.begin():
                c = await db.get(Contest, identifier, with_for_update=True)
                if c is None:
                    raise AppError(404, "contest_not_found", "Contest not found")
                final = await db.get(ContestFinalization, c.id)
                if final:
                    return {
                        "status": "completed",
                        "processed": processed,
                        "run_id": str(final.run_id),
                    }
                if phase(c, self.clock()) not in {"running", "settling"}:
                    return {"status": "waiting", "processed": processed}
                sessions = await self.sessions(db, c)
                due = [d for d in sessions if d.available_at and d.available_at <= self.clock()]
                succeeded = set(
                    (
                        await db.scalars(
                            select(ValuationRun.session_date).where(
                                ValuationRun.contest_id == c.id, ValuationRun.status == "succeeded"
                            )
                        )
                    ).all()
                )
                remaining = [d for d in due if d.session_date not in succeeded]
                if not remaining:
                    return {"status": "waiting", "processed": processed}
                day = remaining[0]
                assert day.closes_at and day.available_at
                run = await db.scalar(
                    select(ValuationRun).where(
                        ValuationRun.contest_id == c.id,
                        ValuationRun.session_date == day.session_date,
                    )
                )
                if run is None:
                    run = ValuationRun(
                        contest_id=c.id,
                        session_date=day.session_date,
                        observed_at=day.closes_at,
                        available_at=day.available_at,
                        status="pending",
                        attempts=1,
                        participant_count=0,
                        evaluated_at=self.clock(),
                    )
                    db.add(run)
                else:
                    run.attempts += 1
                    run.status = "pending"
                    run.error_code = None
                    run.evaluated_at = self.clock()
                await db.flush()
                try:
                    async with db.begin_nested():
                        await self.value_day(db, c, run, day)
                except AppError as exc:
                    run.status, run.error_code = "blocked", exc.code
                    await db.flush()
                    return {"status": "blocked", "error_code": exc.code, "processed": processed}
                processed += 1
                if day.session_date == sessions[-1].session_date:
                    db.add(
                        ContestFinalization(
                            contest_id=c.id, run_id=run.id, completed_at=self.clock()
                        )
                    )
                    c.status = "completed"
                    db.add(
                        AuditEvent(
                            actor_id=None, action="contest_results_finalized", resource_id=c.id
                        )
                    )
                    await db.flush()
                    return {"status": "completed", "processed": processed, "run_id": str(run.id)}
        return {"status": "more_due", "processed": processed}

    async def value_day(
        self, db: AsyncSession, c: Contest, run: ValuationRun, day: ExchangeSession
    ) -> None:
        submissions = await self.latest_submissions(db, c)
        identifiers: set[UUID] = set()
        by_submission = {}
        for s in submissions:
            holding_rows = list(
                (
                    await db.scalars(
                        select(SubmissionHolding)
                        .where(SubmissionHolding.submission_id == s.id)
                        .order_by(SubmissionHolding.instrument_id)
                    )
                ).all()
            )
            by_submission[s.id] = holding_rows
            identifiers.update(h.instrument_id for h in holding_rows)
            identifiers.add(UUID(s.benchmark_metadata["instrument_id"]))
        rule = await self.contests.rules(db, c)
        rules = await self.contests.rule_input(db, rule)
        identifiers.add(rules.benchmark_id) if submissions else None
        points = {}
        if identifiers:
            rows = (
                await db.execute(
                    select(PriceSnapshot, Instrument, IngestionRun)
                    .join(Instrument, Instrument.id == PriceSnapshot.instrument_id)
                    .join(IngestionRun, IngestionRun.id == PriceSnapshot.run_id)
                    .where(
                        PriceSnapshot.instrument_id.in_(identifiers),
                        PriceSnapshot.session_date == day.session_date,
                        PriceSnapshot.observed_at == day.closes_at,
                        PriceSnapshot.source_published_at <= self.clock(),
                        IngestionRun.status == "succeeded",
                        IngestionRun.provider == "investiq-synthetic",
                        IngestionRun.dataset_version.in_(FIXTURE_DATASETS),
                        IngestionRun.data_kind == "fixture",
                    )
                    .order_by(Instrument.id)
                    .with_for_update(read=True, of=[Instrument, PriceSnapshot])
                )
            ).all()
            points = {i.id: (p, i, ingestion) for p, i, ingestion in rows}
            blocked = await db.scalar(
                select(MarketExclusion.id)
                .where(
                    MarketExclusion.instrument_id.in_(identifiers),
                    MarketExclusion.starts_on <= day.session_date,
                    or_(
                        MarketExclusion.ends_on.is_(None),
                        MarketExclusion.ends_on >= min(s.price_session_date for s in submissions),
                    ),
                )
                .limit(1)
            )
            if (
                len(points) != len(identifiers)
                or blocked
                or any(not i.active or i.data_kind != "fixture" for _, i, _ in points.values())
                or len({p.run_id for p, _, _ in points.values()}) != 1
            ):
                raise AppError(
                    409, "market_data_incomplete", "A complete common published session is required"
                )
        prices = []
        for p, i, ingestion in points.values():
            if i.id == rules.benchmark_id and (i.kind != "benchmark" or i.currency != "POINTS"):
                raise AppError(
                    409, "market_data_incomplete", "Frozen benchmark classification changed"
                )
            values = dict(
                run_id=run.id,
                instrument_id=i.id,
                price_snapshot_id=p.id,
                sector_id=i.sector_id,
                symbol=i.symbol,
                price=p.close,
                observed_at=p.observed_at,
                published_at=p.source_published_at,
                ingested_at=p.ingested_at,
                source=ingestion.provider,
                dataset_version=ingestion.dataset_version,
            )
            db.add(ValuationPrice(**values))
            prices.append({k: str(v) for k, v in values.items() if k != "run_id"})
        computed = []
        for s in submissions:
            if (
                s.rule_id != rule.id
                or s.submitted_at >= c.entry_closes_at
                or s.capital != rule.capital
                or s.locks_at != c.entry_closes_at
                or UUID(s.benchmark_metadata["instrument_id"]) != rules.benchmark_id
            ):
                raise AppError(
                    409,
                    "invalid_submission_evidence",
                    "Submission is not bound to frozen contest rules",
                )
            previous = await db.scalar(
                select(ValuationRecord)
                .join(ValuationRun, ValuationRun.id == ValuationRecord.run_id)
                .where(
                    ValuationRecord.membership_id == s.membership_id,
                    ValuationRun.status == "succeeded",
                    ValuationRun.session_date < day.session_date,
                )
                .order_by(ValuationRun.session_date.desc())
                .limit(1)
            )
            if previous and previous.submission_id != s.id:
                raise AppError(
                    409,
                    "submission_evidence_changed",
                    "Accepted portfolio changed after valuation began",
                )
            if any(
                points[h.instrument_id][1].kind != "equity"
                or points[h.instrument_id][1].currency != "INR"
                for h in by_submission[s.id]
            ):
                raise AppError(
                    409, "invalid_valuation_evidence", "A frozen equity classification changed"
                )
            holdings = [
                ValuedHolding(
                    h.instrument_id,
                    h.symbol,
                    h.quantity,
                    h.notional,
                    points[h.instrument_id][0].close,
                    points[h.instrument_id][1].sector_id,
                )
                for h in by_submission[s.id]
            ]
            metrics = value_portfolio(
                s.capital,
                s.cash,
                s.fee,
                s.benchmark_price,
                points[UUID(s.benchmark_metadata["instrument_id"])][0].close,
                holdings,
                previous.peak_value if previous else None,
                previous.max_drawdown_pct if previous else Decimal(0),
            )
            computed.append((s, metrics))
        # Capital is shared within a frozen contest. Exact net P&L sorts before rounded metrics.
        computed.sort(
            key=lambda pair: (
                -pair[1].pnl,
                pair[1].max_drawdown_pct,
                pair[0].submitted_at,
                pair[0].membership_id,
            )
        )
        digest_rows = []
        for rank, (s, m) in enumerate(computed, 1):
            values = asdict(m)
            positions = values.pop("positions")
            db.add(
                ValuationRecord(
                    run_id=run.id,
                    membership_id=s.membership_id,
                    submission_id=s.id,
                    rank=rank,
                    capital=s.capital,
                    cash=s.cash,
                    fee=s.fee,
                    details={"positions": positions},
                    **values,
                )
            )
            digest_rows.append(
                {
                    "submission_id": str(s.id),
                    "rank": rank,
                    **{k: str(v) for k, v in values.items()},
                    "positions": positions,
                }
            )
        run.participant_count = len(computed)
        run.evidence_hash = hashlib.sha256(
            json.dumps(
                {"prices": prices, "records": digest_rows, "version": "eod-valuation-v1"},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        await db.flush()
        run.status, run.error_code = "succeeded", None
        await db.flush()

    async def sweep(self, limit: int = 100) -> dict[str, int]:
        ensure_fixture_mode(self.settings)
        async with self.factory() as db:
            # Rotate by oldest attempt so repeatedly blocked contests cannot starve newer work.
            last_attempt = (
                select(func.max(ValuationRun.evaluated_at))
                .where(ValuationRun.contest_id == Contest.id)
                .scalar_subquery()
            )
            ids = list(
                (
                    await db.scalars(
                        select(Contest.id)
                        .where(
                            Contest.status.not_in(["draft", "cancelled", "completed"]),
                            Contest.starts_at <= self.clock(),
                        )
                        .order_by(last_attempt.asc().nullsfirst(), Contest.id)
                        .limit(limit)
                    )
                ).all()
            )
        counts = {"completed": 0, "blocked": 0, "waiting": 0, "more_due": 0}
        for identifier in ids:
            try:
                result = await self.evaluate(identifier)
                counts[result["status"]] += 1
            except AppError:
                counts["blocked"] += 1
        return counts

    async def board_state(
        self, db: AsyncSession, c: Contest
    ) -> tuple[ValuationRun | None, date | None, bool, bool, str | None]:
        final = await db.get(ContestFinalization, c.id)
        if final:
            run = await db.get(ValuationRun, final.run_id)
            assert run
            return run, run.session_date, True, True, None
        latest = await db.scalar(
            select(ValuationRun)
            .where(ValuationRun.contest_id == c.id, ValuationRun.status == "succeeded")
            .order_by(ValuationRun.session_date.desc())
            .limit(1)
        )
        try:
            sessions = await self.sessions(db, c)
        except AppError as exc:
            return latest, None, False, False, exc.code
        due = [
            d.session_date for d in sessions if d.available_at and d.available_at <= self.clock()
        ]
        expected = due[-1] if due else None
        failed = await db.scalar(
            select(ValuationRun)
            .where(ValuationRun.contest_id == c.id, ValuationRun.status == "blocked")
            .order_by(ValuationRun.session_date.desc())
            .limit(1)
        )
        current = bool(
            latest and latest.session_date == expected and phase(c, self.clock()) != "cancelled"
        )
        return (
            latest,
            expected,
            current,
            False,
            failed.error_code if failed and not current else None,
        )

    async def results_timing(
        self,
        db: AsyncSession,
        c: Contest,
        run: ValuationRun | None,
        current: bool,
        final: bool,
        error: str | None,
    ) -> ResultsTimingOut:
        """Explain the server's current wait using the reviewed calendar, not browser time."""
        timing = ResultsTimingOut(
            entry_opens_at=c.entry_opens_at,
            entry_closes_at=c.entry_closes_at,
            starts_at=c.starts_at,
            ends_at=c.ends_at,
            first_session_closes_at=None,
            first_results_available_at=None,
            next_results_available_at=None,
            state="unavailable",
        )
        state = phase(c, self.clock())
        if state == "cancelled":
            timing.state = "cancelled"
        elif final:
            timing.state = "final"
        elif state == "draft":
            timing.state = "draft"
        try:
            sessions = await self.sessions(db, c)
        except AppError:
            return timing
        timing.first_session_closes_at = sessions[0].closes_at
        timing.first_results_available_at = sessions[0].available_at
        if timing.state in {"cancelled", "final", "draft"}:
            return timing
        next_day = next(
            (day for day in sessions if run is None or day.session_date > run.session_date), None
        )
        timing.next_results_available_at = next_day.available_at if next_day else None
        if error:
            timing.state = "awaiting_data"
        elif state in {"scheduled", "open", "locked"}:
            timing.state = "not_started"
        elif current:
            timing.state = "current"
        elif next_day and next_day.available_at and next_day.available_at > self.clock():
            timing.state = "awaiting_close"
        else:
            timing.state = "processing"
        return timing

    async def leaderboard(
        self,
        identifier: UUID,
        principal: Principal | None,
        cursor: str | None = None,
        limit: int = 20,
        run_id: UUID | None = None,
    ) -> LeaderboardOut:
        ensure_fixture_mode(self.settings)
        async with self.factory() as db, db.begin():
            user = await self.contests.actor(db, principal, verified=False) if principal else None
            c = await self.contests.load(db, identifier, user)
            latest, expected, current, final, error = await self.board_state(db, c)
            timing = await self.results_timing(db, c, latest, current, final, error)
            run = latest
            if run_id:
                run = await db.scalar(
                    select(ValuationRun).where(
                        ValuationRun.id == run_id,
                        ValuationRun.contest_id == c.id,
                        ValuationRun.status == "succeeded",
                    )
                )
                if run is None:
                    raise AppError(404, "valuation_not_found", "Valuation snapshot not found")
                current = current and bool(latest and run.id == latest.id)
                final = final and bool(latest and run.id == latest.id)
            context = fingerprint(
                {
                    "run": str(run.id) if run else None,
                    "viewer": str(user.id) if user else None,
                    "kind": "leaderboard",
                }
            )
            after = 0
            if cursor:
                raw, _ = decode_cursor(cursor, context)
                try:
                    after = int(raw)
                    if after < 1:
                        raise ValueError
                except ValueError as exc:
                    raise AppError(422, "invalid_cursor", "Invalid leaderboard cursor") from exc
            rows: Sequence[Row[ValuationRecord, ContestMembership, User, Privacy]] = []
            if run:
                rows = (
                    await db.execute(
                        select(ValuationRecord, ContestMembership, User, Privacy)
                        .join(
                            ContestMembership, ContestMembership.id == ValuationRecord.membership_id
                        )
                        .join(User, User.id == ContestMembership.user_id)
                        .outerjoin(Privacy, Privacy.user_id == User.id)
                        .where(ValuationRecord.run_id == run.id, ValuationRecord.rank > after)
                        .order_by(ValuationRecord.rank)
                        .limit(limit + 1)
                    )
                ).all()
            items = []
            for record, member, participant, privacy in rows[:limit]:
                label = (
                    participant.name
                    if participant.active and privacy and privacy.public
                    else "Learner " + member.id.hex[:8]
                )
                items.append(
                    RankOut(
                        entry_id=member.id,
                        label=label,
                        is_you=bool(user and user.id == member.user_id),
                        rank=record.rank,
                        total_value=record.total_value,
                        return_pct=record.return_pct,
                        benchmark_return_pct=record.benchmark_return_pct,
                        excess_return_pct=record.excess_return_pct,
                        max_drawdown_pct=record.max_drawdown_pct,
                    )
                )
            count = await db.scalar(
                select(func.count())
                .select_from(ContestMembership)
                .where(ContestMembership.contest_id == c.id)
            )
            submitted_count = await db.scalar(
                select(func.count(func.distinct(PortfolioSubmission.membership_id)))
                .join(ContestMembership, ContestMembership.id == PortfolioSubmission.membership_id)
                .where(ContestMembership.contest_id == c.id, PortfolioSubmission.sealed.is_(True))
            )
            viewer_member = (
                await db.scalar(
                    select(ContestMembership).where(
                        ContestMembership.contest_id == c.id,
                        ContestMembership.user_id == user.id,
                    )
                )
                if user
                else None
            )
            has_submission = bool(
                viewer_member
                and await db.scalar(
                    select(PortfolioSubmission.id)
                    .where(
                        PortfolioSubmission.membership_id == viewer_member.id,
                        PortfolioSubmission.sealed.is_(True),
                    )
                    .limit(1)
                )
            )
            return LeaderboardOut(
                timing=timing,
                submitted_count=submitted_count or 0,
                has_joined=viewer_member is not None,
                has_submission=has_submission,
                contest_id=c.id,
                contest_name=c.name,
                contest_status=phase(c, self.clock()),
                run_id=run.id if run else None,
                session_date=run.session_date if run else None,
                valued_at=run.observed_at if run else None,
                expected_session_date=expected,
                is_current=current,
                is_final=final,
                job_status="blocked" if error else "succeeded" if current else "waiting",
                error_code=error,
                participant_count=run.participant_count if run else 0,
                member_count=count or 0,
                items=items,
                next_cursor=encode_cursor(
                    str(rows[limit - 1][0].rank), rows[limit - 1][0].id, context
                )
                if len(rows) > limit
                else None,
            )

    @staticmethod
    def metrics(record: ValuationRecord, run: ValuationRun) -> MetricsOut:
        data = {
            key: getattr(record, key)
            for key in MetricsOut.model_fields
            if key not in {"session_date", "positions"}
        }
        return MetricsOut(
            **data, session_date=run.session_date, positions=record.details["positions"]
        )

    async def performance(
        self, principal: Principal, identifier: UUID, cursor: str | None = None, limit: int = 20
    ) -> PerformanceOut:
        async with self.factory() as db, db.begin():
            user = await self.contests.actor(db, principal)
            c = await self.contests.load(db, identifier, user)
            member = await db.scalar(
                select(ContestMembership).where(
                    ContestMembership.contest_id == c.id, ContestMembership.user_id == user.id
                )
            )
            if member is None:
                raise AppError(
                    404, "performance_not_found", "Join the contest to view your performance"
                )
            run, expected, current, final, error = await self.board_state(db, c)
            record = (
                await db.scalar(
                    select(ValuationRecord).where(
                        ValuationRecord.run_id == run.id, ValuationRecord.membership_id == member.id
                    )
                )
                if run
                else None
            )
            has_submission = bool(
                await db.scalar(
                    select(PortfolioSubmission.id)
                    .where(
                        PortfolioSubmission.membership_id == member.id,
                        PortfolioSubmission.sealed.is_(True),
                    )
                    .limit(1)
                )
            )
            context = fingerprint({"member": str(member.id), "kind": "performance"})
            query = (
                select(ValuationRecord, ValuationRun)
                .join(ValuationRun, ValuationRun.id == ValuationRecord.run_id)
                .where(
                    ValuationRecord.membership_id == member.id, ValuationRun.status == "succeeded"
                )
            )
            if cursor:
                raw, _ = decode_cursor(cursor, context)
                try:
                    before = date.fromisoformat(raw)
                except ValueError as exc:
                    raise AppError(422, "invalid_cursor", "Invalid performance cursor") from exc
                query = query.where(ValuationRun.session_date < before)
            rows = (
                await db.execute(query.order_by(ValuationRun.session_date.desc()).limit(limit + 1))
            ).all()
            return PerformanceOut(
                timing=await self.results_timing(db, c, run, current, final, error),
                contest_id=c.id,
                contest_name=c.name,
                contest_status=phase(c, self.clock()),
                is_current=current,
                is_final=final,
                expected_session_date=expected,
                error_code=error,
                has_submission=has_submission,
                metrics=self.metrics(record, run) if record and run else None,
                series=[self.metrics(r, v) for r, v in rows[:limit]],
                next_cursor=encode_cursor(
                    rows[limit - 1][1].session_date.isoformat(), rows[limit - 1][0].id, context
                )
                if len(rows) > limit
                else None,
            )

    async def dashboard_items(self, db: AsyncSession, user: User) -> list[DashboardItem]:
        rows = (
            await db.execute(
                select(Contest, ContestMembership)
                .join(ContestMembership, ContestMembership.contest_id == Contest.id)
                .where(ContestMembership.user_id == user.id)
                .order_by(Contest.starts_at.desc(), Contest.id)
            )
        ).all()
        result = []
        for c, member in rows:
            run, _, current, final, _ = await self.board_state(db, c)
            record = (
                await db.scalar(
                    select(ValuationRecord).where(
                        ValuationRecord.run_id == run.id, ValuationRecord.membership_id == member.id
                    )
                )
                if run
                else None
            )
            submitted = bool(
                await db.scalar(
                    select(PortfolioSubmission.id)
                    .where(
                        PortfolioSubmission.membership_id == member.id,
                        PortfolioSubmission.sealed.is_(True),
                    )
                    .limit(1)
                )
            )
            result.append(
                DashboardItem(
                    contest_id=c.id,
                    name=c.name,
                    status=phase(c, self.clock()),
                    has_submission=submitted,
                    session_date=run.session_date if record and run else None,
                    is_current=current,
                    is_final=final,
                    rank=record.rank if record else None,
                    total_value=record.total_value if record else None,
                    pnl=record.pnl if record else None,
                    return_pct=record.return_pct if record else None,
                )
            )
        return result

    async def dashboard(self, principal: Principal) -> DashboardOut:
        async with self.factory() as db, db.begin():
            user = await self.contests.actor(db, principal, verified=False)
            items = await self.dashboard_items(db, user)
            valued = [i for i in items if i.total_value is not None and i.status != "cancelled"]
            return DashboardOut(
                joined_count=len(items),
                active_count=sum(
                    i.status in {"open", "locked", "running", "settling"} for i in items
                ),
                completed_count=sum(i.is_final for i in items),
                cancelled_count=sum(i.status == "cancelled" for i in items),
                submitted_count=sum(i.has_submission for i in items),
                wins=sum(i.is_final and i.rank == 1 for i in items),
                valued_count=len(valued),
                latest_snapshot_value=sum(
                    (i.total_value or Decimal(0) for i in valued), Decimal(0)
                ),
                latest_snapshot_pnl=sum((i.pnl or Decimal(0) for i in valued), Decimal(0)),
                all_valued_current=bool(valued) and all(i.is_current for i in valued),
                items=items[:20],
            )

    async def history(
        self, principal: Principal, cursor: str | None = None, limit: int = 20
    ) -> ContestHistoryOut:
        async with self.factory() as db, db.begin():
            user = await self.contests.actor(db, principal, verified=False)
            items = [
                i
                for i in await self.dashboard_items(db, user)
                if i.status in {"completed", "cancelled"}
            ]
            items.sort(key=lambda i: i.contest_id)
            context = fingerprint({"user": str(user.id), "kind": "contest-history"})
            if cursor:
                _, after = decode_cursor(cursor, context)
                items = [i for i in items if i.contest_id > after]
            return ContestHistoryOut(
                items=items[:limit],
                next_cursor=encode_cursor("", items[limit - 1].contest_id, context)
                if len(items) > limit
                else None,
            )
