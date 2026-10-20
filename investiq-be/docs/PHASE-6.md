# Phase 6 — Simulated valuation, rankings and contest completion

## Goal and prerequisites

Use the latest accepted immutable portfolio from Phase 5 to calculate dated virtual values, benchmark comparisons and rankings; finalize results after all contest sessions are valued. **Simulation only: no real trades, payments, payouts, funds transfers or financial settlement.** The legacy API state `settling` means finalizing simulated results; the UI calls it “finalizing results.” Coins, XP and rewards remain later phases.

Requires migrated PostgreSQL, Redis, the reviewed NSE calendar, fixture market data and accepted submissions. Celery and Beat now schedule useful work. New dependency pins: Celery 5.6.3, Kombu 5.6.2 and Redis Python client 6.4.0. The stable Kombu Redis transport requires a client below 6.5; using the previous client selected a prerelease transport, so both transport and client are pinned to a compatible stable set. Redis **server** remains version 8. All existing identity/portfolio tests run against the compatible client. See DEPENDENCIES.md for official sources; `uv.lock` and hash-bearing `requirements.lock` are updated.

New files: `models/valuation.py`, `schemas/valuation.py`, `analytics/valuation.py`, `services/valuation.py`, `api/valuation.py`, `jobs/valuation.py`, `valuation_cli.py`, migration `0006_valuations`, `data/valuation_scenario_v1.json` and `tests/test_valuation.py`. Modified application registration/settings/readiness, submission composite key, Compose worker/beat services, requirements locks and `.env.example`. Frontend adds `features/performance.js`, performance APIs, dashboard/leaderboard/performance/history routing and genuine My Contests metrics. `tests/browser/performance.spec.js` exercises historical fixtures through the disposable test harness.

The service owns transactions, like Spring `@Transactional`; Pydantic models are DTOs. The pure analytics module does not call providers, the database or an LLM. Celery is the asynchronous execution boundary; PostgreSQL remains the source of work and results.

## Valuation and ranking policy

### Selection, timing and evidence

A contest can be valued only after it starts. Select each member's **highest sealed accepted submission version**; later unsubmitted drafts do not replace it. Verify its frozen rule ID, capital, benchmark and entry-lock timestamp. Accepted versions cannot change after entry closes, before start.

Value every participant at the **same NSE session close**, once that session's reviewed publication time has passed. Calendar dates must cover the whole contest, match frozen start/end boundaries and contain no unsupported special session. Weekends/holidays are skipped using the stored calendar, not hardcoded weekday assumptions. The baseline for each portfolio and benchmark is its immutable submission price snapshot from Phase 5. Benchmark-relative returns therefore use each portfolio's sampled entry EOD and the shared valuation EOD.

All required holdings and benchmark points must exist for the exact target day, match its closing observation, have been published by the worker's current server time, and come from one succeeded fixture batch. Active/classified instruments, currencies and corporate-action exclusions are checked again; unsupported splits/dividends are blocked rather than silently adjusted. No fallback prices, prior-day substitution or fabricated current quotes are permitted.

One missing/blocked point blocks **the entire day's ranking**. No subset receives a misleading current rank. Process required sessions in chronological order; do not skip a missing day just because a later day's prices exist. This preserves the daily-close drawdown path. Existing successful snapshots remain readable but are clearly marked out of date when a newer required session is pending. An empty contest can complete with zero ranked entries and no winner; it does not fabricate participants or require unused prices.

Copied valuation prices include source snapshot IDs, symbol/sector classification, exact prices, observation/publication/ingestion times and provider/dataset version. The run's SHA256 evidence hash covers copied prices, ordered results, submission IDs and calculation version. Corrections to mutable market source rows cannot rewrite archived successful snapshots. Finalized result reads remain stable even if later market/calendar availability changes. Display names are resolved according to **current** privacy settings, not frozen into financial evidence.

### Deterministic calculations

