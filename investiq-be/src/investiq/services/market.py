import base64
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import Select, and_, exists, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investiq.adapters.market import EXCHANGE_TZ
from investiq.core.config import Settings
from investiq.core.errors import AppError
from investiq.core.security import now
from investiq.models.market import (
    ExchangeSession,
    IngestionRun,
    Instrument,
    MarketExclusion,
    PriceSnapshot,
    Sector,
)
from investiq.schemas.market import (
    InstrumentKind,
    InstrumentOut,
    InstrumentPage,
    MarketCap,
    QuoteBatchOut,
    QuoteOut,
    SectorOut,
    SectorPage,
    SessionOut,
    SessionPage,
)
from investiq.services.exchange_calendar import expected_session
from investiq.services.market_ingestion import ensure_fixture_mode


def fingerprint(filters: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest()[:24]


def encode_cursor(value: str, identifier: UUID, context: str) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps([value, str(identifier), context]).encode())
        .decode()
        .rstrip("=")
    )


def decode_cursor(cursor: str, context: str) -> tuple[str, UUID]:
    try:
        if len(cursor) > 1024:
            raise ValueError
        data = json.loads(
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        )
        if (
            not isinstance(data, list)
            or len(data) != 3
            or data[2] != context
            or not isinstance(data[0], str)
            or not isinstance(data[1], str)
        ):
            raise ValueError
        return data[0], UUID(data[1])
    except (ValueError, TypeError, UnicodeError) as exc:
        raise AppError(
            422, "invalid_cursor", "Use a cursor from the same filter and sort query"
        ) from exc


def excluded_on(day: date) -> Select[UUID]:
    return select(MarketExclusion.instrument_id).where(
        MarketExclusion.starts_on <= day,
        or_(MarketExclusion.ends_on.is_(None), MarketExclusion.ends_on >= day),
    )


