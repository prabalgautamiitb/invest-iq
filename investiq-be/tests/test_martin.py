import asyncio
import re
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.adapters.martin import MartinGeneration
from investiq.core.errors import AppError
from investiq.core.security import now
from investiq.db.session import make_engine
from investiq.main import create_app
from investiq.models.identity import User
from investiq.models.martin import MartinTurn
from investiq.schemas.martin import MartinPlan
from investiq.services.learning_seed import seed_curriculum
from investiq.services.martin import answer_for
from tests.conftest import CapturedMailer
from tests.helpers import test_client as api_client
from tests.test_contest import verified
from tests.test_identity import csrf
from tests.test_portfolio import config
from tests.test_valuation import ENTRY, FIRST, scenario


@dataclass
class MockMartin:
    fail: bool = False
    invalid: bool = False
    started: asyncio.Event = field(default_factory=asyncio.Event)
    gate: asyncio.Event | None = None
    calls: list = field(default_factory=list)

    async def generate(self, question, sources, history):
        self.calls.append((question, sources, history))
        self.started.set()
        if self.gate:
            await self.gate.wait()
        if self.fail:
            raise AppError(503, "provider_timeout", "private provider payload must not leak")
        personal = bool(re.search(r"\b(i|my|mine)\b", question, re.IGNORECASE))
        kind = {"performance", "status"} if personal else {"lesson"}
        source = next((s for s in sources if s.kind in kind), sources[0])
        benefits = question.lower().startswith(("is diversification good", "can diversification"))
        intent = "personal_assessment" if personal else "benefits" if benefits else "explanation"
        reply = (
            "Your portfolio evidence needs a review of concentration and sector spread."
            if personal
            else (
                "Yes, diversification can reduce exposure to individual companies, "
                "but market risk remains."
            )
            if benefits
            else "Diversification spreads exposure across different holdings."
        )
        return MartinGeneration(
            MartinPlan(
                intent=intent,
                reply=reply,
                source_ids=["invented"] if self.invalid else [source.id],
                follow_up="Would you like to explore the source in more detail?",
            ),
            100,
            30,
            20,
        )


@pytest_asyncio.fixture
async def martin_settings(market_settings):
    settings = config(market_settings).model_copy(update={"martin_request_limit": 1000})
    engine = make_engine(settings)
    try:
        await seed_curriculum(async_sessionmaker(engine, expire_on_commit=False), settings)
    finally:
        await engine.dispose()
    return settings


async def ask(client, question="What is diversification?", key=None, **extra):
    return await client.post(
        "/api/v1/me/martin/turns",
        json={"question": question, **extra},
        headers={**await csrf(client), "Idempotency-Key": key or str(uuid4())},
    )


async def chat(client, identifier, **params):
    return await client.get(f"/api/v1/me/martin/conversations/{identifier}", params=params)


async def test_free_demo_answers_only_the_requested_turn_without_a_worker(martin_settings):
    settings = martin_settings.model_copy(
        update={"deployment_mode": "free_demo", "free_demo_ai_daily_limit": 1}
    )
    model = MockMartin()
    app = create_app(settings, CapturedMailer(), martin_provider=model)
    async with api_client(app) as first, api_client(app) as second:
        await verified(first, app.state.identity.mailer)
        # Leave another user's earlier turn queued, as after an interrupted request.
        app.state.martin.settings = settings.model_copy(update={"deployment_mode": "worker"})
        waiting = (await ask(first)).json()
        assert waiting["status"] == "queued"
        app.state.martin.settings = settings
        await verified(second, app.state.identity.mailer)
        key = str(uuid4())
        answer = await ask(second, key=key)
        assert answer.status_code == 202 and answer.json()["status"] == "succeeded"
        assert len(model.calls) == 1
        replay = await ask(second, key=key)
        assert replay.json()["id"] == answer.json()["id"] and len(model.calls) == 1
        # A different account's queued request must not have been processed.
        history = (await chat(first, waiting["conversation_id"])).json()
        assert history["items"][0]["status"] == "queued"
        denied = (await ask(second, question="Is diversification good?")).json()
        assert denied["status"] == "failed" and denied["error_code"] == "daily_ai_limit"
        assert len(model.calls) == 1
        retry = await second.post(
            f"/api/v1/me/martin/turns/{denied['id']}/retry", headers=await csrf(second)
        )
        assert retry.status_code == 200 and retry.json()["error_code"] == "daily_ai_limit"
        assert len(model.calls) == 1


