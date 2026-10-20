import asyncio
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
# A fixed valid dummy hash costs the same verify work without hashing on the request path.
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


def now() -> datetime:
    return datetime.now(UTC)


def secret() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_for(token: str) -> str:
    # Domain separation; the high-entropy HttpOnly cookie is the HMAC key.
    return hmac.new(token.encode(), b"investiq.csrf.v1", hashlib.sha256).hexdigest()


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(hasher.hash, password)


async def verify_password(encoded: str, password: str) -> bool:
    def check() -> bool:
        try:
            return hasher.verify(encoded, password)
        except VerificationError:
            return False

    return await asyncio.to_thread(check)


@dataclass(frozen=True)
class Principal:
    session_id: UUID
    user_id: UUID | None
    role: str | None