class MarketService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.factory, self.settings = factory, settings
        self.clock = clock or now

    async def sectors(self) -> SectorPage:
        ensure_fixture_mode(self.settings)
        async with self.factory() as db:
            rows = (await db.scalars(select(Sector).order_by(Sector.name))).all()
            if not rows:
                raise AppError(
                    503, "market_not_initialized", "Initialize the development market dataset"
                )
            return SectorPage(items=[SectorOut.model_validate(row) for row in rows])

    async def instruments(
        self,
        *,
        query: str,
        sector: UUID | None,
        market_cap: MarketCap | None,
        kind: InstrumentKind,
        eligible_only: bool,
        sort: str,
        cursor: str | None,
        limit: int,
    ) -> InstrumentPage:
        ensure_fixture_mode(self.settings)
        query = query.strip().casefold()
        ordering = (
            Instrument.symbol if sort in {"symbol", "-symbol"} else Instrument.name
        ).collate("C")
        descending = sort.startswith("-")
        day = self.clock().astimezone(EXCHANGE_TZ).date()
        context = fingerprint(
            dict(
                query=query,
                sector=str(sector),
                market_cap=market_cap,
                kind=kind,
                eligible_only=eligible_only,
                sort=sort,
                day=day.isoformat(),
            )
        )
        async with self.factory() as db:
            if not await db.scalar(select(exists().where(Instrument.data_kind == "fixture"))):
                raise AppError(
                    503, "market_not_initialized", "Initialize the development market dataset"
                )
            statement = (
                select(Instrument, Sector)
                .outerjoin(Sector, Instrument.sector_id == Sector.id)
                .where(Instrument.kind == kind, Instrument.data_kind == "fixture")
            )
            if query:
                # Escape wildcards: search text is literal user text, never SQL syntax.
                statement = statement.where(
                    or_(
                        Instrument.symbol.icontains(query, autoescape=True),
                        Instrument.name.icontains(query, autoescape=True),
                    )
                )
            if sector is not None:
                statement = statement.where(Instrument.sector_id == sector)
            if market_cap is not None:
                statement = statement.where(Instrument.market_cap == market_cap)
            if eligible_only:
                statement = statement.where(
                    Instrument.active.is_(True), ~Instrument.id.in_(excluded_on(day))
                )
            if cursor:
                value, identifier = decode_cursor(cursor, context)
                boundary = tuple_(ordering, Instrument.id)
                statement = statement.where(
                    boundary < (value, identifier) if descending else boundary > (value, identifier)
                )
            columns = (
                (ordering.desc(), Instrument.id.desc())
                if descending
                else (ordering.asc(), Instrument.id.asc())
            )
            rows = (await db.execute(statement.order_by(*columns).limit(limit + 1))).all()
            blocked = set((await db.scalars(excluded_on(day))).all())
            items = [
                InstrumentOut(
                    id=i.id,
                    symbol=i.symbol,
                    name=i.name,
                    exchange=i.exchange,
                    kind=cast(InstrumentKind, i.kind),
                    currency=cast(Literal["INR", "POINTS"], i.currency),
                    sector=SectorOut.model_validate(s) if s else None,
                    market_cap=cast(MarketCap | None, i.market_cap),
                    active=i.active,
                    excluded=i.id in blocked,
                )
                for i, s in rows[:limit]
            ]
            next_cursor = None
            if len(rows) > limit:
                last = rows[limit - 1][0]
                next_cursor = encode_cursor(
                    last.symbol if "symbol" in sort else last.name, last.id, context
                )
            return InstrumentPage(items=items, next_cursor=next_cursor)

    async def sessions(self, start_date: date, end_date: date) -> SessionPage:
        ensure_fixture_mode(self.settings)
        if end_date < start_date or (end_date - start_date).days > 365:
            raise AppError(
                422, "invalid_calendar_range", "Request an ordered date range of at most 366 days"
            )
        async with self.factory() as db:
            rows = (
                await db.scalars(
                    select(ExchangeSession)
                    .where(
                        ExchangeSession.exchange == "NSE",
                        ExchangeSession.session_date.between(start_date, end_date),
                    )
                    .order_by(ExchangeSession.session_date)
                )
            ).all()
            if len(rows) != (end_date - start_date).days + 1:
                raise AppError(
                    503,
                    "calendar_unavailable",
                    "The requested range is not fully covered by a reviewed calendar",
                )
            return SessionPage(items=[SessionOut.model_validate(row) for row in rows])

    async def quotes(
        self, identifiers: list[UUID], as_of: datetime | None, require_complete: bool
    ) -> QuoteBatchOut:
        ensure_fixture_mode(self.settings)
        if not 1 <= len(identifiers) <= 100:
            raise AppError(422, "invalid_instrument_ids", "Request 1–100 instrument IDs")
        if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
            raise AppError(422, "invalid_quote_cutoff", "Use a timezone-aware quote cutoff")
        cutoff = (as_of or self.clock()).astimezone(UTC)
        if cutoff > self.clock():
            raise AppError(422, "future_quotes_forbidden", "Quote cutoffs cannot be in the future")
        if len(identifiers) != len(set(identifiers)):
            raise AppError(422, "duplicate_instruments", "Request distinct instrument IDs")
        async with self.factory() as db:
            instruments = {
                i.id: i
                for i in (
                    await db.scalars(
                        select(Instrument).where(
                            Instrument.id.in_(identifiers), Instrument.data_kind == "fixture"
                        )
                    )
                ).all()
            }
            if len(instruments) != len(identifiers):
                raise AppError(
                    404, "instrument_not_found", "One or more instrument IDs are unknown"
                )
            expected = await expected_session(db, cutoff)
            snapshots = (
                select(
                    PriceSnapshot,
                    IngestionRun.provider,
                    IngestionRun.dataset_version,
                    func.row_number()
                    .over(
                        partition_by=PriceSnapshot.instrument_id,
                        order_by=PriceSnapshot.session_date.desc(),
                    )
                    .label("position"),
                )
                .join(IngestionRun, PriceSnapshot.run_id == IngestionRun.id)
                .where(
                    PriceSnapshot.instrument_id.in_(identifiers),
                    PriceSnapshot.session_date <= expected.session_date,
                    PriceSnapshot.source_published_at <= cutoff,
                    IngestionRun.status == "succeeded",
                    IngestionRun.provider == "investiq-synthetic",
                    IngestionRun.dataset_version == "fixture-v1",
                )
                .subquery()
            )
            # Select ORM records through their IDs; no per-instrument queries.
            rows = (
                await db.execute(
                    select(PriceSnapshot, snapshots.c.provider, snapshots.c.dataset_version).join(
                        snapshots,
                        and_(PriceSnapshot.id == snapshots.c.id, snapshots.c.position == 1),
                    )
                )
            ).all()
            latest = {p.instrument_id: (p, provider, version) for p, provider, version in rows}
            exclusions = (
                await db.execute(
                    select(MarketExclusion.instrument_id, MarketExclusion.reason).where(
                        MarketExclusion.instrument_id.in_(identifiers),
                        MarketExclusion.starts_on <= cutoff.astimezone(EXCHANGE_TZ).date(),
                        or_(
                            MarketExclusion.ends_on.is_(None),
                            MarketExclusion.ends_on >= expected.session_date,
                        ),
                    )
                )
            ).all()
            blocked = dict(exclusions)
            items = []
            for identifier in identifiers:
                instrument = instruments[identifier]
                row = latest.get(identifier)
                price, provider, version = row if row else (None, None, None)
                freshness: Literal["current_eod", "stale", "missing"] = (
                    "missing"
                    if price is None
                    else ("current_eod" if price.session_date == expected.session_date else "stale")
                )
                reason = (
                    "Instrument is inactive" if not instrument.active else blocked.get(identifier)
                )
                items.append(
                    QuoteOut(
                        instrument_id=identifier,
                        symbol=instrument.symbol,
                        currency=instrument.currency,
                        close=price.close if price else None,
                        session_date=price.session_date if price else None,
                        observed_at=price.observed_at if price else None,
                        source_published_at=price.source_published_at if price else None,
                        ingested_at=price.ingested_at if price else None,
                        source=provider,
                        dataset_version=version,
                        freshness=freshness,
                        blocked_reason=reason,
                        eligible_for_simulation=freshness == "current_eod" and reason is None,
                    )
                )
            complete = all(item.eligible_for_simulation for item in items)
            if require_complete and not complete:
                raise AppError(
                    409,
                    "market_data_incomplete",
                    "Prices are missing, stale or ineligible for the common session",
                )
            return QuoteBatchOut(
                as_of=cutoff,
                expected_session_date=expected.session_date,
                calendar_version=expected.calendar_version,
                all_current=complete,
                items=items,
            )