async def test_private_chat_idempotency_multiturn_cursor_delete_and_auth(martin_settings):
    model = MockMartin()
    app = create_app(martin_settings, CapturedMailer(), martin_provider=model)
    async with api_client(app) as client:
        user = await verified(client, app.state.identity.mailer)
        key = str(uuid4())
        headers = {**await csrf(client), "Idempotency-Key": key}
        responses = await asyncio.gather(
            *[
                client.post(
                    "/api/v1/me/martin/turns",
                    json={"question": "What is diversification?"},
                    headers=headers,
                )
                for _ in range(3)
            ]
        )
        assert all(r.status_code == 202 for r in responses), [r.text for r in responses]
        assert len({r.json()["id"] for r in responses}) == 1
        turn = responses[0].json()
        conversation = turn["conversation_id"]
        assert (await ask(client, question="Different question", key=key)).status_code == 409
        assert (await ask(client)).status_code == 409
        processed = await asyncio.gather(app.state.martin.sweep(), app.state.martin.sweep())
        assert sum(r["processed"] for r in processed) == 1 and len(model.calls) == 1
        result = (await chat(client, conversation)).json()["items"][0]
        assert (
            result["status"] == "succeeded" and result["answer"]["sources"][0]["kind"] == "lesson"
        )
        assert all(
            "questions" not in s.model_dump() and user["email"] not in s.text
            for s in model.calls[0][1]
        )
        second = await ask(client, question="Explain that further", conversation_id=conversation)
        assert second.status_code == 202, second.text
        await app.state.martin.sweep()
        assert (
            len(model.calls[1][2]) == 1
            and model.calls[1][2][0]["question"] == "What is diversification?"
        )
        page = (await chat(client, conversation, limit=1)).json()
        assert page["next_cursor"] and len(page["items"]) == 1
        older = await chat(client, conversation, limit=1, cursor=page["next_cursor"])
        assert older.status_code == 200 and older.json()["items"][0]["id"] == turn["id"]
        assert (await chat(client, conversation, cursor="not-a-cursor")).status_code == 422
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as other:
            assert (await chat(other, conversation)).status_code == 401
            await verified(other, app.state.identity.mailer)
            assert (await chat(other, conversation)).status_code == 404
            assert (await ask(other, conversation_id=conversation)).status_code == 404
            assert (
                await other.post(
                    f"/api/v1/me/martin/turns/{turn['id']}/cancel", headers=await csrf(other)
                )
            ).status_code == 404
            assert (
                await other.delete(
                    f"/api/v1/me/martin/conversations/{conversation}", headers=await csrf(other)
                )
            ).status_code == 404
        assert (
            await client.post(
                "/api/v1/me/martin/turns",
                json={"question": "x"},
                headers={"Idempotency-Key": str(uuid4())},
            )
        ).status_code == 403
        assert (await ask(client, question="x", user_id=user["id"])).status_code == 422
        assert (await ask(client, question="x" * 1001)).status_code == 422
        assert (
            await client.delete(
                f"/api/v1/me/martin/conversations/{conversation}", headers=await csrf(client)
            )
        ).status_code == 204
        assert (await chat(client, conversation)).status_code == 404
        async with app.state.sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(MartinTurn)
                    .where(MartinTurn.conversation_id == UUID(conversation))
                )
                == 0
            )


