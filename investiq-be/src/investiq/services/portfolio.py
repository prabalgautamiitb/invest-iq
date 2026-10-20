import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from investiq.adapters.market import EXCHANGE_TZ, FIXTURE_DATASETS
from investiq.analytics.portfolio import allocate
from investiq.core.errors import AppError
from investiq.core.security import Principal
from investiq.models.contest import Contest, ContestMembership, ContestRules
from investiq.models.identity import User
from investiq.models.market import IngestionRun, Instrument, MarketExclusion, PriceSnapshot
from investiq.models.portfolio import (
    DraftPosition,
    PortfolioDraft,
    PortfolioSubmission,
    SubmissionHolding,
)
from investiq.schemas.portfolio import (
    DraftInput,
    DraftOut,
    HoldingOut,
    PositionInput,
    PreviewOut,
    PriceEvidence,
    SubmissionOut,
    SubmissionPage,
    SubmitInput,
)
from investiq.services.contest import ContestService, phase
from investiq.services.exchange_calendar import expected_session
from investiq.services.market import decode_cursor, encode_cursor, fingerprint


class PortfolioService:
    def __init__(self, contests: ContestService) -> None:
        self.contests, self.factory, self.clock = contests, contests.factory, contests.clock

    @asynccontextmanager
    async def context(
        self, principal: Principal, identifier: UUID
    ) -> AsyncIterator[tuple[AsyncSession, User, Contest, ContestMembership]]:
        async with self.factory() as db, db.begin():
            user = await self.contests.actor(db, principal)
            c = await self.contests.load(db, identifier, user, lock=True)
            member = await db.scalar(
                select(ContestMembership)
                .where(ContestMembership.contest_id == c.id, ContestMembership.user_id == user.id)
                .with_for_update()
            )
            if member is None:
                raise AppError(
                    404, "portfolio_not_found", "Join this contest to access your portfolio"
                )
            yield db, user, c, member

    def editable(self, c: Contest) -> None:
        if phase(c, self.clock()) != "open":
            raise AppError(
                409,
                "portfolio_locked",
                "Drafts and submissions are editable only while entry is open",
            )

    async def draft(self, db: AsyncSession, member: ContestMembership) -> PortfolioDraft | None:
        return await db.scalar(
            select(PortfolioDraft)
            .where(PortfolioDraft.membership_id == member.id)
            .with_for_update()
        )

    async def positions(self, db: AsyncSession, draft: PortfolioDraft) -> list[PositionInput]:
        rows = (
            await db.scalars(
                select(DraftPosition)
                .where(DraftPosition.draft_id == draft.id)
                .order_by(DraftPosition.instrument_id)
            )
        ).all()
        return [
            PositionInput(
                instrument_id=p.instrument_id, quantity=p.quantity, weight_pct=p.weight_pct
            )
            for p in rows
        ]

    async def draft_output(
        self, db: AsyncSession, c: Contest, member: ContestMembership, draft: PortfolioDraft | None
    ) -> DraftOut:
        return DraftOut(
            id=draft.id if draft else None,
            contest_id=c.id,
            rule_id=member.rule_id,
            revision=draft.revision if draft else 0,
            mode=cast(Literal["quantity", "weight"], draft.mode) if draft else "weight",
            positions=await self.positions(db, draft) if draft else [],
            updated_at=draft.updated_at if draft else None,
            editable=phase(c, self.clock()) == "open",
        )

    async def get_draft(self, principal: Principal, identifier: UUID) -> DraftOut:
        async with self.context(principal, identifier) as (db, _, c, member):
            return await self.draft_output(db, c, member, await self.draft(db, member))

    async def eligibility(
        self,
        db: AsyncSession,
        c: Contest,
        member: ContestMembership,
        positions: list[PositionInput],
    ) -> ContestRules:
        rule = await db.get(ContestRules, member.rule_id)
        assert rule
        rules = await self.contests.rule_input(db, rule)
        ids = [p.instrument_id for p in positions]
        if not set(ids).issubset(rules.eligible_instrument_ids):
            raise AppError(
                422,
                "ineligible_instrument",
                "The draft contains an instrument outside the frozen universe",
            )
        if len(ids) > rules.max_holdings:
            raise AppError(422, "holding_count", "Draft exceeds the frozen maximum holdings")
        instruments = (
            await db.scalars(
                select(Instrument)
                .where(Instrument.id.in_(ids))
                .order_by(Instrument.id)
                .with_for_update(read=True)
            )
        ).all()
        blocked = await db.scalar(
            select(MarketExclusion.id)
            .where(
                MarketExclusion.instrument_id.in_(ids),
                MarketExclusion.starts_on <= c.ends_at.astimezone(EXCHANGE_TZ).date(),
                or_(
                    MarketExclusion.ends_on.is_(None),
                    MarketExclusion.ends_on >= self.clock().astimezone(EXCHANGE_TZ).date(),
                ),
            )
            .limit(1)
        )
        if (
            len(instruments) != len(ids)
            or any(
                not i.active or i.kind != "equity" or i.data_kind != "fixture" for i in instruments
            )
            or blocked
        ):
            raise AppError(
                422, "ineligible_instrument", "Inactive or excluded instruments cannot be submitted"
            )
        return rule

    async def save(self, principal: Principal, identifier: UUID, data: DraftInput) -> DraftOut:
        async with self.context(principal, identifier) as (db, user, c, member):
            self.editable(c)
            draft = await self.draft(db, member)
            if (draft.revision if draft else 0) != data.expected_revision:
                raise AppError(
                    409, "draft_conflict", "Draft changed in another tab. Reload before saving"
                )
            await self.eligibility(db, c, member, data.positions)
            if draft is None:
                draft = PortfolioDraft(
                    membership_id=member.id, revision=1, mode=data.mode, updated_at=self.clock()
                )
                db.add(draft)
                await db.flush()
            else:
                draft.revision += 1
                draft.mode, draft.updated_at = data.mode, self.clock()
                await db.execute(delete(DraftPosition).where(DraftPosition.draft_id == draft.id))
            db.add_all([DraftPosition(draft_id=draft.id, **p.model_dump()) for p in data.positions])
            self.editable(
                c
            )  # Recheck after any locks/catalogue work, rather than a stale route check.
            self.contests.audit(db, user, "portfolio_draft_saved", draft.id)
            await db.flush()
            return await self.draft_output(db, c, member, draft)

    async def calculate(
        self, db: AsyncSession, c: Contest, member: ContestMembership, revision: int
    ) -> PreviewOut:
        self.editable(c)
        draft = await self.draft(db, member)
        if draft is None or draft.revision != revision:
            raise AppError(
                409, "draft_conflict", "Reload and save the current draft before reviewing"
            )
        positions = await self.positions(db, draft)
        rule = await self.eligibility(db, c, member, positions)
        rules = await self.contests.rule_input(db, rule)
        instant = self.clock()
        expected = await expected_session(db, instant)
        identifiers = [p.instrument_id for p in positions] + [rules.benchmark_id]
        rows = (
            await db.execute(
                select(PriceSnapshot, Instrument, IngestionRun)
                .join(Instrument, Instrument.id == PriceSnapshot.instrument_id)
                .join(IngestionRun, IngestionRun.id == PriceSnapshot.run_id)
                .where(
                    PriceSnapshot.instrument_id.in_(identifiers),
                    PriceSnapshot.session_date == expected.session_date,
                    PriceSnapshot.observed_at == expected.closes_at,
                    PriceSnapshot.source_published_at <= instant,
                    IngestionRun.status == "succeeded",
                    IngestionRun.provider == "investiq-synthetic",
                    IngestionRun.dataset_version.in_(FIXTURE_DATASETS),
                    IngestionRun.data_kind == "fixture",
                )
                .order_by(Instrument.id)
                .with_for_update(read=True, of=[PriceSnapshot, Instrument])
            )
        ).all()
        points = {i.id: (p, i, run) for p, i, run in rows}
        blocked = await db.scalar(
            select(MarketExclusion.id)
            .where(
                MarketExclusion.instrument_id.in_(identifiers),
                MarketExclusion.starts_on <= c.ends_at.astimezone(EXCHANGE_TZ).date(),
                or_(
                    MarketExclusion.ends_on.is_(None),
                    MarketExclusion.ends_on >= expected.session_date,
                ),
            )
            .limit(1)
        )
        if (
            len(points) != len(set(identifiers))
            or blocked
            or any(not i.active or i.data_kind != "fixture" for _, i, _ in points.values())
        ):
            raise AppError(
                409,
                "market_data_incomplete",
                "A complete current common EOD session, including benchmark, is required",
            )
        benchmark = points[rules.benchmark_id][1]
        if benchmark.kind != "benchmark" or benchmark.currency != "POINTS":
            raise AppError(409, "market_data_incomplete", "The frozen benchmark is unavailable")
        # All prices must come from one successful common batch, not mixed publications.
        if len({p.run_id for p, _, _ in points.values()}) != 1:
            raise AppError(
                409, "market_data_incomplete", "Prices must share one complete EOD publication"
            )
        result = allocate(rules, positions, {i: p.close for i, (p, _, _) in points.items()})
        holdings = []
        for position in positions:
            p, instrument, run = points[position.instrument_id]
            holdings.append(
                HoldingOut(
                    instrument_id=instrument.id,
                    symbol=instrument.symbol,
                    quantity=result.quantities[instrument.id],
                    price=p.close,
                    notional=result.notionals[instrument.id],
                    price_snapshot_id=p.id,
                    observed_at=p.observed_at,
                    source_published_at=p.source_published_at,
                    ingested_at=p.ingested_at,
                    source=run.provider,
                    dataset_version=run.dataset_version,
                )
            )
        p, instrument, run = points[rules.benchmark_id]
        benchmark_evidence = PriceEvidence(
            instrument_id=instrument.id,
            symbol=instrument.symbol,
            price=p.close,
            price_snapshot_id=p.id,
            observed_at=p.observed_at,
            source_published_at=p.source_published_at,
            ingested_at=p.ingested_at,
            source=run.provider,
            dataset_version=run.dataset_version,
        )
        evidence = dict(
            contest_id=str(c.id),
            rule_id=str(rule.id),
            draft_revision=revision,
            holdings=[h.model_dump(mode="json") for h in holdings],
            benchmark=benchmark_evidence.model_dump(mode="json"),
            calendar_version=expected.calendar_version,
            session=str(expected.session_date),
            capital=str(rules.capital),
            notional=str(result.notional),
            fee=str(result.fee),
            cash=str(result.cash),
            calculation_version="whole-shares-v1",
        )
        digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
        self.editable(c)
        return PreviewOut(
            contest_id=c.id,
            rule_id=rule.id,
            draft_revision=revision,
            preview_hash=digest,
            capital=rules.capital,
            notional=result.notional,
            fee=result.fee,
            cash=result.cash,
            holdings=holdings,
            benchmark=benchmark_evidence,
            price_session_date=expected.session_date,
            calendar_version=expected.calendar_version,
            pricing_as_of=instant,
            locks_at=c.entry_closes_at,
        )

    async def preview(self, principal: Principal, identifier: UUID, revision: int) -> PreviewOut:
        async with self.context(principal, identifier) as (db, _, c, member):
            return await self.calculate(db, c, member, revision)

    async def submission_output(
        self, db: AsyncSession, c: Contest, submission: PortfolioSubmission
    ) -> SubmissionOut:
        holdings = (
            await db.scalars(
                select(SubmissionHolding)
                .where(SubmissionHolding.submission_id == submission.id)
                .order_by(SubmissionHolding.instrument_id)
            )
        ).all()
        version = await db.scalar(
            select(func.max(PortfolioSubmission.version)).where(
                PortfolioSubmission.membership_id == submission.membership_id
            )
        )
        return SubmissionOut(
            id=submission.id,
            version=submission.version,
            submitted_at=submission.submitted_at,
            is_latest=version == submission.version,
            contest_id=c.id,
            rule_id=submission.rule_id,
            draft_revision=submission.draft_revision,
            preview_hash=submission.preview_hash,
            capital=submission.capital,
            notional=submission.notional,
            fee=submission.fee,
            cash=submission.cash,
            holdings=[
                HoldingOut(**{key: getattr(h, key) for key in HoldingOut.model_fields})
                for h in holdings
            ],
            benchmark=PriceEvidence.model_validate(
                {
                    **submission.benchmark_metadata,
                    "price": submission.benchmark_price,
                    "price_snapshot_id": submission.benchmark_snapshot_id,
                }
            ),
            price_session_date=submission.price_session_date,
            calendar_version=submission.calendar_version,
            pricing_as_of=submission.pricing_as_of,
            locks_at=submission.locks_at,
        )

    async def submit(
        self, principal: Principal, identifier: UUID, data: SubmitInput, key: UUID
    ) -> SubmissionOut:
        request_hash = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
        async with self.context(principal, identifier) as (db, user, c, member):
            existing = await db.scalar(
                select(PortfolioSubmission).where(
                    PortfolioSubmission.membership_id == member.id,
                    PortfolioSubmission.idempotency_key == key,
                )
            )
            if existing:
                if existing.request_hash != request_hash:
                    raise AppError(
                        409,
                        "idempotency_conflict",
                        "Submission key was already used with another preview",
                    )
                return await self.submission_output(db, c, existing)
            # One immutable submission per saved revision; concurrent requests cannot double-submit.
            saved = await self.draft(db, member)
            if saved:
                same = await db.scalar(
                    select(PortfolioSubmission.id).where(
                        PortfolioSubmission.draft_id == saved.id,
                        PortfolioSubmission.draft_revision == data.draft_revision,
                    )
                )
                if same:
                    raise AppError(
                        409,
                        "revision_submitted",
                        "This revision was submitted. Save a new draft revision to resubmit",
                    )
            preview = await self.calculate(db, c, member, data.draft_revision)
            if preview.preview_hash != data.preview_hash:
                raise AppError(
                    409,
                    "preview_changed",
                    "Prices or evidence changed. Review the current preview before submitting",
                )
            assert saved
            version = (
                await db.scalar(
                    select(func.max(PortfolioSubmission.version)).where(
                        PortfolioSubmission.membership_id == member.id
                    )
                )
                or 0
            ) + 1
            submission = PortfolioSubmission(
                membership_id=member.id,
                rule_id=member.rule_id,
                draft_id=saved.id,
                draft_revision=saved.revision,
                version=version,
                idempotency_key=key,
                request_hash=request_hash,
                preview_hash=preview.preview_hash,
                capital=preview.capital,
                notional=preview.notional,
                fee=preview.fee,
                cash=preview.cash,
                benchmark_snapshot_id=preview.benchmark.price_snapshot_id,
                benchmark_price=preview.benchmark.price,
                benchmark_metadata=preview.benchmark.model_dump(
                    mode="json", exclude={"price", "price_snapshot_id"}
                ),
                price_session_date=preview.price_session_date,
                calendar_version=preview.calendar_version,
                pricing_as_of=preview.pricing_as_of,
                submitted_at=self.clock(),
                locks_at=c.entry_closes_at,
                calculation_version=preview.calculation_version,
                sealed=False,
            )
            db.add(submission)
            await db.flush()
            db.add_all(
                [
                    SubmissionHolding(submission_id=submission.id, **h.model_dump())
                    for h in preview.holdings
                ]
            )
            await db.flush()
            self.editable(c)
            submission.sealed = True
            self.contests.audit(db, user, "portfolio_submitted", submission.id)
            await db.flush()
            return await self.submission_output(db, c, submission)

    async def history(
        self, principal: Principal, identifier: UUID, cursor: str | None = None, limit: int = 20
    ) -> SubmissionPage:
        async with self.context(principal, identifier) as (db, _, c, member):
            query = select(PortfolioSubmission).where(
                PortfolioSubmission.membership_id == member.id, PortfolioSubmission.sealed.is_(True)
            )
            context = fingerprint({"membership": str(member.id), "kind": "submissions"})
            if cursor:
                raw, _ = decode_cursor(cursor, context)
                try:
                    version = int(raw)
                    if version < 1:
                        raise ValueError
                except ValueError as exc:
                    raise AppError(
                        422, "invalid_cursor", "Invalid submission history cursor"
                    ) from exc
                query = query.where(PortfolioSubmission.version < version)
            rows = (
                await db.scalars(
                    query.order_by(PortfolioSubmission.version.desc()).limit(limit + 1)
                )
            ).all()
            return SubmissionPage(
                items=[await self.submission_output(db, c, s) for s in rows[:limit]],
                next_cursor=encode_cursor(str(rows[limit - 1].version), rows[limit - 1].id, context)
                if len(rows) > limit
                else None,
            )
