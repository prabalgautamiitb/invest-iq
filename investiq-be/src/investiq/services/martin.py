import asyncio
import re
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from investiq.adapters.martin import LangChainMartin, MartinProvider
from investiq.ai.evidence import number
from investiq.ai.martin import complete_personal_citations, personal_metrics_supported
from investiq.core.errors import AppError
from investiq.core.security import Principal, now
from investiq.models.contest import Contest, ContestMembership
from investiq.models.identity import User
from investiq.models.learning import LessonVersion
from investiq.models.martin import MartinConversation, MartinTurn
from investiq.models.valuation import ValuationRecord, ValuationRun
from investiq.schemas.martin import (
    MartinAnswer,
    MartinConversationOut,
    MartinConversationPage,
    MartinInput,
    MartinPlan,
    MartinSource,
    MartinTurnOut,
    MartinTurnPage,
)
from investiq.services.coach import CoachService, evidence_hash
from investiq.services.market import decode_cursor, encode_cursor, fingerprint

ACTIVE = ("queued", "running")


def answer_for(plan: MartinPlan, sources: list[MartinSource]) -> MartinAnswer:
    available = {s.id: s for s in sources}
    if (
        len(set(plan.source_ids)) != len(plan.source_ids)
        or not set(plan.source_ids) <= available.keys()
    ):
        raise AppError(422, "invalid_model_output", "Martin returned unsupported evidence")
    plan = complete_personal_citations(plan, sources)
    selected = [available[i] for i in plan.source_ids]
    reply, follow_up = plan.reply.strip(), plan.follow_up.strip()
    if plan.intent == "out_of_scope":
        selected = []
        reply = (
            "I can help with investing concepts and your own simulation results. "
            "I can’t recommend real trades, predict prices or access another learner’s "
            "private data."
        )
    elif plan.intent == "personal_assessment":
        owned = [s for s in selected if s.kind in {"performance", "status"}]
        if not owned:
            # Never substitute a general definition or unsupported praise for a personal review.
            owned = [s for s in sources if s.kind == "status"][:1]
            selected = owned
            reply = (
                "I can’t assess your portfolio from the evidence linked to this answer yet. "
                "Choose a contest with published results so I can review your own allocation."
            )
            follow_up = "Which contest would you like me to review?"
        elif not any(s.kind == "performance" for s in owned):
            selected = owned
            reply = (
                "I can’t assess your portfolio yet because there are no published "
                "portfolio results in this context. Once you confirm a portfolio and its "
                "valuation is published, I can review it using your saved results."
            )
            follow_up = "Have you submitted a portfolio to a contest yet?"
        else:
            if not personal_metrics_supported(reply, owned):
                raise AppError(
                    422, "invalid_model_output", "Personal metrics must come from saved evidence"
                )
    elif plan.intent in {"explanation", "benefits", "comparison"}:
        selected = [s for s in selected if s.kind == "lesson"]
    if not selected and plan.intent not in {"personal_assessment", "out_of_scope"}:
        reply = (
            "I don’t have enough approved information to answer that confidently yet. "
            "Could you narrow down which part you’d like to understand?"
        )
    return MartinAnswer(
        introduction=reply,
        sources=selected,
        follow_up=follow_up,
        intent=plan.intent,
        limitation=(
            "Educational AI explanation grounded in the linked sources. "
            "Personal metrics use saved simulation snapshots; they do not "
            "establish causes, intentions or future returns."
        ),
    )


