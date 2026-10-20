# Phase 3 — market-data foundation

## Goal, prerequisites and boundary

Provide a stable instrument catalogue, sectors/cap categories, explicit exchange sessions, deterministic development quotes, ingestion provenance and price-quality checks. Requires the Phase 3 PostgreSQL migration. Redis/auth infrastructure continues to serve the existing application; this phase adds no worker, LLM key or external price-feed account.

Only synthetic development/test prices are supported. The API labels every instrument/quote as `data_kind: fixture` and every quote as ineligible for live use. Production and `INVESTIQ_MARKET_DATA_MODE=disabled` reject market reads and fixture initialization with `market_data_disabled` (503). Genuine users, portfolios, balances, coin/XP events and activity are never seeded.

The provider abstraction is a Python `Protocol`, analogous to a Java interface: adapters supply a validated `ProviderBatch`; the ingestion service owns persistence, completeness and timestamp rules. Pydantic batches are validated DTOs, and SQLAlchemy services own transactions rather than the API controller.

## Source research and provider decision

Reviewed the official sources on 18 October 2026:

- [NSE data sharing/usage policy](https://www.nseindia.com/static/market-data/nse-data-policy): data display and redistribution depend on the relevant agreement; delayed/EOD data are within the policy's scope.
- [NSE paid EOD/historical products](https://www.nseindia.com/static/market-data/eod-historical-data-subscription): an official commercial route to research for coverage and entitlements.
- [SEBI circular of 8 May 2026](https://www.sebi.gov.in/sebi_data/attachdocs/may-2026/1778242522289.pdf): changes education-related price-data sharing/usage rules, including a 30-day lag and conditions concerning monetary incentives, effective 1 July 2026. The specific product use and agreements need review before enabling a real feed; an EOD label alone does not establish suitability.
- [NSE market timings/holidays](https://www.nseindia.com/resources/exchange-communication-holidays): the reference for normal equity-session hours and the reviewed 2026 holiday snapshot.

Decision: **no production provider is selected or integrated in this phase**. No exchange scraping or unverified free-provider fallback exists. A future adapter needs approved Indian-equity coverage, redistribution/display rights, permitted data lag, benchmark rights, corporate-action handling, historical coverage, freshness guarantees and the appropriate product-use review. Actual feed latency must then replace the fixture's publication policy.

These conclusions supersede Phase 0's tentative suggestion that current delayed/EOD data might be an appropriate production default. The development fixture contains fabricated numerical examples, not real exchange observations or historical records.

## Files

| File | Purpose |
|---|---|
| `models/market.py` | Six persistence models and database constraints |
| `schemas/market.py` | Catalogue, calendar, provider-batch and quote DTOs |
| `adapters/market.py` | Typed provider interface and deterministic fixture adapter |
| `data/market_fixture_v1.json` | Stable instrument/sector IDs and decimal-string synthetic prices |
| `data/nse_calendar_2026.json` | Reviewed calendar source/version and explicit special-session exclusion |
| `services/exchange_calendar.py` | UTC session construction and expected-EOD selection |
| `services/market_ingestion.py` | Development seed, complete-batch validation, transactions, retries and conflict detection |
| `services/market.py` | Search/filter/sort, keyset pagination and quote quality |
| `api/market.py` | Public, read-only market endpoints |
| `market_cli.py` | Explicit development fixture initialization |
| `migrations/versions/0003_market_*.py` | Schema-only migration; never seeds fixture prices in production |
| `tests/test_market.py`, `tests/conftest.py` | Real PostgreSQL failure/concurrency tests and disposable databases |
| `scripts/e2e_server.py` | Browser-test market seed and fixed market clock |
| Frontend `src/api/market.js`, `src/app.js` | API-backed catalogue/quotes, search/filter/pagination, provenance and error states |
| Frontend `tests/browser/market.spec.js` | Browser catalogue, failure/fallback and stale-quote coverage |

Paths in the backend file map are under `src/investiq/` unless otherwise stated.

## Data model

Application IDs are UUIDs; temporal observations use timezone-aware UTC `TIMESTAMPTZ`. Money/index levels use Python Decimal and PostgreSQL `NUMERIC(20,4)`. Prices remain decimal strings in JSON. Incoming floats, NaN/infinity, zero/negative values and values beyond the defined scale are rejected. PostgreSQL also rejects NaN and nonpositive stored closes.

| Entity / ownership | Columns | Constraints, indexes and deletion |
|---|---|---|
| `sectors`: application-owned reference catalogue | `id UUID`; `slug VARCHAR(40)`; `name VARCHAR(80)` | PK id; unique slug/name. Instrument sector FK uses RESTRICT. |
| `instruments`: application-owned stable identities | `id UUID`; `symbol VARCHAR(30)`; `name VARCHAR(150)`; `exchange VARCHAR(10)`; `kind VARCHAR(12)`; `currency VARCHAR(6)`; nullable `sector_id UUID`, `market_cap VARCHAR(8)`; `active BOOLEAN` default true; `data_kind VARCHAR(10)`; `created_at TIMESTAMPTZ` default now | PK id; unique exchange/symbol; indexes symbol, sector_id, market_cap. Exchange is NSE; kind equity/benchmark; cap large/mid/small. Equities require sector/cap and INR; benchmarks have no sector/cap and use POINTS. Sector FK RESTRICT; snapshots/exclusions prevent deleting referenced instruments. |
| `exchange_sessions`: reviewed calendar | `id UUID`; `exchange VARCHAR(10)`; `session_date DATE`; `status VARCHAR(12)`; nullable `opens_at`, `closes_at`, `available_at TIMESTAMPTZ`; nullable `reason VARCHAR(150)`; `calendar_version VARCHAR(60)`; `source VARCHAR(200)` | PK id; unique exchange/date. Status open/closed/unsupported. Open sessions require all times with open < close <= available; non-open sessions require null times. No user ownership or automatic cascading deletion. |
| `market_exclusions`: explicit valuation restrictions | `id UUID`; `instrument_id UUID`; `starts_on DATE`; nullable `ends_on DATE`; `reason VARCHAR(150)`; `source VARCHAR(80)` | PK id; indexed instrument FK RESTRICT; end must be absent or >= start. Open-ended exclusions stay active until an operator supplies an end. No public write endpoint. |
| `market_ingestion_runs`: canonical batch outcomes | `id UUID`; `provider VARCHAR(60)`; `dataset_version VARCHAR(40)`; `session_date DATE`; `data_kind VARCHAR(10)`; `status VARCHAR(12)`; `attempts INTEGER`; `point_count INTEGER`; nullable `content_hash VARCHAR(64)`, `error_code VARCHAR(50)`; `started_at`, `completed_at TIMESTAMPTZ` | PK id; unique provider/version/session. Status succeeded/failed; attempts > 0; point_count >= 0. Success requires hash and no error; failure requires a sanitized error code. Referenced runs cannot be deleted. |
| `price_snapshots`: persisted EOD evidence | `id UUID`; `run_id UUID`; `instrument_id UUID`; `session_date DATE`; `close NUMERIC(20,4)`; `observed_at`, `source_published_at`, `ingested_at TIMESTAMPTZ` (ingested defaults to now) | PK id; unique run/instrument; indexes run, instrument, session_date. Run/instrument FKs RESTRICT. Close positive and non-NaN; publication >= observation. No update/delete API; successful batches reject changed content. |

Reference instruments/sectors use UUID5 generated once from immutable fixture keys, not from mutable symbols. Session IDs use exchange/date keys; run/snapshot IDs use UUID4. No fictional ISIN is assigned and this fixture catalogue is not a verified exchange security master. A later symbol change must preserve the instrument UUID through a reviewed mapping.

Lifecycle policies: instrument active → inactive or reactivated by controlled reference-data maintenance; exclusions active by inclusive date range; calendar open/closed/unsupported is a reviewed record, not inferred at query time; failed ingestion → failed or succeeded on retry; succeeded ingestion is terminal for that provider/version/session. A new dataset/provider version is needed for an intentional price revision.

## Fixture and calendar policy

The explicit seed contains 11 sectors, 16 familiar reference equities, one synthetic Nifty 50 benchmark, and a fictional `FIXSPLIT` exclusion example. The benchmark values are fabricated index points. Sector and cap labels are illustrative classifications. `FIXSPLIT` demonstrates unsupported adjusted-price handling without asserting a real company's corporate event.

Exactly three synthetic batches exist: **14, 15 and 16 October 2026**, each with 18 points. There is no resampling to today's date. All points within a batch share one observation timestamp: normal close at 15:30 Asia/Kolkata (10:00 UTC). The fixture publication policy is 18:00 IST (12:30 UTC), a development policy, not a promise about an exchange/provider publication time.

The calendar explicitly covers every day of 2026, with normal sessions 09:15–15:30 IST, weekends and the sourced holiday list. The special Muhurat date, 8 November, is marked **unsupported**, because special trading hours need their own reviewed record. Closed days have no open/close timestamps. Unexpected closures or revised schedules require an explicit calendar update with a new review/version; the application never silently assumes that an uncovered date is a trading day.

Expected EOD is the most recent supported session whose `available_at` is <= the server quote cutoff. Before Friday's 18:00 publication boundary, Thursday remains the expected EOD; after publication and during the weekend, Friday is expected. An unsupported special session between the selected close and cutoff blocks the request. Outside reviewed coverage, the API returns `calendar_unavailable` rather than extending the calendar by guessing weekdays. The first covered day before its publication can also lack a covered previous session.

Splits/dividends/mergers/symbol changes are not adjusted automatically. The only action-related functionality is an explicit exclusion mechanism. A real provider cannot be enabled until affected instruments, stable identity mappings and adjustment policies are supported or excluded. Future contest valuation must reject intervals that cross unsupported sessions or corporate actions.

## Ingestion, transactions and retry rules

`FixtureMarketProvider.fetch_eod(session_date)` returns a typed batch. The service applies a 10-second fetch timeout, revalidates the returned DTO, then checks provider/version/session identity, a supported session, exact distinct instrument coverage, positive exact decimal prices, close-time alignment, publication policy and no future publication.

The service transaction inserts-or-locks the unique provider/version/session run. It publishes all snapshots and the success state atomically. An identical replay returns the existing run UUID without changing prices or counters. Canonical hashing normalizes decimal scale, UTC timestamps and instrument order, so order-only changes are equivalent. Concurrent retries arbitrate through PostgreSQL uniqueness and row locks. A different successful-batch payload returns `immutable_price_conflict` (409), preserving the prior data.

Failures leave no partial price batch and persist only a sanitized error code in a separate transaction. A later valid retry of a failed run increments attempts and can publish atomically. `started_at`/`completed_at` measure the latest recorded attempt. Outcomes are aggregated per canonical batch, not a full log of each retry. Rejected changes to an already-successful run do not rewrite that run. There is no automatic retry loop or Celery scheduler yet; the explicit CLI is safe to retry.

The seed inserts missing reference/calendar rows only; it never overwrites operator changes or rewrites successful prices. Deleting/corrupting persisted snapshots is not repaired implicitly by replaying a succeeded batch: quote reads flag missing/stale evidence and an operator must investigate. Normal application routes do not expose price writes/deletes.

## HTTP contracts

These public, read-only endpoints contain no private account data. Prefix: `/api/v1`.

| Method / endpoint | Contract |
|---|---|
| GET `/sectors` | Bounded reference lookup: `{items: [{id, slug, name}], next_cursor: null}`. |
| GET `/instruments` | `query`, UUID `sector`, `market_cap=large|mid|small`, `kind=equity|benchmark` (default equity), `eligible_only=true`, `sort=symbol|-symbol|name|-name`, `limit` 1–100 (default 20), optional `cursor`. Returns `{items, next_cursor}`. |
| GET `/quotes` | Required comma-separated UUID `instrument_ids` (1–100, distinct); optional timezone-aware `as_of`; optional `require_complete=true`. Returns the expected common session plus per-instrument quote/quality evidence. |
| GET `/market/sessions` | Required `start_date`, `end_date`; maximum 366 ordered days, all covered. Returns calendar records in `{items, next_cursor: null}`. |

Search uses bound literal substring expressions; `%`/`_` are escaped rather than treated as patterns. Sorting uses an explicit allowlist and C collation, with UUID tie-breakers for stable results across database locales. Pagination is keyset-based, not offset-based. Cursors bind to normalized filters, sort order and the current Kolkata date. Changing filters/day requires starting a new page sequence. Cursors are query boundaries for public data, not authorization credentials or signed access tokens. Catalogue changes during paging are not a repeatable-read snapshot.

Default discovery excludes inactive instruments and instruments excluded on the current Kolkata date. `eligible_only=false` reveals the catalogue metadata for inspection; it never grants valuation permission.

Example:

```http
GET /api/v1/instruments?query=info&market_cap=large&limit=5
```

```json
{"items":[{"id":"d7c1a6ff-747d-518f-a4f9-6e0222b05001","symbol":"INFY","name":"Infosys","exchange":"NSE","kind":"equity","currency":"INR","sector":{"id":"bc2627c2-6d48-55ee-af94-a4e79527720d","slug":"it","name":"IT"},"market_cap":"large","active":true,"excluded":false,"data_kind":"fixture"}],"next_cursor":null}
```

Use the returned UUID when requesting prices. The example uses the deterministic fixture ID; API catalogue values remain authoritative.

```http
GET /api/v1/quotes?instrument_ids=<returned-uuid>&as_of=2026-10-18T12:00:00Z&require_complete=true
```

Response shape (IDs and ingestion timestamps abbreviated for readability):

```json
{
  "as_of":"2026-10-18T12:00:00Z",
  "expected_session_date":"2026-10-16",
  "calendar_version":"nse-equities-2026-reviewed-2026-10-18",
  "all_current":true,"data_kind":"fixture",
  "items":[{
    "instrument_id":"<returned-uuid>","symbol":"INFY","currency":"INR",
    "close":"1874.3500","session_date":"2026-10-16",
    "observed_at":"2026-10-16T10:00:00Z",
    "source_published_at":"2026-10-16T12:30:00Z",
    "ingested_at":"<actual UTC ingestion time>",
    "source":"investiq-synthetic","dataset_version":"fixture-v1","data_kind":"fixture",
    "freshness":"current_eod","blocked_reason":null,
    "eligible_for_simulation":true,"eligible_for_live_use":false
  }]
}
```

`current_eod` describes completeness against the selected synthetic session, not real market freshness. Missing prices return null values and `freshness: missing`; a prior available close is returned with `freshness: stale` and cannot be treated as current. Exclusions/inactivity set `blocked_reason`. `all_current` is true only when every requested point is current and simulation-eligible. This flag is evidence availability, not permission to trade a benchmark or bypass future contest rules.

`require_complete=true` returns 409 if any requested point is missing, stale or blocked, preventing mixed-session valuation. Unknown IDs return 404; malformed/duplicate IDs, unsupported sort/filter/cursors, naive timestamps and future cutoffs return 422. Empty/uninitialized catalogue and uncovered/special calendars return 503. Errors retain the common error/request-ID envelope.

`as_of` is a read-only historical source-availability cutoff; snapshots may have been ingested later. It is not a reconstruction of what this backend knew at that historical instant. No snapshot with a later source-publication time is returned. Future accounting/submission/valuation services must choose their authoritative server cutoff themselves; clients cannot submit a price or dictate a financial valuation time.

## Frontend integration

The portfolio catalogue and quantity-price previews use backend data. Search, sector/cap filters and Load more use API queries. The catalogue shows decimal-preserving formatted prices, source/version, observation/ingestion timestamps in IST, expected session and quality. Failed market requests show retry controls, clear price availability and never substitute old browser fixture prices. Missing/stale prices disable Add and quantity inputs; incomplete selections cannot proceed to local review. Client previews require refresh after 60 seconds; server quality remains authoritative.

Legacy preview allocations remain browser-local symbol-keyed weights; instrument UUIDs are retained alongside catalogue rows. Unknown prior symbols are shown as unavailable with a Remove control. They are not migrated to server portfolios. Phase 5 will replace preview allocation arithmetic/storage with contest-scoped drafts and Decimal validation. Current JavaScript weight/quantity calculations are illustrative previews, never accounting or accepted submissions. The backend does not accept balances, prices, fees, returns, holdings or portfolio mutations in this phase.

## Setup and verification

Host Python development, from `investiq-be`:

```bash
uv sync --locked
docker compose up -d --wait postgres redis mailpit
uv run --locked alembic upgrade head
uv run --locked python -m investiq.market_cli
uv run --locked uvicorn investiq.main:create_app --factory --reload --host 127.0.0.1 --port 8080 --no-access-log
```

Or the full Docker development stack (migrate → idempotent market seed → API):

```bash
docker compose --profile app up -d --build --wait
```

Only run one API on 8080. In a second terminal, from `investiq-fe`:

```bash
npm ci
npm run dev
```

Open http://localhost:5173/#/portfolio. The seed CLI is development/test-only. To disable market data, set `INVESTIQ_MARKET_DATA_MODE=disabled` on the API; production disables it regardless of this value. No fixture-data migration is required in production because the schema migration contains no market seed.

Example reads:

```bash
curl 'http://localhost:8080/api/v1/sectors'
curl 'http://localhost:8080/api/v1/instruments?query=info&limit=5'
curl 'http://localhost:8080/api/v1/market/sessions?start_date=2026-10-16&end_date=2026-10-20'
# Copy a catalogue UUID into this read-only request:
curl 'http://localhost:8080/api/v1/quotes?instrument_ids=<uuid>'
```

Backend checks:

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked alembic check
uv run --locked pytest
uv lock --check
```

Browser checks from `investiq-fe`:

```bash
npx playwright install chromium
npm run check
npm run build
npm run test:e2e
```

Integration tests use real, disposable PostgreSQL databases migrated from zero, including NUMERIC/check-constraint behavior, transactional ingestion, concurrent retry, partial/missing/stale data and production refusal. Test database creation requires CREATEDB on the configured development role. Browser tests seed their own disposable market database, freeze only the market clock to 18 October 2026, keep authentication clocks real, and remove the test database on shutdown. Normal runtime never advances fixture observation times.

No new dependencies were needed: Decimal, zoneinfo, Protocol, resource loading and hashing use Python's standard library; existing pinned SQLAlchemy/Pydantic/FastAPI packages provide the rest. Both Python lock artifacts remain current.

## Next phase

Phase 4 adds contests, versioned/frozen rules, visibility/invitations, ownership, membership and lifecycle transitions, with contest discovery/My Contests integration. Portfolio submission and accounting remain Phase 5; valuation/rankings and scheduled jobs remain Phase 6. A production price adapter is not implied by finishing Phase 3.
