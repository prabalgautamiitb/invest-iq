from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime

from investiq.core.errors import AppError
from investiq.schemas.market import (
    InstrumentKind,
    InstrumentPage,
    MarketCap,
    QuoteBatchOut,
    SectorPage,
    SessionPage,
)
from investiq.services.market import MarketService

router = APIRouter(tags=["market data"])


def service(request: Request) -> MarketService:
    result: MarketService = request.app.state.market
    return result


Service = Annotated[MarketService, Depends(service)]


@router.get("/sectors", response_model=SectorPage)
async def sectors(market: Service) -> SectorPage:
    return await market.sectors()


@router.get("/instruments", response_model=InstrumentPage)
async def instruments(
    market: Service,
    query: Annotated[str, Query(max_length=100)] = "",
    sector: UUID | None = None,
    market_cap: MarketCap | None = None,
    kind: InstrumentKind = "equity",
    eligible_only: bool = True,
    sort: Literal["symbol", "-symbol", "name", "-name"] = "symbol",
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> InstrumentPage:
    return await market.instruments(
        query=query,
        sector=sector,
        market_cap=market_cap,
        kind=kind,
        eligible_only=eligible_only,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )


@router.get("/market/sessions", response_model=SessionPage)
async def sessions(market: Service, start_date: date, end_date: date) -> SessionPage:
    return await market.sessions(start_date, end_date)


@router.get("/quotes", response_model=QuoteBatchOut)
async def quotes(
    market: Service,
    instrument_ids: Annotated[str, Query(min_length=1, max_length=3700)],
    as_of: AwareDatetime | None = None,
    require_complete: bool = False,
) -> QuoteBatchOut:
    try:
        values = instrument_ids.split(",")
        if len(values) > 100:
            raise ValueError
        identifiers = [UUID(value.strip()) for value in values]
    except ValueError as exc:
        raise AppError(
            422, "invalid_instrument_ids", "Provide 1–100 comma-separated UUIDs"
        ) from exc
    return await market.quotes(identifiers, as_of, require_complete)