async def test_performance_missing_owned_snapshots_and_no_foreign_evidence(martin_settings):
    clock = [ENTRY]
    model = MockMartin()
    app = create_app(
        martin_settings, CapturedMailer(), contest_clock=lambda: clock[0], martin_provider=model
    )
    async with api_client(app) as client:
        await verified(client, app.state.identity.mailer)
        missing = (await ask(client, question="How did I perform?", mode="performance")).json()
        await app.state.martin.sweep()
        result = (await chat(client, missing["conversation_id"])).json()["items"][0]
        assert "No published portfolio" in result["answer"]["sources"][0]["text"]
        contest, _, _, submission = await scenario(client)
        before = await ask(
            client, question="How did I perform?", mode="performance", contest_id=contest["id"]
        )
        assert before.status_code == 202, before.text
        await app.state.martin.sweep()
        assert model.calls[-1][1][0].kind == "status"
        clock[0] = FIRST
        await app.state.valuations.evaluate(UUID(contest["id"]))
        valued = await ask(
            client, question="How did I perform?", mode="performance", contest_id=contest["id"]
        )
        assert valued.status_code == 202, valued.text
        await app.state.martin.sweep()
        sources = model.calls[-1][1]
        assert any(s.kind == "performance" and s.session_date == "2026-10-15" for s in sources)
        assert all(s.contest_id in {None, UUID(contest["id"])} for s in sources)
        assert submission["id"] not in str(
            model.calls[-1]
        )  # no private journal or raw submission bundle
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as other:
            await verified(other, app.state.identity.mailer)
            assert (
                await ask(
                    other,
                    question="How did I perform?",
                    mode="performance",
                    contest_id=contest["id"],
                )
            ).status_code == 404
            own = (await ask(other, question="How did I perform?", mode="performance")).json()
            await app.state.martin.sweep()
            assert all(s.contest_id is None for s in model.calls[-1][1])
            assert (await chat(other, own["conversation_id"])).status_code == 200


async def test_invalid_answers_retries_timeout_cancel_lease_and_revoked_owner(martin_settings):
    model = MockMartin(invalid=True)
    app = create_app(martin_settings, CapturedMailer(), martin_provider=model)
    async with api_client(app) as client:
        user = await verified(client, app.state.identity.mailer)
        turn = (await ask(client)).json()
        identifier = turn["id"]
        conversation = turn["conversation_id"]
        await app.state.martin.sweep()
        result = (await chat(client, conversation)).json()["items"][0]
        assert (
            result["status"] == "failed"
            and result["answer"] is None
            and result["error_code"] == "invalid_model_output"
        )
        path = f"/api/v1/me/martin/turns/{identifier}"
        model.invalid = False
        model.fail = True
        assert (await client.post(path + "/retry", headers=await csrf(client))).json()[
            "status"
        ] == "queued"
        await app.state.martin.sweep()
        assert (await chat(client, conversation)).json()["items"][0][
            "error_code"
        ] == "provider_timeout"
        model.fail = False
        model.gate = asyncio.Event()
        model.started.clear()
        await client.post(path + "/retry", headers=await csrf(client))
        worker = asyncio.create_task(app.state.martin.sweep())
        await model.started.wait()
        assert (await client.post(path + "/cancel", headers=await csrf(client))).json()[
            "status"
        ] == "cancelled"
        model.gate.set()
        await worker
        assert (await chat(client, conversation)).json()["items"][0]["status"] == "cancelled"
        model.gate = None
        expired = (await ask(client)).json()
        async with app.state.sessions() as db, db.begin():
            await db.execute(
                update(MartinTurn)
                .where(MartinTurn.id == UUID(expired["id"]))
                .values(
                    status="running",
                    lease_token=uuid4(),
                    leased_until=now() - timedelta(seconds=1),
                    attempts=1,
                )
            )
        await app.state.martin.sweep()
        assert (await chat(client, expired["conversation_id"])).json()["items"][0][
            "error_code"
        ] == "worker_interrupted"
        blocked = (await ask(client)).json()
        async with app.state.sessions() as db, db.begin():
            await db.execute(update(User).where(User.id == UUID(user["id"])).values(active=False))
        count = len(model.calls)
        await app.state.martin.sweep()
        assert len(model.calls) == count
        async with app.state.sessions() as db:
            row = await db.get(MartinTurn, UUID(blocked["id"]))
            assert row.status == "failed" and row.error_code == "owner_unavailable"
        assert (await chat(client, blocked["conversation_id"])).status_code == 401


