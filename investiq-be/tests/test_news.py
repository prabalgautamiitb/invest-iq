from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from investiq.api.news import router
from investiq.core.config import Settings
from investiq.schemas.news import MarketNewsOut, NewsArticle
from investiq.services.news import (
    CACHE_KEY,
    COOLDOWN_KEY,
    LOCK_KEY,
    MarketNewsService,
    parse_feed,
    schedule_at,
)

MONDAY = datetime(2026, 10, 26, 3, 45, tzinfo=UTC)  # 9:15 IST


def article(number: int = 1) -> NewsArticle:
    return NewsArticle(
        id=str(number),
        title=f"Market headline {number}",
        url=f"https://economictimes.indiatimes.com/markets/story-{number}.cms",
        source="The Economic Times",
        published_at=MONDAY - timedelta(minutes=5),
    )


def memory_redis() -> AsyncMock:
    values = {}
    redis = AsyncMock()

    async def get(key):
        return values.get(key)

    async def set_value(key, value, **kwargs):
        if kwargs.get("nx") and key in values:
            return False
        values[key] = value
        return True

    async def release(script, count, key, token):
        if values.get(key) == token:
            values.pop(key)

    async def delete(key):
        values.pop(key, None)

    redis.get.side_effect = get
    redis.set.side_effect = set_value
    redis.eval.side_effect = release
    redis.delete.side_effect = delete
    return redis


def test_hourly_slots_and_reviewed_holidays():
    assert schedule_at(MONDAY) == (MONDAY, MONDAY + timedelta(hours=1))
    assert schedule_at(MONDAY + timedelta(minutes=59))[0] == MONDAY
    assert schedule_at(MONDAY + timedelta(hours=6, minutes=14))[0] == MONDAY + timedelta(hours=6)
    assert schedule_at(MONDAY + timedelta(hours=6, minutes=15))[0] is None
    assert schedule_at(MONDAY + timedelta(hours=6, minutes=16))[0] is None
    before = MONDAY - timedelta(minutes=1)
    assert schedule_at(before) == (None, MONDAY)
    # Weekend and Dussehra must not fetch on a regular weekday schedule.
    assert schedule_at(datetime(2026, 10, 25, 5, tzinfo=UTC))[0] is None
    assert schedule_at(datetime(2026, 10, 20, 5, tzinfo=UTC))[0] is None
    assert schedule_at(datetime(2026, 10, 23, 12, tzinfo=UTC))[1] == MONDAY


def test_parse_deduplicates_sorts_and_validates_original_links():
    def item(number, title=None, url=None, date=None):
        return f"""<item><title>{title or f"Headline {number}"}</title>
        <link>{url or f"https://economictimes.indiatimes.com/markets/{number}.cms"}</link>
        <pubDate>{date or f"Mon, 26 Oct 2026 08:{number:02d}:00 +0530"}</pubDate></item>"""

    feed = "<rss><channel>" + "".join(item(i) for i in range(7))
    feed += item(6) + item(7, title="Headline 6")
    feed += item(8, url="javascript:alert(1)") + item(9, url="https://evil.example/story")
    feed += item(10, date="invalid") + item(11, date="Tue, 27 Oct 2026 08:00:00 +0530")
    feed += "</channel></rss>"
    result = parse_feed(feed.encode(), MONDAY)
    assert [a.title for a in result] == [f"Headline {i}" for i in [6, 5, 4, 3, 2]]
    assert all(str(a.url).startswith("https://economictimes.indiatimes.com/") for a in result)


def test_rejects_oversized_or_entity_payload():
    with pytest.raises(ValueError):
        parse_feed(b"x" * 1_000_001, MONDAY)
    with pytest.raises(ValueError):
        parse_feed(b'<!DOCTYPE rss [<!ENTITY title "Bad">]><rss/>', MONDAY)