class MartinService:
    def __init__(self, coach: CoachService, provider: MartinProvider | None = None) -> None:
        self.coach, self.identity, self.factory = coach, coach.identity, coach.factory
        self.settings, self.provider = coach.settings, provider

    @staticmethod
    def cursor(value: str, context: str) -> tuple[datetime, UUID]:
        stamp, identifier = decode_cursor(value, context)
        try:
            parsed = datetime.fromisoformat(stamp)
            if parsed.tzinfo is None:
                raise ValueError
            return parsed, identifier
        except ValueError:
            raise AppError(422, "invalid_cursor", "Use a cursor from this chat history") from None

    async def conversation(
        self, db: AsyncSession, user_id: UUID, identifier: UUID
    ) -> MartinConversation:
        conversation = await db.scalar(
            select(MartinConversation).where(
                MartinConversation.id == identifier, MartinConversation.user_id == user_id
            )
        )
        if not conversation:
            raise AppError(404, "conversation_not_found", "Conversation not found")
        return conversation

    async def owned_turn(self, db: AsyncSession, user_id: UUID, identifier: UUID) -> MartinTurn:
        turn = await db.scalar(
            select(MartinTurn)
            .where(MartinTurn.id == identifier, MartinTurn.user_id == user_id)
            .with_for_update()
        )
        if not turn:
            raise AppError(404, "question_not_found", "Question not found")
        return turn

    async def sources(
        self, db: AsyncSession, principal: Principal, data: MartinInput
    ) -> list[MartinSource]:
        result: list[MartinSource] = []
        if data.mode == "performance":
            ids: list[UUID]
            if data.contest_id:
                member = await db.scalar(
                    select(ContestMembership.id).where(
                        ContestMembership.user_id == principal.user_id,
                        ContestMembership.contest_id == data.contest_id,
                    )
                )
                if not member:
                    raise AppError(
                        404,
                        "performance_not_found",
                        "Join this contest to discuss your own results",
                    )
                ids = [data.contest_id]
            else:
                ids = list(
                    (
                        await db.scalars(
                            select(ValuationRun.contest_id)
                            .join(ValuationRecord, ValuationRecord.run_id == ValuationRun.id)
                            .join(
                                ContestMembership,
                                ContestMembership.id == ValuationRecord.membership_id,
                            )
                            .where(
                                ContestMembership.user_id == principal.user_id,
                                ValuationRun.status == "succeeded",
                            )
                            .group_by(ValuationRun.contest_id)
                            .order_by(
                                func.max(ValuationRun.session_date).desc(), ValuationRun.contest_id
                            )
                            .limit(3)
                        )
                    ).all()
                )
            for contest_id in ids:
                name = await db.scalar(select(Contest.name).where(Contest.id == contest_id))
                try:
                    evidence = await self.coach.source(db, principal, contest_id)
                except AppError as exc:
                    if exc.code != "coach_evidence_pending":
                        raise
                    result.append(
                        MartinSource(
                            id=f"pending:{contest_id}",
                            kind="status",
                            title=name or "Contest",
                            text=(
                                "Your contest has no published portfolio valuation yet. "
                                "Confirm a submission and wait for published results "
                                "before reviewing performance."
                            ),
                            href=f"performance/{contest_id}",
                            contest_id=contest_id,
                        )
                    )
                    continue
                for fact in evidence.facts:
                    result.append(
                        MartinSource(
                            id=f"{evidence.record_id}:{fact.id}",
                            kind="performance",
                            title=f"{name} · {evidence.session_date}",
                            text=fact.text,
                            href=f"performance/{contest_id}",
                            session_date=str(evidence.session_date),
                            is_current=evidence.is_current,
                            is_final=evidence.is_final,
                            contest_id=contest_id,
                        )
                    )
                previous = (
                    await db.execute(
                        select(ValuationRecord, ValuationRun.session_date)
                        .join(ValuationRun, ValuationRun.id == ValuationRecord.run_id)
                        .join(
                            ContestMembership, ContestMembership.id == ValuationRecord.membership_id
                        )
                        .where(
                            ContestMembership.user_id == principal.user_id,
                            ValuationRun.contest_id == contest_id,
                            ValuationRun.status == "succeeded",
                            ValuationRecord.id != evidence.record_id,
                        )
                        .order_by(ValuationRun.session_date.desc())
                        .limit(3)
                    )
                ).all()
                for record, date in previous:
                    result.append(
                        MartinSource(
                            id=f"{record.id}:daily",
                            kind="performance",
                            title=f"{name} · {date}",
                            text=(
                                f"At this daily close, your portfolio value was "
                                f"{number(record.total_value)} virtual INR, return "
                                f"{number(record.return_pct)}%, benchmark return "
                                f"{number(record.benchmark_return_pct)}% and rank {record.rank}."
                            ),
                            href=f"performance/{contest_id}",
                            session_date=str(date),
                            is_current=False,
                            is_final=False,
                            contest_id=contest_id,
                        )
                    )
            if not result:
                result.append(
                    MartinSource(
                        id="no-results",
                        kind="status",
                        title="Your results",
                        text=(
                            "No published portfolio valuations are available for your account. "
                            "Join a contest, confirm a portfolio "
                            "and wait for its first published valuation."
                        ),
                        href="my-contests",
                    )
                )
        versions = (
            await db.scalars(
                select(LessonVersion)
                .where(LessonVersion.published_at <= now())
                .order_by(LessonVersion.lesson_id, LessonVersion.version.desc())
            )
        ).all()
        seen: set[UUID] = set()
        lessons: list[MartinSource] = []
        for version in versions:
            if version.lesson_id in seen:
                continue
            seen.add(version.lesson_id)
            for index, paragraph in enumerate(version.paragraphs):
                if len(paragraph) <= 1800:
                    lessons.append(
                        MartinSource(
                            id=f"lesson:{version.id}:{index}",
                            kind="lesson",
                            title=f"{version.title} · version {version.version}",
                            text=paragraph,
                            href=f"academy/{version.lesson_id}",
                        )
                    )
        # Bounded lexical retrieval, with the model selecting relevant approved passages.
        # Titles/paragraphs only: never quiz keys, journals, identity or community text.
        terms = set(re.findall(r"[a-z]{3,}", data.question.lower())) - {
            "the",
            "what",
            "how",
            "does",
            "and",
            "can",
            "you",
            "that",
            "with",
        }
        lessons.sort(
            key=lambda s: (-sum(t in (s.title + " " + s.text).lower() for t in terms), s.id)
        )
        # Reserve lesson space even when several contests supply extensive history.
        # Round-robin the owned contexts so a single contest cannot consume the budget.
        groups: dict[UUID | None, list[MartinSource]] = {}
        for source in result:
            groups.setdefault(source.contest_id, []).append(source)
        result = []
        for index in range(max((len(group) for group in groups.values()), default=0)):
            for group in groups.values():
                if index < len(group) and len(result) < 30:
                    result.append(group[index])
        result.extend(lessons[:18])
        if not result:
            raise AppError(
                503,
                "martin_curriculum_unavailable",
                "Initialize Academy lessons before asking Martin",
            )
        # Performance facts remain first so large curricula cannot crowd out owned results.
        selected: list[MartinSource] = []
        size = 0
        for source in result:
            if len(selected) >= 48 or size + len(source.text) > 16000:
                break
            selected.append(source)
            size += len(source.text)
        return selected

    @staticmethod
    async def queue_space(db: AsyncSession) -> None:
        await db.execute(text("SELECT pg_advisory_xact_lock(742022)"))
        count = await db.scalar(
            select(func.count()).select_from(MartinTurn).where(MartinTurn.status.in_(ACTIVE))
        )
        if (count or 0) >= 100:
            raise AppError(503, "martin_busy", "Martin is busy. Please try again shortly")

    async def create(self, principal: Principal, data: MartinInput, key: UUID) -> MartinTurnOut:
        digest = evidence_hash(data.model_dump(mode="json"))
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            if not user.email_verified_at:
                raise AppError(
                    403, "verification_required", "Verify your email before asking Martin"
                )
            replay = await db.scalar(
                select(MartinTurn).where(
                    MartinTurn.user_id == user.id, MartinTurn.request_key == key
                )
            )
            if replay:
                if replay.request_hash != digest:
                    raise AppError(
                        409,
                        "idempotency_conflict",
                        "This question key was already used for a different request",
                    )
                return MartinTurnOut.model_validate(replay)
            config = self.coach.configuration()
            if not config.enabled:
                raise AppError(503, "martin_disabled", "Martin's AI provider is not configured")
            if await db.scalar(
                select(MartinTurn.id)
                .where(MartinTurn.user_id == user.id, MartinTurn.status.in_(ACTIVE))
                .limit(1)
            ):
                raise AppError(
                    409,
                    "martin_question_active",
                    "Wait for your current question or cancel it before asking another",
                )
            await self.queue_space(db)
            conversation = (
                await self.conversation(db, user.id, data.conversation_id)
                if data.conversation_id
                else None
            )
            if conversation and (
                conversation.mode != data.mode or conversation.contest_id != data.contest_id
            ):
                raise AppError(
                    409, "conversation_scope", "Start a new chat to change its topic or contest"
                )
            if (
                conversation
                and (
                    await db.scalar(
                        select(func.count())
                        .select_from(MartinTurn)
                        .where(MartinTurn.conversation_id == conversation.id)
                    )
                    or 0
                )
                >= 100
            ):
                raise AppError(
                    409, "conversation_full", "Start a new chat to continue this discussion"
                )
            retrieval = data
            if conversation:
                last = await db.scalar(
                    select(MartinTurn)
                    .where(MartinTurn.conversation_id == conversation.id)
                    .order_by(MartinTurn.created_at.desc())
                    .limit(1)
                )
                if last:
                    retrieval = data.model_copy(
                        update={"question": last.question[:500] + " " + data.question}
                    )
            # Martin interprets intent against both lesson and bounded owned-result context.
            # The UI mode selects a contest scope; it must not prevent a personal follow-up.
            retrieval = retrieval.model_copy(update={"mode": "performance"})
            sources = await self.sources(db, principal, retrieval)
            if not conversation:
                conversation = MartinConversation(
                    user_id=user.id,
                    title=data.question[:80],
                    mode=data.mode,
                    contest_id=data.contest_id,
                )
                db.add(conversation)
                await db.flush()
            conversation.updated_at = now()
            turn = MartinTurn(
                user_id=user.id,
                conversation_id=conversation.id,
                request_key=key,
                request_hash=digest,
                question=data.question,
                evidence=[s.model_dump(mode="json") for s in sources],
                provider=config.provider,
                model=config.model,
            )
            db.add(turn)
            await db.flush()
            return MartinTurnOut.model_validate(turn)

    async def conversations(
        self, principal: Principal, cursor: str | None, limit: int
    ) -> MartinConversationPage:
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            query = select(MartinConversation).where(MartinConversation.user_id == user.id)
            context = fingerprint({"user": str(user.id), "scope": "martin-conversations"})
            if cursor:
                stamp, identifier = self.cursor(cursor, context)
                query = query.where(
                    tuple_(MartinConversation.updated_at, MartinConversation.id)
                    < (stamp, identifier)
                )
            rows = list(
                (
                    await db.scalars(
                        query.order_by(
                            MartinConversation.updated_at.desc(), MartinConversation.id.desc()
                        ).limit(limit + 1)
                    )
                ).all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            return MartinConversationPage(
                items=[MartinConversationOut.model_validate(r) for r in rows],
                next_cursor=encode_cursor(rows[-1].updated_at.isoformat(), rows[-1].id, context)
                if more
                else None,
            )

    async def turns(
        self, principal: Principal, identifier: UUID, cursor: str | None, limit: int
    ) -> MartinTurnPage:
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            conversation = await self.conversation(db, user.id, identifier)
            query = select(MartinTurn).where(
                MartinTurn.conversation_id == identifier, MartinTurn.user_id == user.id
            )
            context = fingerprint({"user": str(user.id), "conversation": str(identifier)})
            if cursor:
                stamp, last = self.cursor(cursor, context)
                query = query.where(tuple_(MartinTurn.created_at, MartinTurn.id) < (stamp, last))
            rows = list(
                (
                    await db.scalars(
                        query.order_by(MartinTurn.created_at.desc(), MartinTurn.id.desc()).limit(
                            limit + 1
                        )
                    )
                ).all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            return MartinTurnPage(
                conversation=MartinConversationOut.model_validate(conversation),
                items=[MartinTurnOut.model_validate(r) for r in rows],
                next_cursor=encode_cursor(rows[-1].created_at.isoformat(), rows[-1].id, context)
                if more
                else None,
            )

    async def control(self, principal: Principal, identifier: UUID, action: str) -> MartinTurnOut:
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            turn = await self.owned_turn(db, user.id, identifier)
            if action == "cancel" and turn.status in ACTIVE:
                turn.status, turn.lease_token, turn.leased_until = "cancelled", None, None
            elif action == "retry" and turn.status == "failed":
                if turn.attempts >= 3:
                    raise AppError(
                        409,
                        "martin_retry_exhausted",
                        "Start a new question after three failed attempts",
                    )
                newer = await db.scalar(
                    select(MartinTurn.id)
                    .where(
                        MartinTurn.conversation_id == turn.conversation_id,
                        MartinTurn.created_at > turn.created_at,
                    )
                    .limit(1)
                )
                if newer or await db.scalar(
                    select(MartinTurn.id)
                    .where(MartinTurn.user_id == user.id, MartinTurn.status.in_(ACTIVE))
                    .limit(1)
                ):
                    raise AppError(
                        409,
                        "martin_question_active",
                        "Retry the latest question when no other question is processing",
                    )
                if not user.email_verified_at:
                    raise AppError(
                        403, "verification_required", "Verify your email before asking Martin"
                    )
                config = self.coach.configuration()
                if not config.enabled or (config.provider, config.model) != (
                    turn.provider,
                    turn.model,
                ):
                    raise AppError(
                        409,
                        "provider_configuration_changed",
                        "Start a new question after the AI configuration changes",
                    )
                await self.queue_space(db)
                turn.status, turn.error_code = "queued", None
            return MartinTurnOut.model_validate(turn)

    async def delete(self, principal: Principal, identifier: UUID) -> None:
        async with self.factory() as db, db.begin():
            user = await self.identity.authenticated_user(db, principal)
            conversation = await self.conversation(db, user.id, identifier)
            await db.delete(conversation)

    async def allowed(self, db: AsyncSession, turn: MartinTurn) -> bool:
        user = await db.get(User, turn.user_id)
        if not user or not user.active or not user.email_verified_at:
            return False
        contests = {UUID(s["contest_id"]) for s in turn.evidence if s.get("contest_id")}
        if contests:
            found = set(
                (
                    await db.scalars(
                        select(ContestMembership.contest_id).where(
                            ContestMembership.user_id == user.id,
                            ContestMembership.contest_id.in_(contests),
                        )
                    )
                ).all()
            )
            if contests != found:
                return False
        return True

    async def sweep(self, identifier: UUID | None = None) -> dict[str, int]:
        from investiq.services.ai_budget import reserve_generation

        async with self.factory() as db, db.begin():
            await db.execute(
                update(MartinTurn)
                .where(
                    MartinTurn.status == "running",
                    MartinTurn.leased_until <= now(),
                    *([MartinTurn.id == identifier] if identifier else []),
                )
                .values(
                    status="failed",
                    error_code="worker_interrupted",
                    lease_token=None,
                    leased_until=None,
                )
            )
            turn = await db.scalar(
                select(MartinTurn)
                .where(
                    MartinTurn.status == "queued",
                    *([MartinTurn.id == identifier] if identifier else []),
                )
                .order_by(MartinTurn.created_at, MartinTurn.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if not turn:
                return {"processed": 0}
            if not await self.allowed(db, turn):
                turn.status, turn.error_code = "failed", "owner_unavailable"
                return {"processed": 1}
            config = self.coach.configuration()
            if not config.enabled or (config.provider, config.model) != (turn.provider, turn.model):
                turn.status, turn.error_code = "failed", "provider_configuration_changed"
                return {"processed": 1}
            token = uuid4()
            turn.status, turn.lease_token, turn.leased_until = (
                "running",
                token,
                now() + timedelta(seconds=120),
            )
            turn.attempts += 1
            identifier = turn.id
            provider, model, question = turn.provider, turn.model, turn.question
            sources = [MartinSource.model_validate(s) for s in turn.evidence]
            previous = list(
                (
                    await db.scalars(
                        select(MartinTurn)
                        .where(
                            MartinTurn.conversation_id == turn.conversation_id,
                            MartinTurn.status == "succeeded",
                            MartinTurn.created_at < turn.created_at,
                        )
                        .order_by(MartinTurn.created_at.desc())
                        .limit(3)
                    )
                ).all()
            )
            history = [
                {
                    "question": p.question[:500],
                    "answer": (p.answer or {}).get("introduction", "")[:1000],
                    "sources": [
                        {"id": s["id"], "text": s["text"][:400]}
                        for s in (p.answer or {}).get("sources", [])
                    ],
                    "follow_up": (p.answer or {}).get("follow_up", ""),
                }
                for p in reversed(previous)
            ]
        answer: MartinAnswer | None = None
        error = None
        generated = None
        try:
            async with asyncio.timeout(75):
                await reserve_generation(self.identity)
                generated = await (
                    self.provider or LangChainMartin(self.settings, provider, model)
                ).generate(question, sources, history)
                answer = answer_for(generated.plan, sources)
        except AppError as exc:
            error = (
                exc.code
                if exc.code
                in {
                    "provider_timeout",
                    "invalid_model_output",
                    "provider_unavailable",
                    "daily_ai_limit",
                    "rate_limit_unavailable",
                }
                else "provider_unavailable"
            )
        except TimeoutError:
            error = "provider_timeout"
        except Exception:
            error = "provider_unavailable"
        async with self.factory() as db, db.begin():
            turn = await db.scalar(
                select(MartinTurn).where(MartinTurn.id == identifier).with_for_update()
            )
            if not turn or turn.status != "running" or turn.lease_token != token:
                return {"processed": 1}
            if not await self.allowed(db, turn):
                answer, error = None, "owner_unavailable"
            turn.lease_token, turn.leased_until = None, None
            turn.status = "succeeded" if answer else "failed"
            turn.answer = answer.model_dump(mode="json") if answer else None
            turn.error_code = error
            if generated:
                turn.input_tokens, turn.output_tokens, turn.latency_ms = (
                    generated.input_tokens,
                    generated.output_tokens,
                    generated.latency_ms,
                )
        return {"processed": 1}
