"""Operator-only role provisioning; credentials are never accepted on the command line."""

import argparse
import asyncio

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.core.config import Settings
from investiq.core.security import now
from investiq.db.session import make_engine
from investiq.models.identity import AuditEvent, Session, User


async def set_role(email: str, role: str) -> None:
    engine = make_engine(Settings())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db, db.begin():
            user = await db.scalar(select(User).where(User.email == email).with_for_update())
            if user is None:
                raise SystemExit("Account not found")
            if role == "admin" and user.email_verified_at is None:
                raise SystemExit("Verify the account email before assigning administrator access")
            user.role, user.updated_at = role, now()
            await db.execute(
                update(Session)
                .where(Session.user_id == user.id, Session.revoked_at.is_(None))
                .values(revoked_at=now())
            )
            db.add(AuditEvent(action=f"operator_role_{role}", resource_id=user.id))
        print("Role updated; existing account sessions were revoked.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["set-role"])
    parser.add_argument("email")
    parser.add_argument("role", choices=["user", "admin"])
    args = parser.parse_args()
    email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
    asyncio.run(set_role(email, args.role))


if __name__ == "__main__":
    main()
