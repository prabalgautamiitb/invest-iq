"""Dated, unadjusted EOD bars; never substitute latest quotes for a missing session."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from typing import Any
from uuid import UUID

from investiq.adapters.market import EXCHANGE_TZ
from investiq.core.errors import AppError
from investiq.core.security import now
from investiq.schemas.market import PricePoint, ProviderBatch
from investiq.services.market_sources import YAHOO_DATASET, YAHOO_PROVIDER


def yahoo_catalogue() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(
        files("investiq.data").joinpath("yahoo_catalogue_v2.json").read_text()
    )
    return document


def yahoo_pricing_instruments() -> list[dict[str, Any]]:
    document = yahoo_catalogue()
    return list(document["instruments"]) + list(document["legacy_instruments"])


def download_bars(tickers: list[str], day: date) -> dict[str, list[dict[str, str]]]:
    import yfinance as yf  # type: ignore[import-untyped]

    frame = yf.download(
        tickers=tickers,
        start=day.isoformat(),
        end=(day + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        back_adjust=False,
        actions=True,
        repair=False,
        keepna=True,
        threads=4,
        progress=False,
        ignore_tz=False,
        group_by="ticker",
        multi_level_index=True,
        timeout=10,
    )
    if frame is None or frame.empty:
        return {}
    result: dict[str, list[dict[str, str]]] = {}
    for ticker in tickers:
        if ticker not in frame.columns.get_level_values(0):
            continue
        bars = []
        for stamp, row in frame[ticker].iterrows():
            if stamp.tzinfo is None:
                raise AppError(422, "invalid_price_timestamp", "Yahoo returned undated local bars")
            bars.append(
                {
                    "session_date": stamp.tz_convert(EXCHANGE_TZ).date().isoformat(),
                    "open": str(row.get("Open")),
                    "close": str(row.get("Close")),
                    "split": str(row.get("Stock Splits", "0")),
                }
            )
        result[ticker] = bars
    return result


class YahooMarketProvider:
    provider = YAHOO_PROVIDER
    dataset_version = YAHOO_DATASET

    def __init__(
        self,
        timeout: int = 45,
        loader: Callable[[list[str], date], dict[str, list[dict[str, str]]]] = download_bars,
        clock: Callable[[], datetime] = now,
    ) -> None:
        self.timeout, self.loader, self.clock = timeout, loader, clock

    async def fetch_eod(self, session_date: date) -> ProviderBatch:
        # 18:00 is our availability policy, not a claim about Yahoo's publication time.
        available = datetime.combine(session_date, time(18), EXCHANGE_TZ).astimezone(UTC)
        if self.clock() < available:
            raise AppError(409, "session_not_published", "Awaiting this session's closing prices")
        catalogue = yahoo_pricing_instruments()
        try:
            bars = await asyncio.wait_for(
                asyncio.to_thread(self.loader, [i["ticker"] for i in catalogue], session_date),
                timeout=self.timeout,
            )
            points = []
            for instrument in catalogue:
                rows = bars.get(instrument["ticker"], [])
                if len(rows) != 1 or rows[0].get("session_date") != session_date.isoformat():
                    raise AppError(
                        409, "market_data_incomplete", "Awaiting a complete dated Yahoo EOD batch"
                    )
                row = rows[0]
                split = Decimal(row.get("split", "0"))
                if not split.is_finite() or split != 0:
                    raise AppError(
                        409,
                        "unsupported_corporate_action",
                        "A stock split requires review before this session can be valued",
                    )
                opening, close = Decimal(row["open"]), Decimal(row["close"])
                if not all(p.is_finite() and p > 0 for p in (opening, close)):
                    raise AppError(409, "market_data_incomplete", "Yahoo EOD prices are missing")
                points.append(
                    PricePoint(
                        instrument_id=UUID(instrument["id"]),
                        open=opening.quantize(Decimal("0.0001")),
                        close=close.quantize(Decimal("0.0001")),
                    )
                )
            return ProviderBatch(
                provider=self.provider,
                dataset_version=self.dataset_version,
                data_kind="yahoo",
                session_date=session_date,
                observed_at=datetime.combine(session_date, time(15, 30), EXCHANGE_TZ),
                # We only know when we retrieved the data; historical imports cannot be
                # used as information that was available before their actual import.
                source_published_at=self.clock(),
                points=tuple(points),
            )
        except AppError:
            raise
        except (InvalidOperation, ValueError, KeyError, TypeError):
            raise AppError(
                422, "invalid_provider_batch", "Yahoo returned invalid EOD bars"
            ) from None
        except Exception:
            raise AppError(
                503, "provider_failed", "Yahoo EOD download failed; retry later"
            ) from None
