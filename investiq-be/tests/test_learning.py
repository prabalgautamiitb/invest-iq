import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.main import create_app
from investiq.models.learning import (
    Course,
    LearningDay,
    LessonCompletion,
    LessonVersion,
    QuizAnswer,
    QuizAttempt,
    XpEvent,
)
from investiq.services.learning import streaks
from investiq.services.learning_seed import seed_curriculum
from tests.conftest import CapturedMailer, migrated_database
from tests.helpers import test_client as api_client
from tests.test_contest import verified
from tests.test_identity import csrf, register


@pytest_asyncio.fixture
async def learning_settings():
    async with migrated_database() as url:
        yield Settings(
            database_url=SecretStr(url),
            environment="test",
            auth_rate_limit=10000,
            csrf_rate_limit=10000,
            rate_limit_prefix=str(uuid4()),
        )


async def curriculum(app, client):
    await seed_curriculum(app.state.sessions, app.state.settings)
    data = (await client.get("/api/v1/courses")).json()["items"]
    return sorted(data, key=lambda c: c["slug"])


async def enroll(client, course):
    response = await client.post(
        f"/api/v1/courses/{course['id']}/enrollment", headers=await csrf(client)
    )
    assert response.status_code == 200, response.text


async def input_for(app, client, lesson_id, wrong=False):
    public = (await client.get(f"/api/v1/lessons/{lesson_id}")).json()
    async with app.state.sessions() as db:
        version = await db.get(LessonVersion, UUID(public["version_id"]))
        answers = [
            {
                "question_key": q["key"],
                "choice": (q["correct"] + 1) % len(q["options"]) if wrong else q["correct"],
            }
            for q in version.questions
        ]
    return {"version_id": public["version_id"], "answers": answers}


async def submit(client, lesson_id, data, key=None, headers=None):
    return await client.post(
        f"/api/v1/lessons/{lesson_id}/attempts",
        json=data,
        headers={**(headers or await csrf(client)), "Idempotency-Key": key or str(uuid4())},
    )


def test_streak_calendar_gaps_and_yesterday_grace():
    day = date(2026, 10, 20)
    assert streaks([], day) == (0, 0)
    assert streaks([day - timedelta(days=i) for i in (3, 2, 1)], day) == (3, 3)
    assert streaks([day - timedelta(days=i) for i in (5, 4, 3)], day) == (0, 3)
    assert streaks([day, day, day - timedelta(days=2)], day) == (1, 1)


async def test_content_seed_pagination_and_no_fake_activity(learning_settings):
    app = create_app(learning_settings, CapturedMailer())
    async with api_client(app) as client:
        courses = await curriculum(app, client)
        await seed_curriculum(app.state.sessions, learning_settings)
        assert len(courses) == 2 and sum(len(c["lessons"]) for c in courses) == 6
        first = (await client.get("/api/v1/courses?limit=1")).json()
        second = (
            await client.get("/api/v1/courses", params={"cursor": first["next_cursor"], "limit": 1})
        ).json()
        assert first["items"][0]["id"] != second["items"][0]["id"] and second["next_cursor"] is None
        assert (await client.get("/api/v1/courses?cursor=broken")).status_code == 422
        lesson = (await client.get("/api/v1/lessons/" + courses[0]["lessons"][0]["id"])).json()
        assert "correct" not in str(lesson["questions"]) and "explanation" not in str(
            lesson["questions"]
        )
        assert (await client.get("/api/v1/me/learning")).status_code == 401
        await register(client)
        p = (await client.get("/api/v1/me/learning")).json()
        assert p["xp"] == 0 and p["completed_lesson_ids"] == [] and p["achievements"] == []
        assert (
            await client.post(
                "/api/v1/courses/" + courses[0]["id"] + "/enrollment", headers=await csrf(client)
            )
        ).status_code == 403
        assert (await client.get("/api/v1/lessons/" + str(uuid4()))).status_code == 404
        with pytest.raises(AppError, match="development"):
            await seed_curriculum(
                app.state.sessions,
                learning_settings.model_copy(update={"environment": "production"}),
            )