Decimal precision is 50; amounts use four decimal places and reported percentage metrics eight places with half-up rounding. Values beyond supported database precision block with `valuation_out_of_range` instead of overflowing persistence. No float is used for accounting.

```text
holding_value_i = locked_integer_shares_i × closing_price_i
holdings_value = sum(holding_value_i)
portfolio_value = holdings_value + immutable_residual_cash
net_pnl = portfolio_value − original_virtual_capital
return_pct = net_pnl / original_virtual_capital × 100
benchmark_return_pct = (benchmark_close / immutable_entry_benchmark − 1) × 100
excess_return_pp = return_pct − benchmark_return_pct
```

The Phase 5 simulated fee is **already deducted** in residual cash. It is reported as evidence, never charged again. Contributions show each holding's current value minus its entry notional; their sum minus the original fee equals net P&L.

Metrics also include holding/sector counts, largest current position as a percentage of total value, and equity concentration HHI: `sum((holding_value / holdings_value)^2)`. HHI is between 1/N and 1 for N positive holdings; lower means equity value is more evenly spread. Cash is excluded from HHI but included in total portfolio value and the largest-position denominator. These are descriptive metrics, not a suitability assessment.

For daily-close drawdown, seed the peak at starting capital and include the initial simulated fee loss. Then carry forward `peak = max(previous_peak, capital, current_value)` and `max_drawdown_pct = max(previous_drawdown, (peak − value)/peak × 100, initial_fee/capital × 100)`. Every required session must be present; this does **not** estimate intraday drawdown.

Example unit scenario: capital 1000, cash 799.8, fee 0.2 and two holdings worth 120 and 80 produce total value 999.8, net return −0.02%, and initial drawdown 0.02%. If the benchmark grew from 100 to 105, benchmark return is 5% and excess return is −5.02 **percentage points**. Equity HHI is 0.52. This is illustrative simulation arithmetic, not actual market performance.

Ranks are ordinal 1…N, ordered by exact net P&L descending (capital is identical within a frozen contest), then lower eight-place maximum drawdown, earlier timestamp of the selected accepted submission, then membership UUID ascending. Do not rank different contests together. Rounded display returns are not the primary sort key; ties receive a deterministic distinct order.

## Schema and constraints

Migration `0006_valuations` adds four tables and a unique `(id,membership_id)` submission key. IDs are UUIDs, timestamps are timezone-aware UTC, session dates are exchange-local dates. All FKs use `RESTRICT`; snapshots are retained, not cascaded away with users/contests/source data.

| Table | Ownership, columns and constraints |
| --- | --- |
| `valuation_runs` | Contest-owned UUID PK and indexed contest FK; unique contest/session date. Session DATE, observed/available/evaluated timestamps; status varchar(12) pending/blocked/succeeded; positive integer attempts and nonnegative participant count; optional evidence hash varchar(64)/error code varchar(64); calculation version varchar(40). Succeeded requires a hash and no error. Blocked runs retain a stable sanitized error code and retry counter. |
| `valuation_prices` | Run-owned copied common price set. Composite PK run/instrument with restrictive run/instrument/source price/nullable sector FKs; symbol varchar(30), positive non-NaN price NUMERIC(20,4), observed/published/ingested timestamps, source varchar(60), dataset version varchar(40). |
| `valuation_records` | UUID PK; indexed run and membership FKs, submission FK and composite submission/membership FK. Unique run/member and run/rank; rank positive. NUMERIC(24,4) capital, holdings value, cash, fee, total, P&L and carried peak. Arithmetic/nonnegative/NaN checks require total = holdings value + cash, P&L = total − capital and peak ≥ total. NUMERIC(20,8) return/benchmark/excess/drawdown/largest-position/HHI metrics, positive holding count/nonnegative sector count, JSONB copied holding contributions. |
| `contest_finalizations` | Contest UUID PK/FK, unique final run FK and completion timestamp. One durable finalization per contest; its run must belong to the same contest and have succeeded. |

