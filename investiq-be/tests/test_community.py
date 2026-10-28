import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from investiq.core.config import Settings
from investiq.core.security import now
from investiq.main import create_app
from investiq.models.community import CommunityContent, CommunityModeration, CommunityVote
from investiq.models.identity import AuditEvent, User
from tests.conftest import CapturedMailer, migrated_database
from tests.helpers import test_client as api_client
from tests.test_contest import verified
from tests.test_identity import csrf, register


@pytest_asyncio.fixture
async def community_settings():
    async with migrated_database() as url:
        yield Settings(
            database_url=SecretStr(url),
            environment="test",
            auth_rate_limit=10000,
            csrf_rate_limit=10000,
            rate_limit_prefix=str(uuid4()),
        )


async def post(client, body="A question about diversification", key=None, **kwargs):
    return await client.post(
        "/api/v1/community/posts",
        json={"body": body, **kwargs},
        headers={**await csrf(client), "Idempotency-Key": key or str(uuid4())},
    )


async def action(client, identifier, action, data, method="PUT"):
    return await client.request(
        method,
        f"/api/v1/community/posts/{identifier}/{action}",
        json=data,
        headers=await csrf(client),
    )


async def test_public_feed_privacy_saved_posts_and_retry(community_settings):
    app = create_app(community_settings, CapturedMailer())
    async with api_client(app) as client:
        assert (await client.get("/api/v1/community/posts")).json()["items"] == []
        assert (await client.get("/api/v1/community/posts?saved=true")).status_code == 401
        assert (await post(client)).status_code == 401
        await verified(client, app.state.identity.mailer)
        key = str(uuid4())
        first = await post(client, key=key)
        assert first.status_code == 201, first.text
        identifier = first.json()["id"]
        assert (await post(client, key=key)).json()["id"] == identifier
        assert (await post(client, key=key, body="Different payload")).status_code == 409
        for _ in range(2):
            assert (await action(client, identifier, "like", {"enabled": True})).status_code == 200
            assert (await action(client, identifier, "save", {"enabled": True})).status_code == 200
        row = (await client.get(f"/api/v1/community/posts/{identifier}")).json()
        assert row["likes"] == 1 and row["liked"] and row["saved"] and row["own"]
        assert len((await client.get("/api/v1/community/posts?saved=true")).json()["items"]) == 1
        await client.post("/api/v1/auth/logout", headers=await csrf(client))
        guest = (await client.get(f"/api/v1/community/posts/{identifier}")).json()
        assert guest["author"] == "Private learner" and not guest["saved"] and not guest["liked"]
        assert not any(k in guest for k in ("email", "author_id", "reporter_id", "user_id"))
        await verified(client, app.state.identity.mailer, "other-community@example.com")
        assert (await client.get("/api/v1/community/posts?saved=true")).json()["items"] == []
        assert (
            await client.delete(f"/api/v1/community/posts/{identifier}", headers=await csrf(client))
        ).status_code == 403


async def test_groups_comments_membership_and_parent_visibility(community_settings):
    app = create_app(community_settings, CapturedMailer())
    async with api_client(app) as client:
        await verified(client, app.state.identity.mailer)
        data = {"name": "Beginner Questions", "description": "Learn together in public"}
        response = await client.post(
            "/api/v1/community/groups", json=data, headers=await csrf(client)
        )
        assert response.status_code == 201, response.text
        group = response.json()["id"]
        assert (
            await client.post("/api/v1/community/groups", json=data, headers=await csrf(client))
        ).json()["id"] == group
        root = (await post(client, group_id=group)).json()["id"]
        key = str(uuid4())
        url = f"/api/v1/community/posts/{root}/comments"
        headers = {**await csrf(client), "Idempotency-Key": key}
        reply = await client.post(url, json={"body": "A thoughtful reply"}, headers=headers)
        assert reply.status_code == 201, reply.text
        assert (
            await client.post(url, json={"body": "A thoughtful reply"}, headers=headers)
        ).json()["id"] == reply.json()["id"]
        assert len((await client.get(url)).json()["items"]) == 1
        assert (
            await action(client, reply.json()["id"], "save", {"enabled": True})
        ).status_code == 422
        assert (
            await client.post(
                f"/api/v1/community/posts/{reply.json()['id']}/comments",
                json={"body": "Nested"},
                headers={**headers, "Idempotency-Key": str(uuid4())},
            )
        ).status_code == 422
        await client.put(
            f"/api/v1/community/groups/{group}/membership",
            json={"enabled": False},
            headers=await csrf(client),
        )
        assert (await post(client, group_id=group)).status_code == 403
        assert (
            await client.post(
                url,
                json={"body": "Another reply"},
                headers={**headers, "Idempotency-Key": str(uuid4())},
            )
        ).status_code == 403
        assert (await client.get("/api/v1/community/groups")).json()["items"][0]["members"] == 0
        assert (
            await client.get("/api/v1/community/posts", params={"group": group})
        ).status_code == 403
        assert (await client.get(f"/api/v1/community/posts/{root}")).status_code == 403
        await client.put(
            f"/api/v1/community/groups/{group}/membership",
            json={"enabled": True},
            headers=await csrf(client),
        )
        await client.delete(f"/api/v1/community/posts/{root}", headers=await csrf(client))
        assert (await client.get(url)).status_code == 404
        assert (
            await client.get(f"/api/v1/community/posts/{reply.json()['id']}")
        ).status_code == 404
        assert (await client.get("/api/v1/community/posts")).json()["items"] == []


