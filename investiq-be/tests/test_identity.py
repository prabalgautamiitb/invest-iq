import asyncio
from datetime import timedelta
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from httpx import AsyncClient
from redis.exceptions import RedisError
from sqlalchemy import func, select, update

from investiq.api.identity import require_verified
from investiq.core.config import Settings
from investiq.core.security import Principal, digest, now
from investiq.main import create_app
from investiq.models.identity import AccountToken, AuditEvent, Session, User
from tests.conftest import CapturedMailer
from tests.helpers import test_client as api_client

pytestmark = pytest.mark.integration
PASSWORD = "a valid long password 73"


def email() -> str:
    return f"phase2-{uuid4().hex}@example.com"


async def csrf(client: AsyncClient) -> dict[str, str]:
    response = await client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"], "Origin": "http://localhost:5173"}


async def register(client: AsyncClient, address: str | None = None) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        headers=await csrf(client),
        json={
            "email": address or email(),
            "password": PASSWORD,
            "name": "Learning User",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_registration_rotation_hashing_and_profile_isolation(
    identity_settings: Settings,
) -> None:
    mailer = CapturedMailer()
    app = create_app(identity_settings, mailer)
    async with api_client(app) as alice, api_client(create_app(identity_settings, mailer)) as bob:
        old_csrf = await csrf(alice)
        old_cookie = alice.cookies.get(identity_settings.cookie_name)
        first = await register(alice)
        second = await register(bob)
        assert first["role"] == "user" and first["email_verified"] is False
        assert first["onboarding"] is None
        assert first["privacy"] == {"public": False, "holdings": False}
        assert "password" not in str(first) and "token" not in str(first)
        assert old_cookie != alice.cookies.get(identity_settings.cookie_name)
        assert (
            await alice.patch("/api/v1/me", headers=old_csrf, json={"name": "Forged"})
        ).status_code == 403
        headers = await csrf(alice)
        assert (
            await alice.patch("/api/v1/me", headers=headers, json={"role": "admin"})
        ).status_code == 422
        assert (
            await alice.patch(
                "/api/v1/me", headers=headers, json={"user_id": second["id"], "name": "Other"}
            )
        ).status_code == 422
        updated = await alice.patch(
            "/api/v1/me", headers=headers, json={"name": "Alice", "weekly_goal": 105}
        )
        assert updated.json()["name"] == "Alice"
        assert (await bob.get("/api/v1/me")).json()["name"] == "Learning User"
        assert (await alice.get(f"/api/v1/admin/users/{second['id']}")).status_code == 403
        assert (
            await alice.patch("/api/v1/me/preferences", headers=headers, json={"replies": True})
        ).json()["replies"] is True
        assert (
            await alice.patch("/api/v1/me/privacy", headers=headers, json={"public": True})
        ).json()["public"] is True
        assert (await bob.get("/api/v1/me/privacy")).json()["public"] is False
        async with app.state.sessions() as db:
            user = await db.get(User, UUID(first["id"]))
            assert user.password_hash.startswith("$argon2id$")
            assert PASSWORD not in user.password_hash
            current = await db.scalar(
                select(Session).where(
                    Session.token_hash == digest(alice.cookies.get(identity_settings.cookie_name))
                )
            )
            assert current is not None and len(current.token_hash) == 64
            recovery_rows = (
                await db.scalars(select(AccountToken).where(AccountToken.user_id == user.id))
            ).all()
            assert len(recovery_rows) == 1
            assert recovery_rows[0].token_hash != mailer.token(user.email, "verification")
            actions = (
                await db.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == user.id))
            ).all()
            assert {
                "registered",
                "profile_updated",
                "preferences_updated",
                "privacy_updated",
            } <= set(actions)


