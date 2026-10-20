"""Run the same simulation valuation service used by the periodic worker."""

import argparse
import asyncio
import json
from uuid import UUID

from investiq.core.errors import AppError
from investiq.jobs.valuation import execute


async def main(identifier: UUID | None) -> None:
    try:
        result = await execute(identifier=identifier)
        print(json.dumps(result, sort_keys=True))
    except AppError as exc:
        raise SystemExit(f"{exc.code}: {exc.message}") from None
    except Exception:
        raise SystemExit("valuation_failed: check migrations and local infrastructure") from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contest-id", type=UUID, help="Process one contest; omit to scan due contests"
    )
    options = parser.parse_args()
    asyncio.run(main(options.contest_id))
