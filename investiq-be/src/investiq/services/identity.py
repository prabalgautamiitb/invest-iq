import asyncio
import calendar
import hmac
import logging
from collections.abc import Awaitable
from datetime import UTC, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investiq.adapters.mail import Mailer
from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.core.security import (
    DUMMY_HASH,
    Principal,
    csrf_for,
    digest,
    hash_password,
    hasher,
    now,
    secret,
    verify_password,
)
from investiq.models.identity import (
    AccountToken,
    AuditEvent,
    OnboardingResponse,
    Preferences,
    Privacy,
    ProfilePhoto,
    QuestionSet,
    Session,
    User,
)
from investiq.schemas.identity import (
    MeOut,
    OnboardingInput,
    OnboardingOut,
    PreferencesOut,
    PreferencesUpdate,
    PrivacyOut,
    PrivacyUpdate,
    ProfileUpdate,
    QuestionsOut,
    RegisterInput,
    SessionOut,
    SubscriptionInput,
    SubscriptionOut,
)
from investiq.services.profile_photo import normalize_photo

logger = logging.getLogger("investiq.identity")
RATE_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""
GENERIC_EMAIL_MESSAGE = (
    "If the account is eligible, an email will be sent. Please check your inbox."
)


class IdentityService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        settings: Settings,
        mailer: Mailer,
    ) -> None:
        self.factory, self.redis, self.settings, self.mailer = factory, redis, settings, mailer

    async def rate_limit(
        self,
        bucket: str,
        identifier: str,
        *,
        bootstrap: bool = False,
        limit: int | None = None,
        window_seconds: int | None = None,
    ) -> None:
        window = window_seconds or (60 if bootstrap else self.settings.auth_rate_window_seconds)
        limit = limit or (
            self.settings.csrf_rate_limit if bootstrap else self.settings.auth_rate_limit
        )
        key = f"{self.settings.rate_limit_prefix}:{bucket}:{digest(identifier)}"
        try:
            count = await cast(Awaitable[int], self.redis.eval(RATE_SCRIPT, 1, key, str(window)))
        except RedisError as exc:
            raise AppError(503, "rate_limit_unavailable", "Please try again later") from exc
        if int(count) > limit:
            raise AppError(
                429,
                "rate_limited",
                "Too many attempts. Try again later",
                headers={"Retry-After": str(window)},
            )

    async def principal(self, raw: str | None) -> Principal:
        if not raw or len(raw) > 128:
            raise AppError(401, "unauthenticated", "Please sign in")
        async with self.factory() as db:
            session = await db.scalar(
                select(Session).where(
                    Session.token_hash == digest(raw),
                    Session.revoked_at.is_(None),
                    Session.expires_at > now(),
                )
            )
            if session is None:
                raise AppError(401, "session_expired", "Your session expired. Please sign in again")
            user = await db.get(User, session.user_id) if session.user_id else None
            if session.user_id and (user is None or not user.active):
                raise AppError(401, "unauthenticated", "Please sign in")
            return Principal(session.id, session.user_id, user.role if user else None)

    async def bootstrap(self, raw: str | None) -> tuple[str, str, bool]:
        if raw:
            try:
                await self.principal(raw)
                return raw, csrf_for(raw), False
            except AppError:
                pass
        token = secret()
        async with self.factory() as db, db.begin():
            db.add(Session(token_hash=digest(token), expires_at=now() + timedelta(hours=1)))
        return token, csrf_for(token), True

    def validate_csrf(self, raw: str | None, supplied: str | None) -> None:
        if (
            not raw
            or not supplied
            or len(supplied) != 64
            or not supplied.isascii()
            or not hmac.compare_digest(csrf_for(raw), supplied)
        ):
            raise AppError(403, "csrf_failed", "Refresh the page and try again")

    async def _anonymous(self, db: AsyncSession, principal: Principal) -> Session:
        session = await db.get(Session, principal.session_id, with_for_update=True)
        if (
            session is None
            or session.revoked_at
            or session.expires_at <= now()
            or session.user_id is not None
        ):
            raise AppError(409, "session_changed", "Sign out before switching accounts")
        return session

    async def authenticated_user(self, db: AsyncSession, principal: Principal) -> User:
        if principal.user_id is None:
            raise AppError(401, "unauthenticated", "Please sign in")
        # All user mutations lock user -> session. Recovery/revocation use the same order.
        user = await db.get(User, principal.user_id, with_for_update=True)
        session = await db.get(Session, principal.session_id, with_for_update=True)
        if (
            user is None
            or not user.active
            or session is None
            or session.revoked_at
            or session.expires_at <= now()
            or session.user_id != user.id
        ):
            raise AppError(401, "session_expired", "Please sign in again")
        return user

    async def _new_session(self, db: AsyncSession, user: User) -> str:
        # The caller holds the user row lock. Keep the session collection bounded.
        oldest = (
            await db.scalars(
                select(Session)
                .where(
                    Session.user_id == user.id,
                    Session.revoked_at.is_(None),
                    Session.expires_at > now(),
                )
                .order_by(Session.created_at.desc(), Session.id.desc())
                .offset(19)
            )
        ).all()
        for previous in oldest:
            previous.revoked_at = now()
            db.add(
                AuditEvent(
                    actor_id=user.id, action="session_limit_revoked", resource_id=previous.id
                )
            )
        raw = secret()
        db.add(
            Session(
                user_id=user.id,
                token_hash=digest(raw),
                expires_at=now() + timedelta(days=self.settings.session_days),
            )
        )
        return raw

    async def _view(self, db: AsyncSession, user: User) -> MeOut:
        preferences = await db.get(Preferences, user.id)
        privacy = await db.get(Privacy, user.id)
        row = (
            await db.execute(
                select(OnboardingResponse, QuestionSet.version)
                .join(QuestionSet, OnboardingResponse.question_set_id == QuestionSet.id)
                .where(OnboardingResponse.user_id == user.id)
                .order_by(QuestionSet.version.desc())
                .limit(1)
            )
        ).first()
        onboarding = None
        if row:
            answer, version = row
            onboarding = OnboardingOut(
                version=version,
                answers=answer.answers,
                experience=answer.experience,
                learning_profile=answer.learning_profile,
                classification_version=answer.classification_version,
                completed_at=answer.completed_at,
            )
        return MeOut(
            id=user.id,
            email=user.email,
            name=user.name,
            photo_version=await db.scalar(
                select(ProfilePhoto.version).where(ProfilePhoto.user_id == user.id)
            ),
            role=cast(Literal["user", "admin"], user.role),
            email_verified=user.email_verified_at is not None,
            subscription=SubscriptionOut(
                plan=cast(Literal["student", "standard"], user.subscription_plan),
                status="active" if user.subscription_ends_at > now() else "expired",
                monthly_price_inr=99 if user.subscription_plan == "student" else 199,
                starts_at=user.subscription_starts_at,
                ends_at=user.subscription_ends_at,
            )
            if user.subscription_plan and user.subscription_starts_at and user.subscription_ends_at
            else None,
            weekly_goal=user.weekly_goal,
            preferences=PreferencesOut.model_validate(preferences),
            privacy=PrivacyOut.model_validate(privacy),
            onboarding=onboarding,
        )

    def _issue(self, db: AsyncSession, user: User, purpose: str) -> str:
        raw = secret()
        minutes = 60 * 24 if purpose == "verification" else 30
        db.add(
            AccountToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=digest(raw),
                expires_at=now() + timedelta(minutes=minutes),
            )
        )
        return raw

    async def _deliver(self, user_id: UUID, email: str, purpose: str, token: str) -> None:
        # No session/token secrets in audit data. Requests can be retried to issue a fresh link.
        action = f"{purpose}_email_sent"
        try:
            await self.mailer.send(email, purpose, token)
        except Exception as exc:
            action = f"{purpose}_email_failed"
            logger.warning("email_delivery_failed", extra={"exception_type": type(exc).__name__})
        async with self.factory() as db, db.begin():
            db.add(AuditEvent(actor_id=user_id, action=action))

    async def register(self, principal: Principal, data: RegisterInput) -> tuple[MeOut, str]:
        encoded = await hash_password(data.password.get_secret_value())
        try:
            async with self.factory() as db, db.begin():
                previous = await self._anonymous(db, principal)
                user = User(email=str(data.email), name=data.name, password_hash=encoded)
                db.add(user)
                await db.flush()
                db.add_all([Preferences(user_id=user.id), Privacy(user_id=user.id)])
                previous.revoked_at = now()
                raw = await self._new_session(db, user)
                verification = self._issue(db, user, "verification")
                db.add(AuditEvent(actor_id=user.id, action="registered"))
                await db.flush()
                output = await self._view(db, user)
        except IntegrityError as exc:
            raise AppError(
                409, "registration_conflict", "Unable to register with these details"
            ) from exc
        await self._deliver(user.id, user.email, "verification", verification)
        return output, raw

    async def login(self, principal: Principal, email: str, password: str) -> tuple[MeOut, str]:
        result: tuple[MeOut, str] | None = None
        async with self.factory() as db, db.begin():
            previous = await self._anonymous(db, principal)
            user = await db.scalar(select(User).where(User.email == email).with_for_update())
            valid = await verify_password(user.password_hash if user else DUMMY_HASH, password)
            if user is not None and user.active and valid:
                if hasher.check_needs_rehash(user.password_hash):
                    user.password_hash = await hash_password(password)
                previous.revoked_at = now()
                raw = await self._new_session(db, user)
                db.add(AuditEvent(actor_id=user.id, action="logged_in"))
                result = await self._view(db, user), raw
            else:
                db.add(AuditEvent(action="login_failed"))
        if result is None:
            raise AppError(401, "invalid_credentials", "Invalid email or password")
        return result

    async def me(self, principal: Principal) -> MeOut:
        async with self.factory() as db, db.begin():
            user = await self.authenticated_user(db, principal)
            return await self._view(db, user)

    async def start_subscription(self, principal: Principal, data: SubscriptionInput) -> MeOut:
        async with self.factory() as db, db.begin():
            user = await self.authenticated_user(db, principal)
            instant = now()
            if user.subscription_ends_at and user.subscription_ends_at > instant:
                if user.subscription_plan != data.plan:
                    raise AppError(
                        409,
                        "subscription_active",
                        "Your current subscription is active. Choose another plan after it ends.",
                    )
                # Retrying an accepted activation never extends the active term.
                return await self._view(db, user)
            local_start = instant.astimezone(ZoneInfo("Asia/Kolkata"))
            month = local_start.month % 12 + 1
            year = local_start.year + (local_start.month == 12)
            end = local_start.replace(
                year=year,
                month=month,
                day=min(local_start.day, calendar.monthrange(year, month)[1]),
            )
            user.subscription_plan = data.plan
            user.subscription_starts_at = instant
            user.subscription_ends_at = end.astimezone(UTC)
            user.updated_at = instant
            db.add(AuditEvent(actor_id=user.id, action="subscription.started", resource_id=user.id))
            return await self._view(db, user)

    async def logout(self, principal: Principal) -> None:
        async with self.factory() as db, db.begin():
            user = await self.authenticated_user(db, principal)
            session = await db.get(Session, principal.session_id)
            assert session is not None
            session.revoked_at = now()
            db.add(AuditEvent(actor_id=user.id, action="logged_out", resource_id=session.id))

    async def sessions(self, principal: Principal) -> list[SessionOut]:
        async with self.factory() as db, db.begin():
            user = await self.authenticated_user(db, principal)
            sessions = (
                await db.scalars(
                    select(Session)
                    .where(
                        Session.user_id == user.id,
                        Session.revoked_at.is_(None),
                        Session.expires_at > now(),
                    )
                    .order_by(Session.created_at.desc())
                )
            ).all()
            return [
                SessionOut(
                    id=s.id,
                    current=s.id == principal.session_id,
                    created_at=s.created_at,
                    expires_at=s.expires_at,
                )
                for s in sessions
            ]

    async def revoke(self, principal: Principal, session_id: UUID) -> None:
        async with self.factory() as db, db.begin():
            user = await self.authenticated_user(db, principal)
            target = await db.scalar(
                select(Session)
                .where(Session.id == session_id, Session.user_id == user.id)
                .with_for_update()
            )
            if target is None:
                raise AppError(404, "session_not_found", "Session not found")
            target.revoked_at = target.revoked_at or now()
            db.add(AuditEvent(actor_id=user.id, action="session_revoked", resource_id=target.id))

    async def patch(
        self, principal: Principal, data: ProfileUpdate | PreferencesUpdate | PrivacyUpdate
    ) -> MeOut:
        async with self.factory() as db, db.begin():
            user = await self.authenticated_user(db, principal)
            target: User | Preferences | Privacy | None = user
            action = "profile_updated"
            if isinstance(data, PreferencesUpdate):
                target, action = await db.get(Preferences, user.id), "preferences_updated"
            elif isinstance(data, PrivacyUpdate):
                target, action = await db.get(Privacy, user.id), "privacy_updated"
            assert target is not None
            for key, value in data.model_dump(exclude_unset=True).items():
                setattr(target, key, value)
            user.updated_at = now()
            db.add(AuditEvent(actor_id=user.id, action=action))
            await db.flush()
            return await self._view(db, user)

    async def photo(self, principal: Principal) -> bytes:
        async with self.factory() as db, db.begin():
            user = await self.authenticated_user(db, principal)
            photo = await db.get(ProfilePhoto, user.id)
            if photo is None:
                raise AppError(404, "photo_not_found", "No profile photo saved")
            return photo.image

    async def save_photo(self, principal: Principal, raw: bytes | None) -> MeOut:
        async with self.factory() as db, db.begin():
            user = await self.authenticated_user(db, principal)
            photo = await db.get(ProfilePhoto, user.id)
            if raw is None:
                if photo is not None:
                    await db.delete(photo)
            else:
                normalized = await asyncio.to_thread(normalize_photo, raw)
                if photo is None:
                    db.add(ProfilePhoto(user_id=user.id, image=normalized, version=uuid4()))
                else:
                    photo.image, photo.version, photo.updated_at = normalized, uuid4(), now()
            user.updated_at = now()
            db.add(
                AuditEvent(
                    actor_id=user.id,
                    action="profile_photo_removed" if raw is None else "profile_photo_updated",
                )
            )
            await db.flush()
            return await self._view(db, user)

    async def questions(self) -> QuestionsOut:
        async with self.factory() as db:
            row = await db.scalar(
                select(QuestionSet)
                .where(QuestionSet.active.is_(True))
                .order_by(QuestionSet.version.desc())
                .limit(1)
            )
            if row is None:
                raise AppError(
                    503, "onboarding_unavailable", "Onboarding is temporarily unavailable"
                )
            return QuestionsOut.model_validate({"version": row.version, "questions": row.questions})

    async def onboard(self, principal: Principal, data: OnboardingInput) -> MeOut:
        async with self.factory() as db, db.begin():
            user = await self.authenticated_user(db, principal)
            question_set = await db.scalar(
                select(QuestionSet).where(
                    QuestionSet.version == data.version, QuestionSet.active.is_(True)
                )
            )
            if question_set is None:
                raise AppError(409, "question_version_changed", "Reload the current question set")
            approved = {q["id"]: {o["id"] for o in q["options"]} for q in question_set.questions}
            if set(data.answers) != set(approved) or any(
                choice not in approved[q] for q, choice in data.answers.items()
            ):
                raise AppError(
                    422, "invalid_answers", "Choose one approved option for each question"
                )
            experience_choice = data.answers["experience"]
            experience = {
                "experience:0": "beginner",
                "experience:1": "beginner",
                "experience:2": "intermediate",
                "experience:3": "advanced",
            }[experience_choice]
            profile = {
                "beginner": "Foundation Explorer",
                "intermediate": "Confident Builder",
                "advanced": "Strategy Explorer",
            }[experience]
            row = await db.get(OnboardingResponse, (user.id, question_set.id))
            if row is None:
                row = OnboardingResponse(user_id=user.id, question_set_id=question_set.id)
                db.add(row)
            row.answers, row.experience, row.learning_profile = data.answers, experience, profile
            row.classification_version, row.completed_at = 1, now()
            user.weekly_goal = {"pace:0": 35, "pace:1": 105, "pace:2": 210, "pace:3": 75}[
                data.answers["pace"]
            ]
            user.updated_at = now()
            db.add(AuditEvent(actor_id=user.id, action="onboarding_completed"))
            await db.flush()
            return await self._view(db, user)

    async def request_token(self, email: str, purpose: str) -> None:
        delivery: tuple[UUID, str, str] | None = None
        async with self.factory() as db, db.begin():
            user = await db.scalar(select(User).where(User.email == email).with_for_update())
            if (
                user
                and user.active
                and (purpose != "verification" or user.email_verified_at is None)
            ):
                await db.execute(
                    update(AccountToken)
                    .where(
                        AccountToken.user_id == user.id,
                        AccountToken.purpose == purpose,
                        AccountToken.used_at.is_(None),
                    )
                    .values(used_at=now())
                )
                raw = self._issue(db, user, purpose)
                db.add(AuditEvent(actor_id=user.id, action=f"{purpose}_requested"))
                delivery = user.id, user.email, raw
        if delivery:
            user_id, recipient, token = delivery
            await self._deliver(user_id, recipient, purpose, token)

    async def complete_token(self, raw: str, purpose: str, password: str | None = None) -> None:
        encoded = await hash_password(password) if password is not None else None
        async with self.factory() as db, db.begin():
            # Read only the owner first; lock user before token/session to avoid lock inversion.
            owner = await db.scalar(
                select(AccountToken.user_id).where(
                    AccountToken.token_hash == digest(raw), AccountToken.purpose == purpose
                )
            )
            if owner is None:
                raise AppError(400, "invalid_token", "This link is invalid or expired")
            user = await db.get(User, owner, with_for_update=True)
            token = await db.scalar(
                select(AccountToken)
                .where(AccountToken.token_hash == digest(raw), AccountToken.purpose == purpose)
                .with_for_update()
            )
            if (
                not user
                or not user.active
                or not token
                or token.used_at
                or token.expires_at <= now()
            ):
                raise AppError(400, "invalid_token", "This link is invalid or expired")
            token.used_at = now()
            if purpose == "verification":
                user.email_verified_at = user.email_verified_at or now()
            else:
                assert encoded is not None
                user.password_hash = encoded
                await db.execute(
                    update(Session)
                    .where(Session.user_id == user.id, Session.revoked_at.is_(None))
                    .values(revoked_at=now())
                )
                await db.execute(
                    update(AccountToken)
                    .where(
                        AccountToken.user_id == user.id,
                        AccountToken.purpose == purpose,
                        AccountToken.used_at.is_(None),
                    )
                    .values(used_at=now())
                )
            user.updated_at = now()
            db.add(AuditEvent(actor_id=user.id, action=f"{purpose}_completed"))

    async def admin_user(self, principal: Principal, user_id: UUID) -> MeOut:
        async with self.factory() as db, db.begin():
            actor = await self.authenticated_user(db, principal)
            if actor.role != "admin":
                raise AppError(403, "forbidden", "Administrator access required")
            target = await db.get(User, user_id)
            if target is None:
                raise AppError(404, "user_not_found", "User not found")
            db.add(AuditEvent(actor_id=actor.id, action="admin_profile_read", resource_id=user_id))
            return await self._view(db, target)