async def test_reads_do_not_fetch_and_endpoint_returns_shared_snapshot():
    redis, fetch = memory_redis(), AsyncMock(return_value=[article()])
    service = MarketNewsService(redis, Settings(), lambda: MONDAY, fetch)
    app = FastAPI()
    app.state.market_news = service
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/api/v1/market/news")
        assert response.status_code == 200
        assert response.json()["items"] == []
        fetch.assert_not_awaited()
        assert await service.refresh() == {"status": "updated", "count": 1}
        result = (await c.get("/api/v1/market/news")).json()
        assert result["items"][0]["title"] == article().title
        assert result["status"] == "ready"
        fetch.assert_awaited_once()


async def test_same_hour_deduplicates_and_next_hour_refreshes():
    redis, fetch = memory_redis(), AsyncMock(return_value=[article(i) for i in range(5)])
    clock = MONDAY
    service = MarketNewsService(redis, Settings(), lambda: clock, fetch)
    await service.refresh()
    # A second process sees the same Redis snapshot, without another publisher request.
    other = MarketNewsService(redis, Settings(), lambda: clock, fetch)
    assert (await other.refresh())["status"] == "not_due"
    clock += timedelta(hours=1)
    # Simulate expiry of the five-minute retry cooldown.
    await redis.delete(COOLDOWN_KEY)
    assert (await other.refresh())["status"] == "updated"
    assert fetch.await_count == 2


async def test_free_demo_refreshes_daily_after_hours_and_labels_the_schedule():
    redis, fetch = memory_redis(), AsyncMock(return_value=[article()])
    clock = MONDAY + timedelta(hours=12)  # after market hours
    settings = Settings(_env_file=None, deployment_mode="free_demo")
    service = MarketNewsService(redis, settings, lambda: clock, fetch)
    assert (await service.refresh())["status"] == "updated"
    assert (await service.refresh())["status"] == "not_due"
    first = await service.read()
    assert first.status == "ready" and first.next_refresh_at is None
    assert first.schedule.startswith("Daily")
    clock += timedelta(days=1)
    await redis.delete(COOLDOWN_KEY)
    assert (await service.refresh())["status"] == "updated"
    assert fetch.await_count == 2


async def test_failure_or_empty_feed_retains_last_good_snapshot():
    redis = memory_redis()
    snapshot = MarketNewsOut(items=[article()], updated_at=MONDAY, status="ready")
    await redis.set(CACHE_KEY, snapshot.model_dump_json())
    for outcome in [RuntimeError("publisher unavailable"), []]:
        fetch = (
            AsyncMock(side_effect=outcome)
            if isinstance(outcome, Exception)
            else AsyncMock(return_value=outcome)
        )
        clock = MONDAY + timedelta(hours=2)
        service = MarketNewsService(redis, Settings(), lambda clock=clock: clock, fetch)
        # Clear only the simulated cooldown between failed attempts.
        await redis.delete(COOLDOWN_KEY)
        assert (await service.refresh())["status"] == "failed"
        result = await service.read()
        assert result.items == snapshot.items
        assert result.updated_at == MONDAY
        assert result.status == "stale"
        assert (await service.refresh())["status"] == "cooldown"


async def test_initial_warmup_then_no_weekend_refresh_and_lock_exclusion():
    redis, fetch = memory_redis(), AsyncMock(return_value=[article()])
    clock = MONDAY - timedelta(days=1)
    service = MarketNewsService(redis, Settings(), lambda: clock, fetch)
    await redis.set(LOCK_KEY, "another-worker")
    assert (await service.refresh())["status"] == "busy"
    await redis.delete(LOCK_KEY)
    assert (await service.refresh())["status"] == "updated"
    assert (await service.refresh())["status"] == "not_due"
    fetch.assert_awaited_once()


async def test_disabled_or_unavailable_redis_does_not_break_dashboard():
    redis, fetch = memory_redis(), AsyncMock()
    disabled = MarketNewsService(redis, Settings(market_news_enabled=False), lambda: MONDAY, fetch)
    assert (await disabled.read()).status == "disabled"
    assert (await disabled.refresh())["status"] == "disabled"
    redis.get.side_effect = ConnectionError("Redis unavailable")
    service = MarketNewsService(redis, Settings(), lambda: MONDAY, fetch)
    assert (await service.read()).status == "unavailable"
    fetch.assert_not_awaited()