async def test_csrf_origin_validation_and_anonymous_authorization(
    identity_settings: Settings,
) -> None:
    async with api_client(create_app(identity_settings, CapturedMailer())) as client:
        assert (await client.get("/api/v1/me")).status_code == 401
        assert (
            await client.post("/api/v1/auth/login", json={"email": email(), "password": PASSWORD})
        ).status_code == 403
        headers = await csrf(client)
        assert (await client.get("/api/v1/me")).status_code == 401
        for origin in ("https://evil.example", "null"):
            response = await client.post(
                "/api/v1/auth/login",
                headers={**headers, "Origin": origin},
                json={"email": email(), "password": PASSWORD},
            )
            assert response.status_code == 403
        rejected = await client.get("/api/v1/auth/csrf", headers={"Origin": "https://evil.example"})
        assert rejected.status_code == 403
        assert "set-cookie" not in rejected.headers
        assert rejected.headers["cache-control"] == "no-store"


async def test_onboarding_server_classification_and_validation(identity_settings: Settings) -> None:
    async with api_client(create_app(identity_settings, CapturedMailer())) as client:
        await register(client)
        questions = (await client.get("/api/v1/onboarding/questions")).json()
        answers = {q["id"]: q["options"][0]["id"] for q in questions["questions"]}
        headers = await csrf(client)
        invalid = await client.put(
            "/api/v1/me/onboarding",
            headers=headers,
            json={"version": 1, "answers": {**answers, "experience": "forged"}},
        )
        assert invalid.status_code == 422
        assert (await client.get("/api/v1/me")).json()["onboarding"] is None
        assert (
            await client.put(
                "/api/v1/me/onboarding", headers=headers, json={"version": 999, "answers": answers}
            )
        ).status_code == 409
        answers["experience"], answers["pace"] = "experience:2", "pace:1"
        valid = await client.put(
            "/api/v1/me/onboarding",
            headers=headers,
            json={"version": questions["version"], "answers": answers},
        )
        assert valid.status_code == 200
        profile = valid.json()
        assert profile["weekly_goal"] == 105
        assert profile["onboarding"]["experience"] == "intermediate"
        assert profile["onboarding"]["learning_profile"] == "Confident Builder"
        repeat = await client.put(
            "/api/v1/me/onboarding", headers=headers, json={"version": 1, "answers": answers}
        )
        assert repeat.status_code == 200
        assert (await client.get("/api/v1/me")).json()["onboarding"]["answers"] == answers


async def test_verification_single_use_and_verified_dependency(identity_settings: Settings) -> None:
    mailer = CapturedMailer()
    app = create_app(identity_settings, mailer)

    @app.get("/verified-probe")
    async def verified(
        principal: Annotated[Principal, Depends(require_verified)],
    ) -> dict[str, bool]:
        return {"verified": True}

    async with api_client(app) as client:
        user = await register(client)
        assert (await client.get("/verified-probe")).status_code == 403
        token = mailer.token(user["email"], "verification")
        headers = await csrf(client)
        response = await client.post(
            "/api/v1/auth/verification/complete", headers=headers, json={"token": token}
        )
        assert response.status_code == 200
        assert (await client.get("/verified-probe")).status_code == 200
        assert (await client.get("/api/v1/me")).json()["email_verified"] is True
        assert (
            await client.post(
                "/api/v1/auth/verification/complete", headers=headers, json={"token": token}
            )
        ).status_code == 400