async def test_polls_validation_final_votes_concurrency_and_expiry(community_settings):
    app = create_app(community_settings, CapturedMailer())
    async with api_client(app) as client:
        await verified(client, app.state.identity.mailer)
        options = {
            "kind": "poll",
            "options": ["Diversify", "Concentrate"],
            "closes_at": (now() + timedelta(seconds=3)).isoformat(),
        }
        assert (await post(client, **{**options, "options": ["Same", "Same"]})).status_code == 422
        assert (
            await post(client, **{**options, "closes_at": now().isoformat()})
        ).status_code == 422
        assert (
            await post(client, **{**options, "closes_at": (now() + timedelta(days=31)).isoformat()})
        ).status_code == 422
        root = (await post(client, **options)).json()["id"]
        headers = await csrf(client)
        responses = await asyncio.gather(
            *[
                client.put(
                    f"/api/v1/community/posts/{root}/vote", json={"option": 0}, headers=headers
                )
                for _ in range(5)
            ]
        )
        assert all(r.status_code == 200 for r in responses)
        assert (await action(client, root, "vote", {"option": 1})).status_code == 409
        assert (await client.get(f"/api/v1/community/posts/{root}")).json()["votes"] == [1, 0]
        await client.post("/api/v1/auth/logout", headers=await csrf(client))
        await verified(client, app.state.identity.mailer, "poll-second@example.com")
        await asyncio.sleep(3)
        assert (await action(client, root, "vote", {"option": 1})).status_code == 409
        assert not (await client.get(f"/api/v1/community/posts/{root}")).json()["poll_open"]


async def test_moderation_report_privacy_role_refresh_and_audit(community_settings):
    app = create_app(community_settings, CapturedMailer())
    async with api_client(app) as client:
        user = await verified(client, app.state.identity.mailer)
        root = (await post(client)).json()["id"]
        for _ in range(2):
            assert (
                await action(
                    client, root, "reports", {"reason": "Please review this content"}, "POST"
                )
            ).status_code == 200
        assert (await client.get("/api/v1/community/reports")).status_code == 403
        decision = {"action": "hide", "reason": "Reviewed inappropriate content"}
        assert (await action(client, root, "moderation", decision, "POST")).status_code == 403
        async with app.state.sessions() as db, db.begin():
            await db.execute(update(User).where(User.id == UUID(user["id"])).values(role="admin"))
        reports = (await client.get("/api/v1/community/reports")).json()["items"]
        assert len(reports) == 1 and "reporter_id" not in reports[0]
        await action(client, root, "save", {"enabled": True})
        assert (await action(client, root, "moderation", decision, "POST")).status_code == 200
        assert (await client.get(f"/api/v1/community/posts/{root}")).status_code == 404
        assert (await client.get("/api/v1/community/posts?saved=true")).json()["items"] == []
        assert (await action(client, root, "like", {"enabled": True})).status_code == 404
        assert (
            await action(client, root, "moderation", {**decision, "action": "restore"}, "POST")
        ).status_code == 200
        assert (await client.get(f"/api/v1/community/posts/{root}")).status_code == 200
        await client.delete(f"/api/v1/community/posts/{root}", headers=await csrf(client))
        assert (
            await action(client, root, "moderation", {**decision, "action": "restore"}, "POST")
        ).status_code == 409
        assert (await action(client, root, "moderation", decision, "POST")).status_code == 409
        async with app.state.sessions() as db, db.begin():
            assert await db.scalar(select(func.count()).select_from(CommunityModeration)) == 2
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "community.hide")
                )
                == 1
            )
            await db.execute(update(User).where(User.id == UUID(user["id"])).values(role="user"))
        assert (await client.get("/api/v1/community/reports")).status_code == 403