Run state: `pending → succeeded` or `pending → blocked → pending` on retry. Once succeeded, its header is immutable. Records and copied prices may be inserted only while the parent is pending; their update/delete is always rejected, and appending to a succeeded/blocked run is rejected. A deferred constraint trigger checks that a succeeded run has exactly its participant count and contiguous ranks; partial rankings cannot commit in a non-succeeded run. Finalizations cannot be updated/deleted. Failed construction rolls back all children while persisting the blocked header/error/attempt.

Transactions lock the contest before examining work, then source instruments/prices for a common consistent publication. A day’s prices, all participant results, evidence hash and succeeded state commit together. PostgreSQL uniqueness and contest locking make concurrent workers/retries safe. On the final required published session, the same transaction inserts finalization, sets contest status completed, and writes one `contest_results_finalized` audit event with no user impersonation. There are no reward/coin/payment side effects.

## Worker scheduling and retry behavior

Beat schedules `investiq.valuation.scan` every 60 seconds by default. A scan selects up to 100 started, published, noncancelled/noncompleted contests, ordered by oldest attempt. Each contest processes up to 10 due sessions per scan; each day has its own transaction, so interrupted backfills preserve already successful snapshots. Repeated scans continue remaining work.

The schedule is a reconciliation loop over durable database conditions: accepted submissions, calendar sessions and immutable run rows define the work. Broker delivery is not the only record of a requested financial action. Lost ticks, broker restarts or worker interruptions are recovered by the next scan; successful rows are never recalculated or duplicated. Consequently no redundant outbox table is needed for this periodic read/compute workflow. A future reward issuance workflow will need its own ledger/outbox guarantees.

Celery uses JSON messages, a separate Redis DB 1 and `investiq.valuation` queue, late acknowledgements and prefetch 1. No credentials or user portfolio payloads are task arguments, and no Celery result backend stores sensitive results. Runtime failures raise sanitized messages and receive at most three jittered backoff retries; scheduled scans continue afterward. Missing data is a normal persisted blocked result, retried on later scans when data arrives. Soft/hard task limits are 90/120 seconds, broker visibility timeout 180 seconds. Fresh async database/Redis pools per task are closed before its event loop exits; connections are not reused across Celery forks or asyncio loops.

Run only **one Beat scheduler**. Duplicate messages are safe, but unnecessary duplicate schedulers waste work. Worker/Beat observability and production scale/load tuning remain Phase 12; local scan limits are explicit, not a claim of unlimited throughput. Calendar failures discovered before a valid target session can be established are reported by read APIs and the scan summary; no guessed session row is fabricated.

## API contracts and privacy

All paths are under `/api/v1`. APIs are read-only; actors cannot submit ranks, returns, prices, a valuation time or completion status. A trusted local operator CLI and the scheduler invoke the reusable service. Results APIs remain usable when a worker/broker is unavailable, with pending/out-of-date metadata rather than invented results.

| Method/path | Contract |
| --- | --- |
| GET `/contests/{id}/leaderboard` | Published public visibility for guests; existing private/draft ownership/invitation/membership rules for authenticated viewers. `{contest_id,contest_name,contest_status,run_id,session_date,valued_at,expected_session_date,is_current,is_final,job_status,error_code,participant_count,member_count,items,next_cursor,calculation_version,data_kind}`. Page limit 1–100/default 20, cursor bound to viewer and run; optional `run_id` selects a successful snapshot belonging to that contest. |
| GET `/contests/{id}/performance` | Verified current member only. Own latest metrics, `has_submission`, current/final/error metadata and descending daily `series` with member-bound date cursor. Metrics contain accepted submission ID, capital/value/cash/fee/P&L, rank, returns, concentration/diversification counts, carried peak/drawdown and own holding contributions. No other-user performance route. |
| GET `/me/dashboard` | Authenticated own membership/submission/active/completed/cancelled/win/valued counts; latest-snapshot total value/P&L and `all_valued_current`; up to 20 recent contest summaries. Aggregates exclude cancelled/unvalued portfolios and explicitly combine each contest’s own latest snapshot, **not** a common-time global return. Unvalued portfolios are counted separately; never implied to have zero performance. |
| GET `/me/contest-history` | Own completed/cancelled membership summaries with value/rank if present; UUID-keyset pagination and user-bound cursor, default 20/max 100. |

