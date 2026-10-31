"""A shared, fail-closed allowance for optional free-demo AI generations."""

from investiq.core.errors import AppError
from investiq.core.security import now
from investiq.services.identity import IdentityService


async def reserve_generation(identity: IdentityService) -> None:
    if identity.settings.deployment_mode != "free_demo":
        return
    try:
        # A single atomic Redis counter across API instances, batch jobs and users.
        # Date-qualified keys reset at UTC midnight, including for failed attempts.
        await identity.rate_limit(
            "ai_daily",
            now().date().isoformat(),
            limit=identity.settings.free_demo_ai_daily_limit,
            window_seconds=86400,
        )
    except AppError as exc:
        if exc.code != "rate_limited":
            raise
        raise AppError(
            429, "daily_ai_limit", "Today's demo AI allowance is used. Try again tomorrow."
        ) from None
