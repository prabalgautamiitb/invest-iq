"""Explicit, retry-safe local contest seed for an existing verified host."""

import argparse
import asyncio

from investiq.core.errors import AppError
from investiq.main import create_app
from investiq.services.contest import ContestService


async def seed(owner_email: str) -> None:
    app = create_app()
    try:
        async with app.router.lifespan_context(app):
            service: ContestService = app.state.contests
            result = await service.seed_draft(owner_email)
            print(f"Fixture draft {result.id}: {result.status}. Review and publish in the UI.")
    except AppError as exc:
        raise SystemExit(f"{exc.code}: {exc.message}") from None
    except Exception:
        raise SystemExit("contest_seed_failed: check migrations and local infrastructure") from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--owner-email", required=True, help="Existing verified account; no account is created"
    )
    arguments = parser.parse_args()
    asyncio.run(seed(arguments.owner_email))
