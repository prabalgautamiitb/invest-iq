"""Shared publisher headlines. HTTP reads never fetch RSS; Celery refreshes Redis."""

import hashlib
import html
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
from xml.etree import ElementTree

import httpx
from pydantic import HttpUrl
from redis.asyncio import Redis

from investiq.core.config import Settings
from investiq.core.security import now
from investiq.schemas.news import MarketNewsOut, NewsArticle
from investiq.services.exchange_calendar import calendar_rows

logger = logging.getLogger("investiq.news")
FEED_URL = "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
CACHE_KEY = "investiq:market-news:v1"
LOCK_KEY = CACHE_KEY + ":lock"
COOLDOWN_KEY = CACHE_KEY + ":cooldown"
MAX_FEED_BYTES = 1_000_000


@lru_cache(maxsize=1)
def refresh_windows() -> tuple[tuple[datetime, datetime], ...]:
    """Use the same reviewed holiday/special-session calendar as portfolio valuations."""
    slots = []
    for day in calendar_rows():
        if day["status"] != "open":
            continue
        slot = day["opens_at"]
        while slot <= day["closes_at"]:
            slots.append((slot, min(slot + timedelta(hours=1), day["closes_at"])))
            slot += timedelta(hours=1)
    return tuple(slots)


def schedule_at(at: datetime) -> tuple[datetime | None, datetime | None]:
    windows = refresh_windows()
    # A due slot only belongs to the current market session, not an earlier day.
    due = next((start for start, end in reversed(windows) if start <= at < end), None)
    upcoming = next((start for start, _ in windows if start > at), None)
    return due, upcoming


def parse_feed(content: bytes, at: datetime) -> list[NewsArticle]:
    if len(content) > MAX_FEED_BYTES or b"<!DOCTYPE" in content.upper():
        raise ValueError("Unsupported RSS payload")
    root = ElementTree.fromstring(content)
    articles: list[NewsArticle] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for item in root.findall("./channel/item"):
        title = html.unescape(re.sub(r"<[^>]+>", "", item.findtext("title") or ""))
        title = " ".join(title.split())[:500]
        parts = urlsplit((item.findtext("link") or "").strip())
        if (
            parts.scheme != "https"
            or parts.hostname != "economictimes.indiatimes.com"
            or parts.username
            or parts.password
            or not title
        ):
            continue
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
            if published.tzinfo is None:
                continue
            published = published.astimezone(UTC)
        except (ValueError, TypeError, OverflowError):
            continue
        if published > at + timedelta(minutes=5) or published < at - timedelta(days=7):
            continue
        if url in seen_urls or title.casefold() in seen_titles:
            continue
        seen_urls.add(url)
        seen_titles.add(title.casefold())
        articles.append(
            NewsArticle(
                id=hashlib.sha256(url.encode()).hexdigest()[:16],
                title=title,
                url=HttpUrl(url),
                source="The Economic Times",
                published_at=published,
            )
        )
    # Publisher markets feed, newest first; no invented relevance or impact scores.
    return sorted(articles, key=lambda a: a.published_at, reverse=True)[:5]


async def fetch_headlines(at: datetime) -> list[NewsArticle]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        async with client.stream(
            "GET",
            FEED_URL,
            headers={
                "User-Agent": "InvestIQ/1.0 RSS Reader",
                "Accept": "application/rss+xml, application/xml",
            },
        ) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_FEED_BYTES:
                    raise ValueError("RSS payload too large")
    return parse_feed(bytes(content), at)


class MarketNewsService:
    def __init__(
        self,
        redis: Redis,
        settings: Settings,
        clock: Callable[[], datetime] = now,
        fetch: Callable[[datetime], Awaitable[list[NewsArticle]]] = fetch_headlines,
    ) -> None:
        self.redis, self.settings, self.clock, self.fetch = redis, settings, clock, fetch

    async def read(self) -> MarketNewsOut:
        at = self.clock()
        _, upcoming = schedule_at(at)
        if not self.settings.market_news_enabled:
            return MarketNewsOut(status="disabled", next_refresh_at=upcoming)
        try:
            raw = await self.redis.get(CACHE_KEY)
            result = MarketNewsOut.model_validate_json(raw) if raw else MarketNewsOut()
        except Exception:
            logger.warning("news_cache_unavailable")
            result = MarketNewsOut()
        result.next_refresh_at = upcoming
        if result.items and result.updated_at:
            result.status = "stale" if at - result.updated_at > timedelta(minutes=90) else "ready"
        return result

    async def refresh(self) -> dict[str, object]:
        if not self.settings.market_news_enabled:
            return {"status": "disabled"}
        at = self.clock()
        due, _ = schedule_at(at)
        cached = await self.read()
        if cached.items and (due is None or (cached.updated_at and cached.updated_at >= due)):
            return {"status": "not_due"}
        # One initial warm-up outside market hours; thereafter only hourly session slots.
        if await self.redis.get(COOLDOWN_KEY):
            return {"status": "cooldown"}
        token = str(uuid4())
        if not await self.redis.set(LOCK_KEY, token, nx=True, ex=45):
            return {"status": "busy"}
        try:
            # Recheck after acquiring the distributed lock to avoid duplicate fetches.
            cached = await self.read()
            if cached.items and (due is None or (cached.updated_at and cached.updated_at >= due)):
                return {"status": "not_due"}
            await self.redis.set(COOLDOWN_KEY, "1", ex=300)
            items = await self.fetch(at)
            if not items:
                raise ValueError("No usable headlines")
            snapshot = MarketNewsOut(items=items[:5], updated_at=at, status="ready")
            await self.redis.set(CACHE_KEY, snapshot.model_dump_json())
            return {"status": "updated", "count": len(snapshot.items)}
        except Exception:
            # Preserve the last successful snapshot and never log provider payloads.
            logger.warning("news_refresh_failed")
            return {"status": "failed"}
        finally:
            await cast(
                Awaitable[int],
                self.redis.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    "return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    LOCK_KEY,
                    token,
                ),
            )
