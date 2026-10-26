# Market brief

Home shows one headline beside the Nifty 50 overview, rotating every three seconds.
The carousel pauses on hover, keyboard focus, while the tab is hidden, or using
its pause button. Its five indicators select a particular headline. Portfolio
shows the complete list at the bottom, both on contest selection and in a
contest workspace. Every headline links to its original publisher in a new tab.

## Source and refresh policy

The source is The Economic Times' public **Markets** RSS feed:
`https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms`.
The service selects the five newest unique usable articles, retaining the
publisher title, original HTTPS link, publication time and source attribution.
It does not generate headlines, copy article bodies, or claim an impact ranking.
Duplicate links/titles, invalid links/dates, future timestamps and items more than
seven days old are excluded. A publisher response can contain fewer than five
valid stories; the interface displays the available stories without filler.

Celery Beat checks eligibility every 60 seconds on the existing valuation queue.
The worker fetches once per hourly slot: **9:15, 10:15, 11:15, 12:15, 13:15, 14:15
and 15:15 IST**, using the same reviewed NSE calendar as valuation. Weekends,
holidays, unsupported special sessions and dates beyond the reviewed calendar
do not create hourly slots. The currently bundled calendar covers 2026; extend
that shared calendar before the next year. Scheduled dispatch may lag a slot
by up to one scan interval.

A missing cache is warmed once on the first worker scan, including outside
market hours. After that, saved headlines remain visible between trading
sessions. Redis shares the snapshot across API/worker processes and browsers.
A distributed lock prevents concurrent publisher requests; failures back off
for five minutes and retain the last good snapshot and its original fetch time.

`GET /api/v1/market/news` reads the saved snapshot only; visiting the site and
carousel transitions do not trigger publisher requests. It returns `items`,
`updated_at`, `next_refresh_at`, `status` and `schedule`. `status` is `stale`
after 90 minutes, including outside trading hours; the UI then labels it as
saved headlines and keeps the timestamp visible. Missing or unavailable cache
data returns an empty/unavailable state instead of blocking portfolio work.
Frontend widgets read the shared snapshot once per minute while visible.

## Run locally

Use the existing API, worker and Beat services. No news API key or migration is
needed. After changing the backend source, rebuild the running app services:

```bash
docker compose --profile app build api worker beat
docker compose --profile app up -d --no-deps api worker beat
```

For Python-only development, start the API as usual and run the existing
Celery worker and Beat commands from the project README. To populate the first
snapshot immediately:

```bash
uv run --locked python -c 'import asyncio; from investiq.jobs.valuation import execute_news; print(asyncio.run(execute_news()))'
```

This command respects the same schedule/deduplication rules. Set
`INVESTIQ_MARKET_NEWS_ENABLED=false` for the API and worker to disable news.
The Compose stack forwards this setting. Redis must be running for persistence.

After frontend changes, run `npm run build` or use the Vite dev server.

## Verification

```bash
# Backend: parser, scheduling boundaries/holidays, HTTP endpoint, shared cache,
# concurrent locks, failure retention, unavailable cache, disabled mode.
uv run --locked pytest tests/test_news.py

# Frontend: rotation, pause, selection, shared portfolio links, mobile layout,
# empty/stale/failure states. Uses the existing disposable browser test harness.
cd ../investiq-fe
npx playwright test tests/browser/news.spec.js
```

The browser tests use labelled test headlines and mocked API responses; they
never present those fixtures through the application's real news endpoint.