async def test_server_scoring_validation_idempotency_and_private_history(learning_settings):
    mailer = CapturedMailer()
    app = create_app(learning_settings, mailer)
    async with api_client(app) as alice, api_client(create_app(learning_settings, mailer)) as bob:
        courses = await curriculum(app, alice)
        course = courses[0]
        lesson_id = course["lessons"][0]["id"]
        await verified(alice, mailer)
        await verified(bob, mailer)
        correct = await input_for(app, alice, lesson_id)
        wrong = await input_for(app, alice, lesson_id, True)
        assert (await submit(alice, lesson_id, correct)).status_code == 409
        await enroll(alice, course)
        await enroll(alice, course)
        assert (
            await alice.post(f"/api/v1/lessons/{lesson_id}/attempts", json=correct)
        ).status_code == 403
        forged = {**correct, "xp": 9999}
        assert (await submit(alice, lesson_id, forged)).status_code == 422
        for bad in [
            [],
            correct["answers"][:1],
            correct["answers"] * 2,
            [{"question_key": "forged", "choice": 0}],
            [{**correct["answers"][0], "choice": 9}, correct["answers"][1]],
            [{**correct["answers"][0], "choice": True}, correct["answers"][1]],
        ]:
            assert (await submit(alice, lesson_id, {**correct, "answers": bad})).status_code == 422
        failed = await submit(alice, lesson_id, wrong)
        assert (
            failed.status_code == 201
            and not failed.json()["passed"]
            and failed.json()["xp_awarded"] == 0
        )
        key = str(uuid4())
        passed = await submit(alice, lesson_id, correct, key)
        assert (
            passed.status_code == 201
            and passed.json()["passed"]
            and passed.json()["xp_awarded"] == 25
        )
        assert (
            await submit(
                alice, lesson_id, {**correct, "answers": list(reversed(correct["answers"]))}, key
            )
        ).json() == passed.json()
        assert (await submit(alice, lesson_id, wrong, key)).status_code == 409
        assert (await submit(alice, lesson_id, correct)).json()["xp_awarded"] == 0
        p = (await alice.get("/api/v1/me/learning")).json()
        assert p["xp"] == 25 and p["completed_lesson_ids"] == [lesson_id]
        assert len(p["enrolled_course_ids"]) == 1 and p["achievements"][0]["code"] == "first_lesson"
        assert (await bob.get("/api/v1/me/learning")).json()["xp"] == 0
        assert (await bob.get(f"/api/v1/lessons/{lesson_id}/attempts")).json()["items"] == []
        page = (await alice.get(f"/api/v1/lessons/{lesson_id}/attempts?limit=1")).json()
        assert len(page["items"]) == 1 and page["next_cursor"]
        assert (
            await bob.get(
                f"/api/v1/lessons/{lesson_id}/attempts", params={"cursor": page["next_cursor"]}
            )
        ).status_code == 422
        all_ids = {page["items"][0]["id"]}
        while page["next_cursor"]:
            page = (
                await alice.get(
                    f"/api/v1/lessons/{lesson_id}/attempts",
                    params={"cursor": page["next_cursor"], "limit": 1},
                )
            ).json()
            all_ids.update(a["id"] for a in page["items"])
        assert len(all_ids) == 3


async def test_parallel_retries_and_distinct_attempts_award_once(learning_settings):
    mailer = CapturedMailer()
    app = create_app(learning_settings, mailer)
    async with api_client(app) as client:
        course = (await curriculum(app, client))[0]
        await verified(client, mailer)
        await enroll(client, course)
        lesson_id = course["lessons"][0]["id"]
        data = await input_for(app, client, lesson_id)
        headers = await csrf(client)
        key = str(uuid4())
        results = await asyncio.gather(
            *(submit(client, lesson_id, data, key, headers) for _ in range(8))
        )
        assert all(r.status_code == 201 for r in results), [r.text for r in results]
        assert len({r.json()["id"] for r in results}) == 1
        results = await asyncio.gather(
            *(submit(client, lesson_id, data, headers=headers) for _ in range(8))
        )
        assert all(r.status_code == 201 and r.json()["xp_awarded"] == 0 for r in results)
        async with app.state.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(XpEvent)) == 1
            assert await db.scalar(select(func.count()).select_from(LessonCompletion)) == 1
            assert await db.scalar(select(func.count()).select_from(QuizAttempt)) == 9
            assert await db.scalar(select(func.count()).select_from(LearningDay)) == 1


