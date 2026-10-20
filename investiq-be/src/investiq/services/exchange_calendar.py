import json
from datetime import UTC, date, datetime, time, timedelta
from importlib.resources import files
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from investiq.adapters.market import EXCHANGE_TZ
from investiq.core.errors import AppError
from investiq.models.market import ExchangeSession


def calendar_rows() -> list[dict[str, Any]]:
    data = json.loads(files("investiq.data").joinpath("nse_calendar_2026.json").read_text())
    current, end = date.fromisoformat(data["start_date"]), date.fromisoformat(data["end_date"])
    rows = []
    while current <= end:
        key = current.isoformat()
        reason = data["unsupported"].get(key)
        status = "unsupported" if reason else "open"
        if status == "open" and (current.weekday() >= 5 or key in data["holidays"]):
            status, reason = "closed", data["holidays"].get(key, "Weekend")
        opening = closing = available = None
        if status == "open":
            opening = datetime.combine(
                current, time.fromisoformat(data["regular_open"]), EXCHANGE_TZ
            )
            closing = datetime.combine(
                current, time.fromisoformat(data["regular_close"]), EXCHANGE_TZ
            )
            available = closing + timedelta(minutes=data["publication_delay_minutes"])
        rows.append(
            dict(
                id=uuid5(NAMESPACE_URL, f"investiq.calendar:NSE:{key}"),
                exchange="NSE",
                session_date=current,
                status=status,
                reason=reason,
                opens_at=opening.astimezone(UTC) if opening else None,
                closes_at=closing.astimezone(UTC) if closing else None,
                available_at=available.astimezone(UTC) if available else None,
                calendar_version=data["version"],
                source=data["source"],
            )
        )
        current += timedelta(days=1)
    return rows


async def expected_session(db: AsyncSession, as_of: datetime) -> ExchangeSession:
    local_day = as_of.astimezone(EXCHANGE_TZ).date()
    today = await db.scalar(
        select(ExchangeSession).where(
            ExchangeSession.exchange == "NSE", ExchangeSession.session_date == local_day
        )
    )
    if today is None:
        raise AppError(
            503, "calendar_unavailable", "No reviewed exchange calendar covers this date"
        )
    previous = await db.scalar(
        select(ExchangeSession)
        .where(
            ExchangeSession.exchange == "NSE",
            ExchangeSession.status == "open",
            ExchangeSession.available_at <= as_of,
        )
        .order_by(ExchangeSession.session_date.desc())
        .limit(1)
    )
    if previous is None:
        raise AppError(503, "calendar_unavailable", "No completed, published session is covered")
    unsupported = await db.scalar(
        select(ExchangeSession.id)
        .where(
            ExchangeSession.exchange == "NSE",
            ExchangeSession.status == "unsupported",
            ExchangeSession.session_date > previous.session_date,
            ExchangeSession.session_date <= local_day,
        )
        .limit(1)
    )
    if unsupported:
        raise AppError(503, "unsupported_session", "A special exchange session needs review")
    return previous