async def test_login_logout_revocation_and_ownership(identity_settings: Settings) -> None:
    mailer = CapturedMailer()
    async with (
        api_client(create_app(identity_settings, mailer)) as first,
        api_client(create_app(identity_settings, mailer)) as second,
        api_client(create_app(identity_settings, mailer)) as other,
    ):
        user = await register(first)
        await register(other)
        second_headers = await csrf(second)
        for address in (user["email"], email()):
            wrong = await second.post(
                "/api/v1/auth/login",
                headers=second_headers,
                json={"email": address, "password": "wrong"},
            )
            assert wrong.status_code == 401
            assert wrong.json()["error"]["code"] == "invalid_credentials"
        success = await second.post(
            "/api/v1/auth/login",
            headers=second_headers,
            json={"email": user["email"].upper(), "password": PASSWORD},
        )
        assert success.status_code == 200
        entries = (await first.get("/api/v1/me/sessions")).json()
        assert len(entries) == 2
        target = next(s["id"] for s in entries if not s["current"])
        assert (
            await other.delete(f"/api/v1/me/sessions/{target}", headers=await csrf(other))
        ).status_code == 404
        for _ in range(2):
            assert (
                await first.delete(f"/api/v1/me/sessions/{target}", headers=await csrf(first))
            ).status_code == 204
        assert (await second.get("/api/v1/me")).status_code == 401
        assert (
            await first.post("/api/v1/auth/logout", headers=await csrf(first))
        ).status_code == 204
        assert (await first.get("/api/v1/me")).status_code == 401


async def test_reset_is_single_use_under_concurrency_and_revokes_sessions(
    identity_settings: Settings,
) -> None:
    mailer = CapturedMailer()
    async with (
        api_client(create_app(identity_settings, mailer)) as logged,
        api_client(create_app(identity_settings, mailer)) as resetter,
        api_client(create_app(identity_settings, mailer)) as concurrent,
    ):
        user = await register(logged)
        headers = await csrf(resetter)
        existing = await resetter.post(
            "/api/v1/auth/password-reset/request", headers=headers, json={"email": user["email"]}
        )
        missing = await resetter.post(
            "/api/v1/auth/password-reset/request", headers=headers, json={"email": email()}
        )
        assert existing.status_code == missing.status_code == 202
        assert existing.json() == missing.json()
        token = mailer.token(user["email"], "password_reset")
        payload = {"token": token, "password": "the new long password 92"}
        other_headers = await csrf(concurrent)
        results = await asyncio.gather(
            resetter.post("/api/v1/auth/password-reset/complete", headers=headers, json=payload),
            concurrent.post(
                "/api/v1/auth/password-reset/complete", headers=other_headers, json=payload
            ),
        )
        assert sorted(r.status_code for r in results) == [200, 400]
        assert (await logged.get("/api/v1/me")).status_code == 401
        login = await resetter.post(
            "/api/v1/auth/login",
            headers=await csrf(resetter),
            json={"email": user["email"], "password": payload["password"]},
        )
        assert login.status_code == 200


async def test_expired_and_superseded_tokens_and_expired_session(
    identity_settings: Settings,
) -> None:
    mailer = CapturedMailer()
    app = create_app(identity_settings, mailer)
    async with api_client(app) as client:
        user = await register(client)
        old = mailer.token(user["email"], "verification")
        headers = await csrf(client)
        await client.post(
            "/api/v1/auth/verification/request", headers=headers, json={"email": user["email"]}
        )
        fresh = mailer.token(user["email"], "verification")
        assert old != fresh
        assert (
            await client.post(
                "/api/v1/auth/verification/complete", headers=headers, json={"token": old}
            )
        ).status_code == 400
        async with app.state.sessions() as db, db.begin():
            await db.execute(
                update(AccountToken)
                .where(AccountToken.token_hash == digest(fresh))
                .values(created_at=now() - timedelta(days=2), expires_at=now() - timedelta(days=1))
            )
        assert (
            await client.post(
                "/api/v1/auth/verification/complete", headers=headers, json={"token": fresh}
            )
        ).status_code == 400
        async with app.state.sessions() as db, db.begin():
            await db.execute(
                update(Session)
                .where(Session.user_id == UUID(user["id"]))
                .values(created_at=now() - timedelta(days=2), expires_at=now() - timedelta(days=1))
            )
        assert (await client.get("/api/v1/me")).status_code == 401