Leaderboard rows expose entry UUID, rank, value, returns and drawdown. Names appear only if the user's current public-profile preference permits it; otherwise the label is `Learner <opaque entry prefix>`. Emails, user UUIDs, holdings and cash are never public leaderboard fields. `is_you` is derived from the authenticated session, not supplied by the client. Private resources remain 404 to unauthorized viewers. Profile privacy changes apply on subsequent reads without rewriting immutable metrics.

An empty not-yet-valued board returns `items:[]`, `run_id:null`, `is_current:false`, `is_final:false`, `job_status:"waiting"`; a completed empty contest returns a successful final run with participant count 0. If a later day is missing, the prior successful board remains visible with `is_current:false`, `job_status:"blocked"`, `expected_session_date` pointing to the needed day and a stable error such as `market_data_incomplete`. A final board uses its fixed final run and never becomes stale merely because the market continues after the contest.

Responses use decimal strings. Relevant errors retain the standard envelope: 401 sign-in/session, 403 verification, 404 contest/performance/valuation access, 422 invalid IDs/cursors/limits, and 503 fixture functionality disabled in production. Data-blocked jobs are reported as metadata rather than misrepresenting stale ranks as current. Only successful snapshots count toward final rankings/wins.

Example requests with the Phase 2 authenticated cookie jar:

```bash
curl -sS "http://localhost:8080/api/v1/contests/$INVESTIQ_CONTEST_ID/leaderboard?limit=20"
curl -sS -b /tmp/investiq-cookies.txt "http://localhost:8080/api/v1/contests/$INVESTIQ_CONTEST_ID/performance?limit=20"
curl -sS -b /tmp/investiq-cookies.txt http://localhost:8080/api/v1/me/dashboard
curl -sS -b /tmp/investiq-cookies.txt 'http://localhost:8080/api/v1/me/contest-history?limit=20'
```

For a default new account the dashboard counts/totals are zero with no contest rows; no sample achievements, returns or ranks are copied into account history. A successful two-session scenario returns daily snapshots for October 15 and 16, `is_final:true`, contest status completed and one immutable finalization. Actual monetary values come from submitted positions and the checked-in prices, not hardcoded API responses.

## Start and operate locally

Existing complete container setup:

```bash
cd investiq-be
docker compose --profile app up -d --build --wait
```

This starts PostgreSQL, Redis, local Mailpit, schema migration, guarded market fixture seed, API, Celery worker and one Beat scheduler. The worker has a targeted Celery ping health check; Beat writes its local schedule file under `/tmp`. PostgreSQL retains authoritative progress even if the local schedule file disappears.

Host development alternative, using separate terminals and one API on 8080:

```bash
cd investiq-be
# Use the existing .env; fresh setup: copy .env.example to .env first.
uv sync --locked
docker compose up -d --wait postgres redis mailpit
uv run --locked alembic upgrade head
uv run --locked python -m investiq.market_cli
uv run --locked uvicorn investiq.main:create_app --factory --host 127.0.0.1 --port 8080 --reload --no-access-log
```

```bash
cd investiq-be
uv run --locked celery -q -A investiq.jobs.valuation:app worker --loglevel=WARNING --concurrency=2
```

```bash
cd investiq-be
uv run --locked celery -q -A investiq.jobs.valuation:app beat --loglevel=WARNING --schedule=/tmp/investiq-celerybeat
```

Do not run host Beat as well as container Beat. Environment settings: `INVESTIQ_CELERY_BROKER_URL` defaults to local Redis DB 1, `INVESTIQ_VALUATION_QUEUE` defaults to `investiq.valuation`, and `INVESTIQ_VALUATION_SCAN_SECONDS` defaults to 60. Broker URLs remain server-side SecretStr settings; do not put them in frontend variables or task arguments.