async def test_feed_cursors_validation_verified_writes_and_database_guards(community_settings):
    app = create_app(community_settings, CapturedMailer())
    async with api_client(app) as client:
        await register(client)
        assert (await post(client)).status_code == 403
        # Verify through the helper in a new account rather than importing demo data.
        await client.post("/api/v1/auth/logout", headers=await csrf(client))
        await verified(client, app.state.identity.mailer, "guards@example.com")
        one = (await post(client)).json()["id"]
        await post(client, body="A second genuine post", kind="idea")
        first = (await client.get("/api/v1/community/posts?limit=1")).json()
        second = (
            await client.get(
                "/api/v1/community/posts", params={"limit": 1, "cursor": first["next_cursor"]}
            )
        ).json()
        assert first["items"][0]["id"] != second["items"][0]["id"]
        assert (
            await client.get(
                "/api/v1/community/posts", params={"kind": "idea", "cursor": first["next_cursor"]}
            )
        ).status_code == 422
        assert (await client.get("/api/v1/community/posts?cursor=broken")).status_code == 422
        assert (await post(client, body="   ")).status_code == 422
        assert (await post(client, author_id=str(uuid4()))).status_code == 422
        assert (
            await client.post(
                "/api/v1/community/posts",
                json={"body": "Missing CSRF"},
                headers={"Idempotency-Key": str(uuid4())},
            )
        ).status_code == 403
        async with app.state.sessions() as db:
            try:
                async with db.begin():
                    await db.execute(
                        update(CommunityContent)
                        .where(CommunityContent.id == UUID(one))
                        .values(body="Rewritten evidence")
                    )
            except IntegrityError:
                pass
            else:
                raise AssertionError("Community evidence was mutable")
        async with app.state.sessions() as db:
            try:
                async with db.begin():
                    author = await db.scalar(
                        select(CommunityContent.author_id).where(CommunityContent.id == UUID(one))
                    )
                    db.add(CommunityVote(content_id=UUID(one), user_id=author, option=0))
                    await db.flush()
            except IntegrityError:
                pass
            else:
                raise AssertionError("A non-poll accepted a vote")


async def test_public_name_changes_concurrent_creation_and_paginated_groups_reports(
    community_settings,
):
    import httpx

    app = create_app(community_settings, CapturedMailer())
    async with api_client(app) as client:
        user = await verified(client, app.state.identity.mailer)
        headers = {**await csrf(client), "Idempotency-Key": str(uuid4())}
        created = await asyncio.gather(
            *[
                client.post(
                    "/api/v1/community/posts",
                    json={"body": "Retrying the same genuine post"},
                    headers=headers,
                )
                for _ in range(4)
            ]
        )
        assert all(r.status_code == 201 for r in created)
        assert len({r.json()["id"] for r in created}) == 1
        identifier = created[0].json()["id"]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as guest:
            assert (await guest.get(f"/api/v1/community/posts/{identifier}")).json()[
                "author"
            ] == "Private learner"
            assert (
                await client.patch(
                    "/api/v1/me/privacy", json={"public": True}, headers=await csrf(client)
                )
            ).status_code == 200
            assert (await guest.get(f"/api/v1/community/posts/{identifier}")).json()[
                "author"
            ] == user["name"]
            await client.patch(
                "/api/v1/me/privacy", json={"public": False}, headers=await csrf(client)
            )
            assert (await guest.get(f"/api/v1/community/posts/{identifier}")).json()[
                "author"
            ] == "Private learner"
        for name in ["A Group", "B Group", "C Group"]:
            assert (
                await client.post(
                    "/api/v1/community/groups",
                    json={"name": name, "description": "Public learning"},
                    headers=await csrf(client),
                )
            ).status_code == 201
        first = (await client.get("/api/v1/community/groups?limit=1")).json()
        second = (
            await client.get(
                "/api/v1/community/groups", params={"cursor": first["next_cursor"], "limit": 1}
            )
        ).json()
        assert first["items"][0]["name"] == "A Group" and second["items"][0]["name"] == "B Group"
        assert (await client.get("/api/v1/community/groups?cursor=broken")).status_code == 422
        second_post = (await post(client, body="Second report target")).json()["id"]
        for target in [identifier, second_post]:
            await action(
                client, target, "reports", {"reason": "Needs administrator review"}, "POST"
            )
        async with app.state.sessions() as db, db.begin():
            await db.execute(update(User).where(User.id == UUID(user["id"])).values(role="admin"))
        first = (await client.get("/api/v1/community/reports?limit=1")).json()
        second = (
            await client.get(
                "/api/v1/community/reports", params={"cursor": first["next_cursor"], "limit": 1}
            )
        ).json()
        assert first["items"][0]["id"] != second["items"][0]["id"]
        assert (await client.get("/api/v1/community/reports?cursor=broken")).status_code == 422


async def test_community_write_rate_limit_is_separate_from_auth(community_settings):
    app = create_app(
        community_settings.model_copy(update={"community_write_limit": 1}), CapturedMailer()
    )
    async with api_client(app) as client:
        await verified(client, app.state.identity.mailer)
        assert (await post(client)).status_code == 201
        response = await post(client, body="Another post")
        assert response.status_code == 429 and response.headers["Retry-After"] == "60"
        assert len((await client.get("/api/v1/community/posts")).json()["items"]) == 1


