import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import and_, case, exists, func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from investiq.adapters.market import EXCHANGE_TZ
from investiq.core.errors import AppError
from investiq.core.security import Principal, now
from investiq.models.contest import (
    Contest,
    ContestEligibleInstrument,
    ContestInvitation,
    ContestMembership,
    ContestRules,
)
from investiq.models.identity import AuditEvent, User
from investiq.models.market import ExchangeSession, Instrument, MarketExclusion
from investiq.schemas.contest import (
    ContestInput,
    ContestOut,
    ContestPage,
    InvitationOut,
    InvitationPage,
    Level,
    RulesInput,
    Status,
    Visibility,
)
from investiq.services.identity import IdentityService
from investiq.services.market import decode_cursor, encode_cursor, fingerprint
from investiq.services.market_ingestion import ensure_fixture_mode


def phase(c: Contest, instant: datetime) -> Status:
    if c.status in {"draft", "cancelled", "completed"}:
        return cast(Status, c.status)
    if instant >= c.ends_at:
        return "settling"
    if instant >= c.starts_at:
        return "running"
    if instant >= c.entry_closes_at:
        return "locked"
    return "open" if instant >= c.entry_opens_at else "scheduled"


class ContestService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        identity: IdentityService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.factory, self.identity, self.clock = factory, identity, clock or now

    async def seed_draft(self, owner_email: str) -> ContestOut:
        """Local operator seed; never invent an owner, membership, or performance history."""
        ensure_fixture_mode(self.identity.settings)
        key = uuid5(NAMESPACE_URL, "investiq.contest-seed:fixture-v1")
        async with self.factory() as db, db.begin():
            user = await db.scalar(
                select(User).where(User.email == owner_email.lower()).with_for_update()
            )
            if user is None or not user.active or user.email_verified_at is None:
                raise AppError(
                    422, "verified_owner_required", "Register and verify the owner account first"
                )
            existing = await db.scalar(
                select(Contest).where(Contest.owner_id == user.id, Contest.creation_key == key)
            )
            if existing:
                return await self.output(db, existing, user)
            data = await self.template()
            data.name = "Practice league (fixture v1)"
            await self.validate(db, data)
            c = Contest(
                owner_id=user.id,
                creation_key=key,
                request_hash=hashlib.sha256(data.model_dump_json().encode()).hexdigest(),
                **data.model_dump(exclude={"rules"}),
            )
            db.add(c)
            await db.flush()
            await self.append_rules(db, c, data.rules, 1)
            self.audit(db, user, "contest_seeded", c.id)
            return await self.output(db, c, user)

    async def template(self) -> ContestInput:
        ensure_fixture_mode(self.identity.settings)
        async with self.factory() as db:
            sessions = (
                await db.scalars(
                    select(ExchangeSession)
                    .where(
                        ExchangeSession.exchange == "NSE",
                        ExchangeSession.status == "open",
                        ExchangeSession.opens_at > self.clock() + timedelta(hours=1),
                    )
                    .order_by(ExchangeSession.session_date)
                    .limit(5)
                )
            ).all()
            if len(sessions) < 5:
                raise AppError(
                    503,
                    "calendar_unavailable",
                    "Extend the reviewed calendar before creating a contest",
                )
            start, end = sessions[0].opens_at, sessions[-1].closes_at
            assert start and end
            blocked = select(MarketExclusion.instrument_id).where(
                MarketExclusion.starts_on <= sessions[-1].session_date,
                or_(
                    MarketExclusion.ends_on.is_(None),
                    MarketExclusion.ends_on >= sessions[0].session_date,
                ),
            )
            ids = list(
                (
                    await db.scalars(
                        select(Instrument.id)
                        .where(
                            Instrument.active.is_(True),
                            Instrument.kind == "equity",
                            Instrument.data_kind == "fixture",
                            Instrument.id.not_in(blocked),
                        )
                        .order_by(Instrument.symbol)
                    )
                ).all()
            )
            benchmark = await db.scalar(
                select(Instrument.id)
                .where(
                    Instrument.active.is_(True),
                    Instrument.kind == "benchmark",
                    Instrument.data_kind == "fixture",
                )
                .order_by(Instrument.symbol)
                .limit(1)
            )
            if benchmark is None or len(ids) < 5:
                raise AppError(503, "market_not_initialized", "Initialize development market data")
            data = ContestInput(
                name="My learning league",
                description="Educational fixture simulation. No monetary prizes.",
                entry_opens_at=self.clock(),
                entry_closes_at=start - timedelta(minutes=5),
                starts_at=start,
                ends_at=end,
                rules=RulesInput(benchmark_id=benchmark, eligible_instrument_ids=ids),
            )
            await self.validate(db, data)
            return data

    async def actor(self, db: AsyncSession, principal: Principal, *, verified: bool = True) -> User:
        ensure_fixture_mode(self.identity.settings)
        user = await self.identity.authenticated_user(db, principal)
        if verified and user.email_verified_at is None:
            raise AppError(403, "verification_required", "Verify your email to continue")
        return user

    @staticmethod
    def audit(db: AsyncSession, user: User, action: str, identifier: UUID) -> None:
        db.add(AuditEvent(actor_id=user.id, action=action, resource_id=identifier))

    def visible(self, user: User | None, instant: datetime) -> ColumnElement[bool]:
        public = and_(Contest.visibility == "public", Contest.status != "draft")
        if user is None:
            return public
        return or_(
            public,
            Contest.owner_id == user.id,
            exists().where(
                ContestMembership.contest_id == Contest.id, ContestMembership.user_id == user.id
            ),
            and_(
                literal(user.email_verified_at is not None),
                Contest.status != "draft",
                Contest.status != "cancelled",
                exists().where(
                    ContestInvitation.contest_id == Contest.id,
                    ContestInvitation.email == user.email,
                    ContestInvitation.status == "pending",
                    ContestInvitation.expires_at > instant,
                ),
            ),
        )

    async def load(
        self, db: AsyncSession, identifier: UUID, user: User | None, *, lock: bool = False
    ) -> Contest:
        query = select(Contest).where(Contest.id == identifier, self.visible(user, self.clock()))
        if lock:
            query = query.with_for_update()
        contest = await db.scalar(query)
        if contest is None:
            raise AppError(404, "contest_not_found", "Contest not found")
        return contest

    @staticmethod
    def owner(c: Contest, user: User) -> None:
        if c.owner_id != user.id:
            raise AppError(403, "contest_owner_required", "Only the host can change this contest")

    async def rules(self, db: AsyncSession, c: Contest) -> ContestRules:
        rule = await db.scalar(
            select(ContestRules)
            .where(ContestRules.contest_id == c.id)
            .order_by(ContestRules.version.desc())
            .limit(1)
        )
        assert rule is not None
        return rule

    async def rule_input(self, db: AsyncSession, rule: ContestRules) -> RulesInput:
        identifiers = list(
            (
                await db.scalars(
                    select(ContestEligibleInstrument.instrument_id)
                    .where(ContestEligibleInstrument.rule_id == rule.id)
                    .order_by(ContestEligibleInstrument.instrument_id)
                )
            ).all()
        )
        return RulesInput.model_validate(
            {**rule.rules, "capital": rule.capital, "eligible_instrument_ids": identifiers}
        )

    async def append_rules(
        self, db: AsyncSession, c: Contest, data: RulesInput, version: int
    ) -> None:
        rule = ContestRules(
            contest_id=c.id,
            version=version,
            capital=data.capital,
            rules=data.model_dump(mode="json", exclude={"capital", "eligible_instrument_ids"}),
        )
        db.add(rule)
        await db.flush()
        db.add_all(
            [
                ContestEligibleInstrument(rule_id=rule.id, instrument_id=i)
                for i in data.eligible_instrument_ids
            ]
        )
        await db.flush()

    async def output(self, db: AsyncSession, c: Contest, user: User | None) -> ContestOut:
        rule = await self.rules(db, c)
        count = await db.scalar(
            select(func.count())
            .select_from(ContestMembership)
            .where(ContestMembership.contest_id == c.id)
        )
        joined = bool(
            user
            and await db.scalar(
                select(ContestMembership.id).where(
                    ContestMembership.contest_id == c.id, ContestMembership.user_id == user.id
                )
            )
        )
        return ContestOut(
            id=c.id,
            owner_id=c.owner_id,
            name=c.name,
            description=c.description,
            visibility=cast(Visibility, c.visibility),
            level=cast(Level, c.level),
            status=phase(c, self.clock()),
            capacity=c.capacity,
            member_count=count or 0,
            is_owner=bool(user and c.owner_id == user.id),
            joined=joined,
            entry_opens_at=c.entry_opens_at,
            entry_closes_at=c.entry_closes_at,
            starts_at=c.starts_at,
            ends_at=c.ends_at,
            rule_id=rule.id,
            rule_version=rule.version,
            rules=await self.rule_input(db, rule),
        )

    async def validate(self, db: AsyncSession, data: ContestInput) -> None:
        ensure_fixture_mode(self.identity.settings)
        if data.entry_closes_at <= self.clock():
            raise AppError(422, "invalid_schedule", "Entry closing must be in the future")
        first, last = (
            data.starts_at.astimezone(EXCHANGE_TZ).date(),
            data.ends_at.astimezone(EXCHANGE_TZ).date(),
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
        if not days or len(days) != (last - first).days + 1:
            raise AppError(
                422, "calendar_unavailable", "Schedule is outside the reviewed exchange calendar"
            )
        if (
            any(d.status == "unsupported" for d in days)
            or days[0].opens_at != data.starts_at
            or days[-1].closes_at != data.ends_at
        ):
            raise AppError(
                422,
                "invalid_market_schedule",
                "Start at a supported session open and end at a supported session close",
            )
        ids = data.rules.eligible_instrument_ids
        eligible = set(
            (
                await db.scalars(
                    select(Instrument.id).where(
                        Instrument.id.in_(ids),
                        Instrument.active.is_(True),
                        Instrument.kind == "equity",
                        Instrument.data_kind == "fixture",
                    )
                )
            ).all()
        )
        blocked = await db.scalar(
            select(MarketExclusion.id)
            .where(
                MarketExclusion.instrument_id.in_(ids),
                MarketExclusion.starts_on <= last,
                or_(
                    MarketExclusion.ends_on.is_(None),
                    MarketExclusion.ends_on >= data.entry_closes_at.astimezone(EXCHANGE_TZ).date(),
                ),
            )
            .limit(1)
        )
        benchmark = await db.get(Instrument, data.rules.benchmark_id)
        if (
            len(eligible) != len(ids)
            or blocked
            or benchmark is None
            or not benchmark.active
            or benchmark.kind != "benchmark"
            or benchmark.data_kind != "fixture"
        ):
            raise AppError(
                422,
                "invalid_contest_universe",
                "Use active fixture equities and benchmark without unsupported "
                "corporate actions during the contest",
            )

    async def create(self, principal: Principal, data: ContestInput, key: UUID) -> ContestOut:
        digest = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
        async with self.factory() as db, db.begin():
            user = await self.actor(db, principal)
            existing = await db.scalar(
                select(Contest).where(Contest.owner_id == user.id, Contest.creation_key == key)
            )
            if existing:
                if existing.request_hash != digest:
                    raise AppError(
                        409,
                        "idempotency_conflict",
                        "This creation key was already used with different details",
                    )
                return await self.output(db, existing, user)
            await self.validate(db, data)
            c = Contest(
                owner_id=user.id,
                creation_key=key,
                request_hash=digest,
                **data.model_dump(exclude={"rules"}),
            )
            db.add(c)
            await db.flush()
            await self.append_rules(db, c, data.rules, 1)
            self.audit(db, user, "contest_created", c.id)
            await db.flush()
            return await self.output(db, c, user)

    async def revise(
        self, principal: Principal, identifier: UUID, data: ContestInput
    ) -> ContestOut:
        async with self.factory() as db, db.begin():
            user = await self.actor(db, principal)
            c = await self.load(db, identifier, user, lock=True)
            self.owner(c, user)
            if c.status != "draft":
                raise AppError(
                    409, "rules_frozen", "Published contest rules and schedule are frozen"
                )
            await self.validate(db, data)
            rule = await self.rules(db, c)
            for key, value in data.model_dump(exclude={"rules"}).items():
                setattr(c, key, value)
            await self.append_rules(db, c, data.rules, rule.version + 1)
            self.audit(db, user, "contest_rules_revised", c.id)
            await db.flush()
            return await self.output(db, c, user)

    async def transition(
        self, principal: Principal, identifier: UUID, action: Literal["publish", "cancel"]
    ) -> ContestOut:
        async with self.factory() as db, db.begin():
            user = await self.actor(db, principal)
            c = await self.load(db, identifier, user, lock=True)
            self.owner(c, user)
            if action == "publish":
                if c.status == "cancelled":
                    raise AppError(
                        409, "invalid_transition", "A cancelled contest cannot be published"
                    )
                if c.status == "draft":
                    rule = await self.rules(db, c)
                    await self.validate(
                        db,
                        ContestInput(
                            **{
                                key: getattr(c, key)
                                for key in ContestInput.model_fields
                                if key != "rules"
                            },
                            rules=await self.rule_input(db, rule),
                        ),
                    )
                    c.status = "scheduled"
                    c.status = phase(c, self.clock())
                    self.audit(db, user, "contest_published", c.id)
            elif c.status != "cancelled":
                if phase(c, self.clock()) not in {"draft", "scheduled", "open"}:
                    raise AppError(
                        409, "invalid_transition", "Cancellation is allowed only before entry locks"
                    )
                c.status = "cancelled"
                self.audit(db, user, "contest_cancelled", c.id)
            await db.flush()
            return await self.output(db, c, user)

    async def get(self, identifier: UUID, principal: Principal | None) -> ContestOut:
        ensure_fixture_mode(self.identity.settings)
        async with self.factory() as db, db.begin():
            user = await self.actor(db, principal, verified=False) if principal else None
            return await self.output(db, await self.load(db, identifier, user), user)

    async def listing(
        self,
        principal: Principal | None,
        *,
        query: str = "",
        visibility: Visibility | None = None,
        level: Level | None = None,
        status: Status | None = None,
        scope: Literal["discover", "joined", "hosted"] = "discover",
        sort: Literal["name", "-name"] = "name",
        cursor: str | None = None,
        limit: int = 20,
    ) -> ContestPage:
        ensure_fixture_mode(self.identity.settings)
        instant = self.clock()
        async with self.factory() as db, db.begin():
            user = await self.actor(db, principal, verified=False) if principal else None
            if scope != "discover" and user is None:
                raise AppError(401, "unauthenticated", "Please sign in")
            statement = select(Contest).where(self.visible(user, instant))
            if scope == "joined":
                assert user
                statement = statement.where(
                    exists().where(
                        ContestMembership.contest_id == Contest.id,
                        ContestMembership.user_id == user.id,
                    )
                )
            if scope == "hosted":
                assert user
                statement = statement.where(Contest.owner_id == user.id)
            if query.strip():
                escaped = (
                    query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                )
                statement = statement.where(
                    or_(
                        Contest.name.ilike(f"%{escaped}%", escape="\\"),
                        Contest.description.ilike(f"%{escaped}%", escape="\\"),
                    )
                )
            if visibility:
                statement = statement.where(Contest.visibility == visibility)
            if level:
                statement = statement.where(Contest.level == level)
            if status:
                effective = case(
                    (Contest.status.in_(["draft", "cancelled", "completed"]), Contest.status),
                    (Contest.ends_at <= instant, "settling"),
                    (Contest.starts_at <= instant, "running"),
                    (Contest.entry_closes_at <= instant, "locked"),
                    (Contest.entry_opens_at <= instant, "open"),
                    else_="scheduled",
                )
                statement = statement.where(effective == status)
            context = fingerprint(
                {
                    "query": query.strip(),
                    "visibility": visibility,
                    "level": level,
                    "status": status,
                    "scope": scope,
                    "sort": sort,
                    "user": str(user.id) if user else None,
                }
            )
            name = Contest.name.collate("C")
            if cursor:
                value, identifier = decode_cursor(cursor, context)
                statement = statement.where(
                    tuple_(name, Contest.id) < tuple_(value, identifier)
                    if sort.startswith("-")
                    else tuple_(name, Contest.id) > tuple_(value, identifier)
                )
            rows = (
                await db.scalars(
                    statement.order_by(
                        name.desc() if sort.startswith("-") else name,
                        Contest.id.desc() if sort.startswith("-") else Contest.id,
                    ).limit(limit + 1)
                )
            ).all()
            items = [await self.output(db, c, user) for c in rows[:limit]]
            return ContestPage(
                items=items,
                next_cursor=encode_cursor(rows[limit - 1].name, rows[limit - 1].id, context)
                if len(rows) > limit
                else None,
            )

    async def join_locked(self, db: AsyncSession, c: Contest, user: User) -> None:
        # Caller locks user -> session -> contest. Every seat allocation takes this contest lock.
        existing = await db.scalar(
            select(ContestMembership.id).where(
                ContestMembership.contest_id == c.id, ContestMembership.user_id == user.id
            )
        )
        if existing:
            return
        if phase(c, self.clock()) != "open":
            raise AppError(409, "entry_closed", "Contest is not open for entry")
        if c.visibility == "private" and c.owner_id != user.id:
            invite = await db.scalar(
                select(ContestInvitation)
                .where(
                    ContestInvitation.contest_id == c.id,
                    ContestInvitation.email == user.email,
                    ContestInvitation.status == "pending",
                    ContestInvitation.expires_at > self.clock(),
                )
                .with_for_update()
            )
            if invite is None:
                raise AppError(404, "contest_not_found", "Contest not found")
            invite.status = "accepted"
        count = await db.scalar(
            select(func.count())
            .select_from(ContestMembership)
            .where(ContestMembership.contest_id == c.id)
        )
        if count is not None and count >= c.capacity:
            raise AppError(409, "contest_full", "All contest seats are taken")
        rule = await self.rules(db, c)
        db.add(ContestMembership(contest_id=c.id, user_id=user.id, rule_id=rule.id))
        self.audit(db, user, "contest_joined", c.id)
        await db.flush()

    async def join(self, principal: Principal, identifier: UUID) -> ContestOut:
        async with self.factory() as db, db.begin():
            user = await self.actor(db, principal)
            c = await self.load(db, identifier, user, lock=True)
            await self.join_locked(db, c, user)
            return await self.output(db, c, user)

    def invitation_output(self, invitation: ContestInvitation, name: str) -> InvitationOut:
        status = (
            "expired"
            if invitation.status == "pending" and invitation.expires_at <= self.clock()
            else invitation.status
        )
        return InvitationOut(
            id=invitation.id,
            contest_id=invitation.contest_id,
            contest_name=name,
            status=cast(Literal["pending", "accepted", "declined", "revoked", "expired"], status),
            email=invitation.email,
            expires_at=invitation.expires_at,
        )

    async def invite(self, principal: Principal, identifier: UUID, email: str) -> InvitationOut:
        async with self.factory() as db, db.begin():
            user = await self.actor(db, principal)
            c = await self.load(db, identifier, user, lock=True)
            self.owner(c, user)
            if phase(c, self.clock()) not in {"scheduled", "open"}:
                raise AppError(
                    409, "entry_closed", "Publish the contest and invite before entry locks"
                )
            address = email.lower()
            invitation = await db.scalar(
                select(ContestInvitation).where(
                    ContestInvitation.contest_id == c.id, ContestInvitation.email == address
                )
            )
            if invitation:
                return self.invitation_output(invitation, c.name)
            count = await db.scalar(
                select(func.count())
                .select_from(ContestInvitation)
                .where(ContestInvitation.contest_id == c.id)
            )
            if count is not None and count >= 1000:
                raise AppError(
                    409, "invitation_limit", "A contest supports at most 1000 invitations"
                )
            invitation = ContestInvitation(
                contest_id=c.id,
                email=address,
                created_at=self.clock(),
                expires_at=min(c.entry_closes_at, self.clock() + timedelta(days=7)),
            )
            db.add(invitation)
            await db.flush()
            self.audit(db, user, "contest_invited", invitation.id)
            return self.invitation_output(invitation, c.name)

    async def invitations(
        self,
        principal: Principal,
        *,
        identifier: UUID | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> InvitationPage:
        async with self.factory() as db, db.begin():
            user = await self.actor(db, principal)
            query = select(ContestInvitation, Contest.name).join(
                Contest, Contest.id == ContestInvitation.contest_id
            )
            if identifier:
                c = await self.load(db, identifier, user)
                self.owner(c, user)
                query = query.where(Contest.id == identifier)
            else:
                query = query.where(
                    ContestInvitation.email == user.email,
                    Contest.status.not_in(["draft", "cancelled"]),
                )
            context = fingerprint(
                {"user": str(user.id), "contest": str(identifier), "kind": "invitations"}
            )
            if cursor:
                _, after = decode_cursor(cursor, context)
                query = query.where(ContestInvitation.id > after)
            rows = (await db.execute(query.order_by(ContestInvitation.id).limit(limit + 1))).all()
            return InvitationPage(
                items=[self.invitation_output(i, n) for i, n in rows[:limit]],
                next_cursor=encode_cursor("", rows[limit - 1][0].id, context)
                if len(rows) > limit
                else None,
            )

    async def invitation_action(
        self, principal: Principal, identifier: UUID, action: Literal["accept", "decline", "revoke"]
    ) -> InvitationOut:
        async with self.factory() as db, db.begin():
            user = await self.actor(db, principal)
            # Lookup before locking, then contest -> invitation, matching every invitation write.
            lookup = await db.get(ContestInvitation, identifier)
            if lookup is None:
                raise AppError(404, "invitation_not_found", "Invitation not found")
            c = await db.scalar(
                select(Contest).where(Contest.id == lookup.contest_id).with_for_update()
            )
            assert c
            i = await db.scalar(
                select(ContestInvitation)
                .where(ContestInvitation.id == identifier)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert i
            if (action == "revoke" and c.owner_id != user.id) or (
                action != "revoke" and i.email != user.email
            ):
                raise AppError(404, "invitation_not_found", "Invitation not found")
            desired = {"accept": "accepted", "decline": "declined", "revoke": "revoked"}[action]
            if i.status == desired:
                return self.invitation_output(i, c.name)
            if i.status != "pending" or i.expires_at <= self.clock():
                raise AppError(409, "invitation_unavailable", "Invitation is no longer pending")
            if action == "accept":
                await self.join_locked(db, c, user)
            i.status = desired
            self.audit(db, user, "contest_invitation_" + desired, i.id)
            await db.flush()
            return self.invitation_output(i, c.name)