Manual trusted operator execution uses the same service, without needing Celery delivery:

```bash
cd investiq-be
uv run --locked python -m investiq.valuation_cli --contest-id "$INVESTIQ_CONTEST_ID"
# Scan due contests instead:
uv run --locked python -m investiq.valuation_cli
# Container-only equivalent:
docker compose exec api python -m investiq.valuation_cli --contest-id "$INVESTIQ_CONTEST_ID"
```

Expected output is a small JSON summary: waiting if no published session is due, blocked with a stable data error, more_due for a bounded backfill, or completed with the final run UUID. Reruns are safe and do not issue rewards or payments.

Frontend:

```bash
cd investiq-fe
npm ci
npm run dev
```

Open http://localhost:5173, sign in/verify, join and submit a portfolio. The signed-in dashboard uses actual counts/results. My Contests links to Performance and Leaderboard and shows recorded values/ranks with snapshot dates. `/leaderboard` chooses a contest instead of comparing unrelated global fixtures; `/leaderboard/{id}` shows its published ranks; `/performance/{id}` shows only the current member’s metrics/contributions/daily series; `/contest-history` lists completed/cancelled contests. All valuation times display in Asia/Kolkata. Missing APIs/data show waiting/error/retry states with no fixture-rank fallback. Account/route generation checks discard obsolete private responses and no result payloads go into localStorage.

## Development scenario, verification and limitations

Prices remain the explicit synthetic October 14–16, 2026 dataset. **New contests outside these dates will wait or block when the required EOD prices are absent.** This is intentional; no scheduler invents prices to force a result. A production feed and corporate-action adjustments remain disabled. The normal API has no time-travel endpoint.

`data/valuation_scenario_v1.json` records a runnable historical test timeline: submit after October 14 publication, start October 15, value that close, end October 16, then finalize after its publication. The integration/browser fixtures create real test memberships and accepted submissions in disposable databases; nothing is automatically seeded as genuine account activity. `scripts/e2e_server.py` provides loopback/header-gated clock/value controls **only in the disposable browser harness**, is not imported by the normal API, and is not included in the Docker image. These controls are test infrastructure, not product APIs.

```bash
cd investiq-be
uv run --locked alembic check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
cd ../investiq-fe
npm run check
npm run build
npm run test:e2e
```

Tests use real PostgreSQL/Redis. Coverage includes exact accounting/fee reuse, benchmark/excess/drawdown/HHI, latest submission selection, common-time rankings, deterministic ties, empty contests, missing data with no partial results, retry/backfill, stale metadata, private access/current name privacy, immutable headers/prices/records/finalization, incomplete snapshot rejection, concurrent completion and exactly one completion audit event. A real Celery subprocess consumes an isolated Redis queue and finalizes the historical fixture contest; it does not share test work with the normal queue. Browser tests cover genuine dashboard/My Contests metrics, private performance, rankings, final history and API failure states, alongside all previous phase flows.

Next is Phase 7: courses, lessons, quiz attempts, progress, XP, achievements and streaks. Phase 6 has no real settlement or fulfillment and awards no coins/XP.

Phase 6 verification: **85 backend tests and 12 Chromium browser tests passed**, including a real Celery subprocess consuming an isolated Redis queue, concurrent completion, immutable snapshots, deterministic ties, missing-price retry/backfill and all previous identity/portfolio flows. Ruff lint/format, strict mypy, uv lock checks, hash-locked container build, Alembic comparison/offline SQL, a disposable PostgreSQL downgrade/upgrade round trip, frontend syntax/build and wheel asset checks passed. API and worker are healthy, Beat is running, and readiness reports revision `0006_valuations` with PostgreSQL/Redis OK. Normal API test-clock routes return 404; temporary databases were removed.