async def test_joined_feeds_gate_every_read_and_interaction_and_revoke_saved_access(
    community_settings,
):
    mailer = CapturedMailer()
    async with (
        api_client(create_app(community_settings, mailer)) as alice,
        api_client(create_app(community_settings, mailer)) as bob,
        api_client(create_app(community_settings, mailer)) as guest,
    ):
        await verified(alice, mailer, "circle-owner@example.com")
        await verified(bob, mailer, "circle-member@example.com")

        async def group(client, name):
            response = await client.post(
                "/api/v1/community/groups",
                json={"name": name, "description": "Discuss investing together"},
                headers=await csrf(client),
            )
            assert response.status_code == 201
            return response.json()["id"]

        first = await group(alice, "A members circle")
        own = await group(bob, "B members circle")
        await group(bob, "C members circle")
        private = (await post(alice, body="Only A members may read this", group_id=first)).json()[
            "id"
        ]
        reply = (
            await alice.post(
                f"/api/v1/community/posts/{private}/comments",
                json={"body": "A members reply"},
                headers={**await csrf(alice), "Idempotency-Key": str(uuid4())},
            )
        ).json()["id"]
        own_post = (await post(bob, body="Only B members may read this", group_id=own)).json()["id"]
        public = (await post(alice, body="A general discussion anyone can read")).json()["id"]
        for viewer in [bob, guest]:
            assert (await viewer.get("/api/v1/community/groups/" + first)).json()[
                "visibility"
            ] == "members"
            for path in [
                f"/posts/{private}",
                f"/posts/{reply}",
                f"/posts/{private}/comments",
                f"/posts?group={first}",
            ]:
                result = await viewer.get("/api/v1/community" + path)
                assert result.status_code == 403
                assert "Only A members" not in result.text
            visible = (await viewer.get("/api/v1/community/posts")).json()["items"]
            assert private not in {p["id"] for p in visible}
        for name, body in [
            ("like", {"enabled": True}),
            ("save", {"enabled": True}),
            ("vote", {"option": 0}),
        ]:
            assert (await action(bob, private, name, body)).status_code == 403
        assert (
            await action(
                bob, private, "reports", {"reason": "Cannot read this private post"}, "POST"
            )
        ).status_code == 403
        assert (await post(bob, group_id=first)).status_code == 403
        assert (await guest.get(f"/api/v1/community/posts/{public}")).status_code == 200
        assert (await guest.get("/api/v1/community/posts?scope=joined")).json()["items"] == []
        assert (await guest.get("/api/v1/community/groups?scope=joined")).status_code == 401
        membership = f"/api/v1/community/groups/{first}/membership"
        assert (
            await bob.put(membership, json={"enabled": True}, headers=await csrf(bob))
        ).status_code == 200
        assert (await bob.get(f"/api/v1/community/posts/{private}")).status_code == 200
        await action(bob, private, "save", {"enabled": True})
        joined = (await bob.get("/api/v1/community/posts?scope=joined&limit=1")).json()
        next_page = (
            await bob.get(
                "/api/v1/community/posts",
                params={"scope": "joined", "limit": 1, "cursor": joined["next_cursor"]},
            )
        ).json()
        assert {joined["items"][0]["id"], next_page["items"][0]["id"]} == {private, own_post}
        assert public not in {p["id"] for p in joined["items"] + next_page["items"]}
        assert (
            await bob.get(
                "/api/v1/community/posts",
                params={"scope": "public", "cursor": joined["next_cursor"]},
            )
        ).status_code == 422
        directory = (
            await bob.get("/api/v1/community/groups?scope=joined&q=A%20members&limit=1")
        ).json()
        assert [g["id"] for g in directory["items"]] == [first]
        assert directory["items"][0]["posts"] == 1
        assert not directory["items"][0]["owned"]
        created = (await bob.get("/api/v1/community/groups?scope=created")).json()["items"]
        assert len(created) == 2 and all(g["owned"] for g in created)
        await bob.put(membership, json={"enabled": False}, headers=await csrf(bob))
        assert (await bob.get(f"/api/v1/community/posts/{private}")).status_code == 403
        assert (await bob.get("/api/v1/community/posts?saved=true")).json()["items"] == []
        assert private not in {
            p["id"] for p in (await bob.get("/api/v1/community/posts?scope=joined")).json()["items"]
        }
        await bob.put(membership, json={"enabled": True}, headers=await csrf(bob))
        assert (await bob.get("/api/v1/community/posts?saved=true")).json()["items"][0][
            "id"
        ] == private