async def test_question_intent_retrieves_personal_context_without_changing_chat_mode(
    martin_settings,
):
    clock, model = [ENTRY], MockMartin()
    app = create_app(
        martin_settings, CapturedMailer(), contest_clock=lambda: clock[0], martin_provider=model
    )
    async with api_client(app) as client:
        await verified(client, app.state.identity.mailer)
        # Personal assessment in the default learning mode must not reuse a definition.
        pending = (await ask(client, question="Am I good at diversification?")).json()
        await app.state.martin.sweep()
        missing = (await chat(client, pending["conversation_id"])).json()["items"][0]["answer"]
        assert missing["intent"] == "personal_assessment"
        assert "can’t assess your portfolio yet" in missing["introduction"]
        assert all(s["kind"] == "status" for s in missing["sources"])
        contest, _, _, _ = await scenario(client)
        clock[0] = FIRST
        await app.state.valuations.evaluate(UUID(contest["id"]))
        definition = (await ask(client, question="What is diversification?")).json()
        conversation = definition["conversation_id"]
        await app.state.martin.sweep()
        explanation = (await chat(client, conversation)).json()["items"][0]["answer"]
        personal = await ask(
            client, question="Am I good at diversification?", conversation_id=conversation
        )
        assert personal.status_code == 202
        await app.state.martin.sweep()
        assessment = (await chat(client, conversation)).json()["items"][0]["answer"]
        assert assessment["intent"] == "personal_assessment"
        assert any(
            s["kind"] == "performance" and s["contest_id"] == contest["id"]
            for s in assessment["sources"]
        )
        assert (await chat(client, conversation)).json()["conversation"]["mode"] == "learning"
        assert model.calls[-1][2][-1]["answer"] == explanation["introduction"]
        await ask(client, question="Is diversification good?", conversation_id=conversation)
        await app.state.martin.sweep()
        benefits = (await chat(client, conversation)).json()["items"][0]["answer"]
        assert benefits["intent"] == "benefits"
        assert all(s["kind"] == "lesson" for s in benefits["sources"])
        assert len({a["introduction"] for a in [explanation, assessment, benefits]}) == 3
        assert assessment["introduction"] != explanation["sources"][0]["text"]


def test_personal_answer_requires_owned_evidence_and_rejects_invented_scores():
    from investiq.schemas.martin import MartinSource

    performance = MartinSource(
        id="owned",
        kind="performance",
        title="Snapshot",
        text="Your holdings span sectors.",
        href="my-contests",
    )
    plan = MartinPlan(
        intent="personal_assessment",
        reply="Your diversification score is 95.",
        source_ids=["owned"],
        follow_up="Want to review it?",
    )
    with pytest.raises(AppError, match="Personal metrics"):
        answer_for(plan, [performance])
    lesson = performance.model_copy(update={"id": "lesson", "kind": "lesson"})
    unsupported = plan.model_copy(
        update={"source_ids": ["lesson"], "reply": "You are very good at diversification."}
    )
    safe = answer_for(unsupported, [lesson])
    assert "can’t assess" in safe.introduction and not safe.sources


@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_provider_corrects_unsupported_personal_metrics_once(monkeypatch, repair_succeeds):
    from langchain_core.messages import AIMessage

    from investiq.adapters.martin import LangChainMartin
    from investiq.core.config import Settings
    from investiq.schemas.martin import MartinSource

    calls = []

    class StubChat:
        def __init__(self, **kwargs):
            pass

        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, messages):
            calls.append(list(messages))
            reply = (
                "Your largest position is 20 percent."
                if repair_succeeds and len(calls) == 2
                else "Your diversification score is 95."
            )
            return {
                "parsed": MartinPlan(
                    intent="personal_assessment",
                    reply=reply,
                    source_ids=["S1"],
                    follow_up="Want to review the sector spread?",
                ),
                "raw": AIMessage(""),
                "parsing_error": None,
            }

    monkeypatch.setattr("langchain_ollama.ChatOllama", StubChat)
    provider = LangChainMartin(Settings(), "ollama", "stub")
    sources = [
        MartinSource(
            id="owned",
            kind="performance",
            title="Snapshot",
            text="Your largest position is 20 percent.",
            href="my-contests",
        )
    ]
    if repair_succeeds:
        result = await provider.generate("How about mine?", sources, [])
        assert result.plan.source_ids == ["owned"]
        assert answer_for(result.plan, sources).introduction == result.plan.reply
    else:
        with pytest.raises(AppError, match="verify personal evidence"):
            await provider.generate("How about mine?", sources, [])
    assert len(calls) == 2
    assert calls[0][-1].content.endswith("Latest question:\nHow about mine?")