async def test_duplicate_registration_concurrency(identity_settings: Settings) -> None:
    address, mailer = email(), CapturedMailer()
    async with (
        api_client(create_app(identity_settings, mailer)) as one,
        api_client(create_app(identity_settings, mailer)) as two,
    ):
        headers1, headers2 = await csrf(one), await csrf(two)
        data = {"name": "Concurrent", "email": address, "password": PASSWORD}
        results = await asyncio.gather(
            one.post("/api/v1/auth/register", headers=headers1, json=data),
            two.post("/api/v1/auth/register", headers=headers2, json=data),
        )
        assert sorted(r.status_code for r in results) == [201, 409]
        assert len(mailer.messages) == 1


async def test_rate_limits_are_atomic_and_fail_closed(
    identity_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity_settings.auth_rate_limit = 1
    app = create_app(identity_settings, CapturedMailer())
    async with api_client(app) as client:
        headers = await csrf(client)
        responses = await asyncio.gather(
            *[
                client.post(
                    "/api/v1/auth/password-reset/request", headers=headers, json={"email": email()}
                )
                for _ in range(3)
            ]
        )
        assert sorted(r.status_code for r in responses) == [202, 429, 429]
        assert all(r.headers.get("retry-after") == "900" for r in responses if r.status_code == 429)

        async def unavailable(*args: object, **kwargs: object) -> None:
            raise RedisError("secret connection details")

        monkeypatch.setattr(app.state.identity.redis, "eval", unavailable)
        failed = await client.post(
            "/api/v1/auth/password-reset/request", headers=headers, json={"email": email()}
        )
        assert failed.status_code == 503
        assert "secret connection details" not in failed.text


async def test_admin_authorization_uses_database_role(identity_settings: Settings) -> None:
    app = create_app(identity_settings, CapturedMailer())
    async with api_client(app) as client:
        user = await register(client)
        assert (await client.get(f"/api/v1/admin/users/{user['id']}")).status_code == 403
        async with app.state.sessions() as db, db.begin():
            await db.execute(update(User).where(User.id == UUID(user["id"])).values(role="admin"))
        assert (await client.get(f"/api/v1/admin/users/{user['id']}")).status_code == 200


async def test_email_failure_is_audited_without_token_disclosure(
    identity_settings: Settings,
) -> None:
    app = create_app(identity_settings, CapturedMailer(fail=True))
    async with api_client(app) as client:
        user = await register(client)
        async with app.state.sessions() as db:
            failed = await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.actor_id == UUID(user["id"]),
                    AuditEvent.action == "verification_email_failed",
                )
            )
            assert failed == 1
        assert (await client.get("/api/v1/me")).status_code == 200


async def test_production_cookie_security(identity_settings: Settings) -> None:
    identity_settings.environment = "production"
    async with api_client(
        create_app(identity_settings, CapturedMailer()), base_url="https://testserver"
    ) as client:
        response = await client.get("/api/v1/auth/csrf")
        cookie = response.headers["set-cookie"]
        assert cookie.startswith("__Host-investiq_session=")
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
        assert "Path=/" in cookie and "Domain=" not in cookie


async def test_operator_roles_require_verification_and_revoke_sessions(
    identity_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from investiq import cli

    monkeypatch.setattr(cli, "Settings", lambda: identity_settings)
    mailer = CapturedMailer()
    async with api_client(create_app(identity_settings, mailer)) as client:
        user = await register(client)
        with pytest.raises(SystemExit, match="Verify the account email"):
            await cli.set_role(user["email"], "admin")
        await client.post(
            "/api/v1/auth/verification/complete",
            headers=await csrf(client),
            json={"token": mailer.token(user["email"], "verification")},
        )
        await cli.set_role(user["email"], "admin")
        assert (await client.get("/api/v1/me")).status_code == 401
        login = await client.post(
            "/api/v1/auth/login",
            headers=await csrf(client),
            json={"email": user["email"], "password": PASSWORD},
        )
        assert login.status_code == 200
        assert login.json()["role"] == "admin"
        await cli.set_role(user["email"], "user")
        assert (await client.get("/api/v1/me")).status_code == 401