async def test_ist_days_streaks_course_achievements_and_retake_no_day(learning_settings):
    clock = [datetime(2026, 10, 20, 18, 29, tzinfo=UTC)]
    mailer = CapturedMailer()
    app = create_app(learning_settings, mailer, learning_clock=lambda: clock[0])
    async with api_client(app) as client:
        course = (await curriculum(app, client))[0]
        await verified(client, mailer)
        await enroll(client, course)
        for index, instant in enumerate(
            [
                datetime(2026, 10, 20, 18, 29, tzinfo=UTC),
                datetime(2026, 10, 20, 18, 31, tzinfo=UTC),
                datetime(2026, 10, 21, 18, 31, tzinfo=UTC),
            ]
        ):
            clock[0] = instant
            lesson_id = course["lessons"][index]["id"]
            response = await submit(client, lesson_id, await input_for(app, client, lesson_id))
            assert response.status_code == 201, response.text
        p = (await client.get("/api/v1/me/learning")).json()
        assert (
            p["xp"] == 75 and p["current_streak"] == 3 and p["last_learning_date"] == "2026-10-22"
        )
        assert {a["code"] for a in p["achievements"]} == {
            "first_lesson",
            "first_course",
            "three_day_streak",
        }
        clock[0] = datetime(2026, 10, 24, 12, tzinfo=UTC)
        lesson_id = course["lessons"][0]["id"]
        assert (await submit(client, lesson_id, await input_for(app, client, lesson_id))).json()[
            "xp_awarded"
        ] == 0
        p = (await client.get("/api/v1/me/learning")).json()
        assert (
            p["current_streak"] == 0
            and p["longest_streak"] == 3
            and p["last_learning_date"] == "2026-10-22"
        )


async def test_versions_preserve_evidence_and_cannot_reaward(learning_settings):
    mailer = CapturedMailer()
    app = create_app(learning_settings, mailer)
    async with api_client(app) as client:
        course = (await curriculum(app, client))[0]
        lesson_id = course["lessons"][0]["id"]
        await verified(client, mailer)
        await enroll(client, course)
        data = await input_for(app, client, lesson_id)
        key = str(uuid4())
        original = (await submit(client, lesson_id, data, key)).json()
        async with app.state.sessions() as db, db.begin():
            old = await db.get(LessonVersion, UUID(data["version_id"]))
            db.add(
                LessonVersion(
                    lesson_id=old.lesson_id,
                    version=2,
                    title="Revised lesson",
                    paragraphs=old.paragraphs,
                    questions=old.questions,
                )
            )
        assert (await submit(client, lesson_id, data, key)).json() == original
        assert (await submit(client, lesson_id, data)).status_code == 409
        revised = await input_for(app, client, lesson_id)
        assert revised["version_id"] != data["version_id"]
        assert (await submit(client, lesson_id, revised)).json()["xp_awarded"] == 0
        assert (await client.get("/api/v1/me/learning")).json()["xp"] == 25
        history = (await client.get(f"/api/v1/lessons/{lesson_id}/attempts")).json()["items"]
        assert {a["version_id"] for a in history} == {data["version_id"], revised["version_id"]}


async def test_database_rejects_mutation_late_answers_and_incomplete_evidence(learning_settings):
    mailer = CapturedMailer()
    app = create_app(learning_settings, mailer)
    async with api_client(app) as client:
        course = (await curriculum(app, client))[0]
        lesson_id = course["lessons"][0]["id"]
        user = await verified(client, mailer)
        await enroll(client, course)
        data = await input_for(app, client, lesson_id)
        result = (await submit(client, lesson_id, data)).json()
        for model, values in [
            (Course, {"title": "Changed"}),
            (LessonVersion, {"title": "Changed"}),
            (QuizAttempt, {"xp_awarded": 500}),
            (XpEvent, {"amount": 500}),
        ]:
            with pytest.raises(IntegrityError):
                async with app.state.sessions() as db, db.begin():
                    await db.execute(update(model).values(**values))
        with pytest.raises(IntegrityError):
            async with app.state.sessions() as db, db.begin():
                db.add(
                    QuizAnswer(
                        attempt_id=UUID(result["id"]), question_key="extra", choice=0, correct=True
                    )
                )
        with pytest.raises(IntegrityError):
            async with app.state.sessions() as db, db.begin():
                db.add(
                    QuizAttempt(
                        user_id=UUID(user["id"]),
                        lesson_id=UUID(lesson_id),
                        version_id=UUID(data["version_id"]),
                        idempotency_key=uuid4(),
                        request_hash="a" * 64,
                        correct_count=2,
                        total=2,
                        passed=True,
                        xp_awarded=25,
                        submitted_at=datetime.now(UTC),
                    )
                )
        assert (await client.get("/api/v1/me/learning")).json()["xp"] == 25
