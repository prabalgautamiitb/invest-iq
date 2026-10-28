from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import false, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from investiq.core.errors import AppError
from investiq.core.security import Principal, now
from investiq.models.community import (
    CommunityContent as Content,
)
from investiq.models.community import (
    CommunityGroup as Group,
)
from investiq.models.community import (
    CommunityModeration as Moderation,
)
from investiq.models.community import (
    CommunityReaction as Reaction,
)
from investiq.models.community import (
    CommunityReport as Report,
)
from investiq.models.community import (
    CommunitySave as Save,
)
from investiq.models.community import (
    CommunityVote as Vote,
)
from investiq.models.community import (
    GroupMember as Member,
)
from investiq.models.identity import AuditEvent, Privacy, User
from investiq.schemas.community import (
    ContentInput,
    ContentOut,
    ContentPage,
    GroupInput,
    GroupOut,
    GroupPage,
    ModerateInput,
    ReportOut,
    ReportPage,
)
from investiq.services.identity import IdentityService
from investiq.services.market import decode_cursor, encode_cursor, fingerprint


class CommunityService:
    def __init__(self, identity: IdentityService) -> None:
        self.identity = identity
        self.factory = identity.factory

    async def viewer(
        self,
        db: AsyncSession,
        principal: Principal | None,
        *,
        write: bool = False,
        admin: bool = False,
    ) -> User | None:
        user = (
            await self.identity.authenticated_user(db, principal)
            if principal and principal.user_id
            else None
        )
        if (write or admin) and (not user or not user.email_verified_at):
            raise AppError(403, "verification_required", "Verify your email to participate")
        if admin and (not user or user.role != "admin"):
            raise AppError(403, "admin_required", "Administrator access required")
        return user

    async def require_group(self, db: AsyncSession, user: User | None, identifier: UUID) -> None:
        if not await db.get(Group, identifier):
            raise AppError(404, "group_not_found", "Community is unavailable")
        if not user or (user.role != "admin" and not await db.get(Member, (identifier, user.id))):
            raise AppError(403, "membership_required", "Join this community to access its posts")

    async def visible(
        self, db: AsyncSession, identifier: UUID, *, user: User | None, lock: bool = False
    ) -> Content:
        query = select(Content).where(Content.id == identifier)
        content = await db.scalar(query.with_for_update() if lock else query)
        if not content or content.state != "visible":
            raise AppError(404, "content_not_found", "Community content is unavailable")
        if content.group_id:
            await self.require_group(db, user, content.group_id)
        if content.parent_id:
            parent = await db.get(Content, content.parent_id)
            if not parent or parent.state != "visible":
                raise AppError(404, "content_not_found", "Community content is unavailable")
        return content

    async def output(self, db: AsyncSession, row: Content, user: User | None) -> ContentOut:
        author = await db.get(User, row.author_id)
        privacy = await db.get(Privacy, row.author_id)
        own = bool(user and user.id == row.author_id)
        label = (
            author.name
            if author and author.active and (own or (privacy and privacy.public))
            else "Private learner"
        )
        likes = await db.scalar(
            select(func.count()).select_from(Reaction).where(Reaction.content_id == row.id)
        )
        comments = await db.scalar(
            select(func.count())
            .select_from(Content)
            .where(Content.parent_id == row.id, Content.state == "visible")
        )
        votes = (
            await db.execute(
                select(Vote.option, func.count())
                .where(Vote.content_id == row.id)
                .group_by(Vote.option)
            )
        ).all()
        mine = await db.get(Vote, (row.id, user.id)) if user else None
        group = await db.get(Group, row.group_id) if row.group_id else None
        return ContentOut(
            id=row.id,
            author=label,
            own=own,
            kind=row.kind,
            body=row.body,
            group_id=row.group_id,
            group_name=group.name if group else None,
            created_at=row.created_at,
            likes=likes or 0,
            comments=comments or 0,
            liked=bool(user and await db.get(Reaction, (row.id, user.id))),
            saved=bool(user and await db.get(Save, (row.id, user.id))),
            options=row.options,
            votes=[dict(votes).get(i, 0) for i in range(len(row.options))],
            my_vote=mine.option if mine else None,
            closes_at=row.closes_at,
            poll_open=bool(row.kind == "poll" and row.closes_at and now() < row.closes_at),
        )

    async def feed(
        self,
        principal: Principal | None,
        kind: str | None,
        group: UUID | None,
        saved: bool,
        parent: UUID | None,
        cursor: str | None,
        limit: int,
        scope: str = "accessible",
    ) -> ContentPage:
        async with self.factory() as db, db.begin():
            user = await self.viewer(db, principal)
            if saved and not user:
                raise AppError(401, "unauthenticated", "Sign in to view saved posts")
            if parent:
                await self.visible(db, parent, user=user)
            if group:
                await self.require_group(db, user, group)
            query = select(Content).where(Content.state == "visible", Content.parent_id == parent)
            memberships = select(Member.group_id).where(Member.user_id == user.id) if user else None
            if not user or user.role != "admin":
                query = query.where(
                    or_(Content.group_id.is_(None), Content.group_id.in_(memberships))
                    if memberships is not None
                    else Content.group_id.is_(None)
                )
            if scope == "joined":
                query = query.where(
                    Content.group_id.in_(memberships) if memberships is not None else false()
                )
            elif scope == "public":
                query = query.where(Content.group_id.is_(None))
            if kind:
                query = query.where(Content.kind == kind)
            if group:
                query = query.where(Content.group_id == group)
            if saved and user:
                query = query.join(Save, Save.content_id == Content.id).where(
                    Save.user_id == user.id
                )
            context = fingerprint(
                {
                    "kind": kind,
                    "group": str(group),
                    "parent": str(parent),
                    "saved": saved,
                    "scope": scope,
                    "viewer": str(user.id) if user else None,
                }
            )
            if cursor:
                value, identifier = decode_cursor(cursor, context)
                try:
                    stamp = datetime.fromisoformat(value)
                    if stamp.tzinfo is None:
                        raise ValueError
                except ValueError as exc:
                    raise AppError(422, "invalid_cursor", "Invalid community cursor") from exc
                query = query.where(
                    tuple_(Content.created_at, Content.id) < tuple_(stamp, identifier)
                )
            rows = list(
                (
                    await db.scalars(
                        query.order_by(Content.created_at.desc(), Content.id.desc()).limit(
                            limit + 1
                        )
                    )
                ).all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            return ContentPage(
                items=[await self.output(db, row, user) for row in rows],
                next_cursor=encode_cursor(rows[-1].created_at.isoformat(), rows[-1].id, context)
                if more
                else None,
            )

    async def detail(self, principal: Principal | None, identifier: UUID) -> ContentOut:
        async with self.factory() as db, db.begin():
            user = await self.viewer(db, principal)
            return await self.output(db, await self.visible(db, identifier, user=user), user)

    async def create(
        self, principal: Principal | None, data: ContentInput, key: UUID, parent: UUID | None = None
    ) -> ContentOut:
        digest = fingerprint({"data": data.model_dump(mode="json"), "parent": str(parent)})
        async with self.factory() as db, db.begin():
            user = await self.viewer(db, principal, write=True)
            assert user is not None
            existing = await db.scalar(
                select(Content).where(Content.author_id == user.id, Content.request_key == key)
            )
            if existing:
                if existing.request_hash != digest:
                    raise AppError(
                        409,
                        "idempotency_conflict",
                        "This request key was already used for different content",
                    )
                await self.visible(db, existing.id, user=user)
                return await self.output(db, existing, user)
            group_id = data.group_id
            if parent:
                root = await self.visible(db, parent, user=user, lock=True)
                if root.parent_id:
                    raise AppError(422, "nested_comment", "Reply to the original post")
                group_id = root.group_id
            if group_id and not await db.get(Member, (group_id, user.id)):
                raise AppError(
                    403, "membership_required", "Join this community before posting or replying"
                )
            if data.kind == "poll" and (
                not data.closes_at or not now() < data.closes_at <= now() + timedelta(days=30)
            ):
                raise AppError(422, "poll_window", "Polls must close within the next 30 days")
            row = Content(
                author_id=user.id,
                request_key=key,
                request_hash=digest,
                parent_id=parent,
                group_id=group_id,
                kind="comment" if parent else data.kind,
                body=data.body,
                options=data.options,
                closes_at=data.closes_at,
            )
            db.add(row)
            await db.flush()
            return await self.output(db, row, user)

    async def groups(
        self,
        principal: Principal | None,
        cursor: str | None,
        limit: int,
        scope: str = "all",
        q: str = "",
    ) -> GroupPage:
        async with self.factory() as db, db.begin():
            user = await self.viewer(db, principal)
            q = q.strip()
            context = fingerprint(
                {"groups": True, "viewer": str(user.id) if user else None, "scope": scope, "q": q}
            )
            query = select(Group)
            if scope in {"joined", "created"}:
                if user is None:
                    raise AppError(401, "unauthenticated", "Sign in to view your communities")
                if scope == "joined":
                    query = query.where(
                        Group.id.in_(select(Member.group_id).where(Member.user_id == user.id))
                    )
                else:
                    query = query.where(Group.creator_id == user.id)
            if q:
                query = query.where(
                    or_(
                        Group.name.icontains(q, autoescape=True),
                        Group.description.icontains(q, autoescape=True),
                    )
                )
            if cursor:
                name, identifier = decode_cursor(cursor, context)
                query = query.where(
                    tuple_(Group.name.collate("C"), Group.id) > tuple_(name, identifier)
                )
            rows = list(
                (
                    await db.scalars(
                        query.order_by(Group.name.collate("C"), Group.id).limit(limit + 1)
                    )
                ).all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            result = []
            for row in rows:
                result.append(await self.group_output(db, row, user))
            return GroupPage(
                items=result,
                next_cursor=encode_cursor(rows[-1].name, rows[-1].id, context) if more else None,
            )

    async def group_output(self, db: AsyncSession, row: Group, user: User | None) -> GroupOut:
        members = await db.scalar(
            select(func.count()).select_from(Member).where(Member.group_id == row.id)
        )
        posts = await db.scalar(
            select(func.count())
            .select_from(Content)
            .where(
                Content.group_id == row.id, Content.parent_id.is_(None), Content.state == "visible"
            )
        )
        return GroupOut(
            id=row.id,
            name=row.name,
            description=row.description,
            members=members or 0,
            joined=bool(user and await db.get(Member, (row.id, user.id))),
            owned=bool(user and row.creator_id == user.id),
            posts=posts or 0,
        )

    async def group_detail(self, principal: Principal | None, identifier: UUID) -> GroupOut:
        async with self.factory() as db, db.begin():
            user = await self.viewer(db, principal)
            row = await db.get(Group, identifier)
            if not row:
                raise AppError(404, "group_not_found", "Group is unavailable")
            return await self.group_output(db, row, user)

    async def create_group(self, principal: Principal | None, data: GroupInput) -> UUID:
        async with self.factory() as db, db.begin():
            user = await self.viewer(db, principal, write=True)
            assert user is not None
            # Serialize name allocation across creators without an IntegrityError leaking a 500.
            await db.execute(select(func.pg_advisory_xact_lock(742019)))
            old = await db.scalar(select(Group).where(Group.name == data.name))
            if old:
                if old.creator_id == user.id and old.description == data.description:
                    return old.id
                raise AppError(409, "group_name_taken", "Choose another group name")
            row = Group(creator_id=user.id, name=data.name, description=data.description)
            db.add(row)
            await db.flush()
            db.add(Member(group_id=row.id, user_id=user.id))
            db.add(AuditEvent(actor_id=user.id, action="community.created", resource_id=row.id))
            return row.id

    async def membership(
        self, principal: Principal | None, identifier: UUID, enabled: bool
    ) -> None:
        async with self.factory() as db, db.begin():
            user = await self.viewer(db, principal, write=True)
            assert user is not None
            if not await db.get(Group, identifier):
                raise AppError(404, "group_not_found", "Group is unavailable")
            member = await db.get(Member, (identifier, user.id))
            if enabled and not member:
                db.add(Member(group_id=identifier, user_id=user.id))
            elif not enabled and member:
                await db.delete(member)
            if enabled != bool(member):
                db.add(
                    AuditEvent(
                        actor_id=user.id,
                        action="community.joined" if enabled else "community.left",
                        resource_id=identifier,
                    )
                )

    async def interact(
        self,
        principal: Principal | None,
        identifier: UUID,
        action: str,
        enabled: bool = True,
        option: int = 0,
        reason: str = "",
    ) -> None:
        async with self.factory() as db, db.begin():
            user = await self.viewer(db, principal, write=True)
            assert user is not None
            row = await self.visible(db, identifier, user=user, lock=True)
            if action == "save" and row.parent_id:
                raise AppError(
                    422, "save_post_only", "Save the original post to keep this discussion"
                )
            if action in {"like", "save"}:
                model = Reaction if action == "like" else Save
                old = await db.get(model, (row.id, user.id))
                if enabled and not old:
                    db.add(model(content_id=row.id, user_id=user.id))
                elif not enabled and old:
                    await db.delete(old)
            elif action == "vote":
                old_vote = await db.get(Vote, (row.id, user.id))
                if old_vote:
                    if old_vote.option != option:
                        raise AppError(
                            409, "vote_final", "Your poll vote has already been recorded"
                        )
                    return
                if (
                    row.kind != "poll"
                    or not row.closes_at
                    or now() >= row.closes_at
                    or option >= len(row.options)
                ):
                    raise AppError(
                        409, "poll_unavailable", "This poll is closed or this option is unavailable"
                    )
                db.add(Vote(content_id=row.id, user_id=user.id, option=option))
            elif action == "delete":
                if row.author_id != user.id:
                    raise AppError(403, "not_author", "Only the author may delete this content")
                row.state = "deleted"
                db.add(AuditEvent(actor_id=user.id, action="community.delete", resource_id=row.id))
            elif action == "report":
                old_report = await db.scalar(
                    select(Report).where(Report.content_id == row.id, Report.reporter_id == user.id)
                )
                if not old_report:
                    db.add(Report(content_id=row.id, reporter_id=user.id, reason=reason))

    async def reports(
        self, principal: Principal | None, cursor: str | None, limit: int
    ) -> ReportPage:
        async with self.factory() as db, db.begin():
            user = await self.viewer(db, principal, admin=True)
            assert user is not None
            context = fingerprint({"reports": str(user.id)})
            query = select(Report, Content).join(Content, Content.id == Report.content_id)
            if cursor:
                value, identifier = decode_cursor(cursor, context)
                try:
                    resolved, stamp = value.split("|", 1)
                    instant = datetime.fromisoformat(stamp)
                    if resolved not in {"0", "1"} or instant.tzinfo is None:
                        raise ValueError
                except ValueError as exc:
                    raise AppError(422, "invalid_cursor", "Invalid report cursor") from exc
                query = query.where(
                    tuple_(Report.resolved, Report.created_at, Report.id)
                    > tuple_(resolved == "1", instant, identifier)
                )
            rows = list(
                (
                    await db.execute(
                        query.order_by(Report.resolved, Report.created_at, Report.id).limit(
                            limit + 1
                        )
                    )
                ).all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            result = [
                ReportOut(
                    resolved=r.resolved,
                    id=r.id,
                    content_id=c.id,
                    body=c.body,
                    state=c.state,
                    reason=r.reason,
                    created_at=r.created_at,
                )
                for r, c in rows
            ]
            last = rows[-1][0] if rows else None
            return ReportPage(
                items=result,
                next_cursor=encode_cursor(
                    f"{int(last.resolved)}|{last.created_at.isoformat()}", last.id, context
                )
                if more and last
                else None,
            )

    async def moderate(
        self, principal: Principal | None, identifier: UUID, data: ModerateInput
    ) -> None:
        async with self.factory() as db, db.begin():
            user = await self.viewer(db, principal, write=True, admin=True)
            assert user is not None
            row = await db.scalar(select(Content).where(Content.id == identifier).with_for_update())
            if not row:
                raise AppError(404, "content_not_found", "Content is unavailable")
            if data.action in {"hide", "restore"} and row.state == "deleted":
                raise AppError(409, "author_deleted", "Author-deleted content cannot be changed")
            if data.action != "dismiss":
                row.state = "hidden" if data.action == "hide" else "visible"
            reports = (
                await db.scalars(
                    select(Report).where(Report.content_id == row.id, Report.resolved.is_(False))
                )
            ).all()
            for report in reports:
                report.resolved = True
            db.add(
                Moderation(
                    content_id=row.id, moderator_id=user.id, action=data.action, reason=data.reason
                )
            )
            db.add(
                AuditEvent(actor_id=user.id, action="community." + data.action, resource_id=row.id)
            )