def test_personal_summary_completes_metric_citations_from_the_same_snapshot():
    from investiq.schemas.martin import MartinSource

    contest_id = uuid4()
    sources = [
        MartinSource(
            id=identifier,
            kind="performance",
            title="Contest snapshot",
            text=text,
            href="my-contests",
            contest_id=contest_id,
            session_date="2026-10-16",
        )
        for identifier, text in [
            ("value", "Portfolio value is 100250 virtual INR."),
            ("return", "Portfolio return is 0.25%."),
            ("rank", "Snapshot rank is 2 among 7 portfolios."),
            ("benchmark", "Benchmark return is 0.10%; excess return is 0.15 percentage points."),
        ]
    ]
    plan = MartinPlan(
        intent="personal_assessment",
        reply=(
            "Your return was 0.25%, with rank 2 among 7 portfolios. "
            "Your value was 100250 virtual INR, and excess return was 0.15 percentage points."
        ),
        source_ids=["value", "return", "rank"],
        follow_up="Would you like to review concentration next?",
    )
    answer = answer_for(plan, sources)
    assert answer.introduction == plan.reply
    assert [source.id for source in answer.sources] == ["value", "return", "rank", "benchmark"]
    assert plan.source_ids == ["value", "return", "rank"]
    for other in [
        sources[-1].model_copy(update={"contest_id": uuid4()}),
        sources[-1].model_copy(update={"session_date": "2026-10-15"}),
        sources[-1].model_copy(update={"text": "No benchmark return is published."}),
    ]:
        with pytest.raises(AppError, match="Personal metrics"):
            answer_for(plan, [*sources[:-1], other])
    invented = plan.model_copy(update={"reply": plan.reply + " Your skill score is 95."})
    with pytest.raises(AppError, match="Personal metrics"):
        answer_for(invented, sources)


async def test_selected_contest_performance_summary_persists_all_metric_citations(martin_settings):
    class SummaryModel:
        async def generate(self, question, sources, history):
            chosen = [
                next(s for s in sources if s.kind == "performance" and s.id.endswith(":" + name))
                for name in ["value", "return", "rank", "benchmark"]
            ]
            return MartinGeneration(
                MartinPlan(
                    intent="personal_assessment",
                    reply=" ".join(source.text for source in chosen),
                    source_ids=[source.id for source in chosen[:3]],
                    follow_up="Would you like to review your allocation next?",
                )
            )

    clock = [ENTRY]
    app = create_app(
        martin_settings,
        CapturedMailer(),
        contest_clock=lambda: clock[0],
        martin_provider=SummaryModel(),
    )
    async with api_client(app) as client:
        await verified(client, app.state.identity.mailer)
        contest, _, _, _ = await scenario(client)
        clock[0] = FIRST
        await app.state.valuations.evaluate(UUID(contest["id"]))
        queued = await ask(
            client,
            question="How did I perform in my last contest?",
            mode="performance",
            contest_id=contest["id"],
        )
        assert queued.status_code == 202
        await app.state.martin.sweep()
        turn = (await chat(client, queued.json()["conversation_id"])).json()["items"][0]
        assert turn["status"] == "succeeded"
        citations = turn["answer"]["sources"]
        assert {source["id"].rsplit(":", 1)[-1] for source in citations} == {
            "value",
            "return",
            "rank",
            "benchmark",
        }
        assert all(source["contest_id"] == contest["id"] for source in citations)
