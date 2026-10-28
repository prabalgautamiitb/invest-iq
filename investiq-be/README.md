# InvestIQ backend

Phases 0–10 are implemented: foundation, identity/onboarding, synthetic market data, contests, portfolio submissions and simulated performance. All backend source, infrastructure, migrations, tests, and documentation live here. Registration, login, verification/recovery, profiles, onboarding and settings now use the API. The portfolio catalogue/search/quotes also use the API; prices are explicitly synthetic. Contest discovery, creation, invitations, memberships and My Contests now use the API. Contest members can now save drafts, review server calculations and submit immutable portfolio versions. Valuation, benchmark comparisons, rankings, dashboard metrics and contest result finalization now use persisted snapshots. Courses, lessons, quizzes, XP, achievements and streaks now use persisted learning records. Virtual coin earnings, tiers, sandbox inventory/redemption, ledger and history now use the API. Community posts, replies, likes, private saves, polls, discoverable communities with members-only feeds and administrator moderation now use the API. Private performance-coach jobs/reports and decision journals now use the API, with local Ollama and an explicitly configured Gemini adapter.

InvestIQ is simulation-only. Capital, cash and fees are virtual; Phase 6 calculates and finalizes contest results and rankings, with no real trades, payments, payouts or financial settlement.

## Administrator content publishing

Verified administrators can list courses with `GET /api/v1/admin/courses`, publish a course and its initial lessons with `POST /api/v1/admin/courses`, and append a lesson with `POST /api/v1/admin/courses/{course_id}/lessons`. Course input contains `slug`, `title`, `description`, and `lessons`; lesson input contains `title`, `xp`, `paragraphs`, and `questions`. Each question contains `key`, `prompt`, `options`, a zero-based `correct` index, and `explanation`. See `/docs` for the complete request schemas.

Writes require a valid session, CSRF protection, verified email, and a current database admin role. Publication is transactional and recorded in the audit log. Course URL names are unique; concurrent lesson additions receive distinct ordered positions. Public lesson responses omit correct answers and explanations until a learner submits a quiz. No migration or curriculum reseed is required for authored content.

## Profile photos

`GET /me` includes nullable `photo_version`. Authenticated `GET /me/photo` serves
only the current user's photo. CSRF-protected `PUT /me/photo` accepts raw JPEG,
PNG, or WebP bytes up to 1 MB; `DELETE /me/photo` restores the initials avatar.
The browser editor crops larger local photos before upload. Pillow validates the
decoded image, rejects animation and oversized dimensions, and stores a fresh
256 × 256 JPEG without original metadata in `profile_photos`. Photo changes are
audited; image bytes are excluded from ordinary profile JSON and AI context.
Migration `0014_profile_photos` is additive. Rebuild the API, worker and scheduler
with the normal Compose command below to install Pillow and apply the migration.

## Start the backend

For the complete local Phase 10 stack (API, Celery worker and one Beat scheduler), start Ollama on the host with `llama3.1:8b` installed (`ollama list`; pull it if missing), then:

```bash
cd investiq-be
docker compose --profile app up -d --build --wait
```

Host API development is also supported below; run the separate worker/Beat commands in [PHASE-6.md](docs/PHASE-6.md#start-and-operate-locally) to update results automatically.

Prerequisites: Docker Desktop running, Python 3.13, and [uv](https://docs.astral.sh/uv/getting-started/installation/). Run these commands from the project root:

```bash
cd investiq-be
cp .env.example .env
uv sync --locked
# PostgreSQL on 5433 and Redis on 6380; both bind only to loopback.
docker compose up -d --wait postgres redis mailpit
uv run --locked alembic upgrade head
uv run --locked python -m investiq.market_cli --public-contests
uv run --locked python -m investiq.learning_cli
uv run --locked python -m investiq.rewards_cli
uv run --locked uvicorn investiq.main:create_app --factory --reload --host 127.0.0.1 --port 8080 --no-access-log
```

Use `cp` only for initial setup; keep your existing `.env` on subsequent starts. The application reads `.env` relative to this directory. No model key or market-data account is needed.

Open http://127.0.0.1:8080/docs for Swagger. From another terminal:

```bash
curl -i http://127.0.0.1:8080/api/v1/health/live
# HTTP 200: {"status":"ok"}
curl -i http://127.0.0.1:8080/api/v1/health/ready
# HTTP 200: {"status":"ready","checks":{"postgresql":"ok","redis":"ok"}}
```

Readiness returns HTTP 503 with `status: unavailable` when a dependency is unreachable or the schema revision is wrong. Liveness stays independent of those dependencies. Check that Docker is running and migrations completed if readiness fails. Ports 5433/6380 avoid common local database ports; change Compose port mappings and `.env` URLs together if needed.

An alternative, requiring only Docker, runs the API and migrations in containers:

```bash
docker compose --profile app up -d --build --wait
```

This runs migrations and idempotent development market, learning and sandbox reward seeds before starting the API. Container dependencies use the hash-verified `requirements.lock` export of `uv.lock`; see the dependency guide before updating packages. Do not run the host API and container API simultaneously on port 8080. After code changes use `--build` again. This Compose stack is for local development; image major tags receive upstream patches, whereas Python packages are fully locked.

Stop the host API with Ctrl+C, then stop infrastructure with `docker compose down`. Named volumes retain data.

## Verify

From `investiq-be`, with infrastructure running:

```bash
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked alembic check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
```

The default test suite includes **real PostgreSQL and Redis** integration tests. Foundation tests use temporary tables; identity tests create and drop a dedicated migrated database. Redis keys have unique namespaces and TTLs; tests never flush Redis or create demo business activity in your application database. The local PostgreSQL test role needs CREATEDB permission. `uv run --locked pytest -m 'not integration'` runs only infrastructure-independent tests. There is no SQLite substitute. HTTP tests use HTTPX ASGI transport and explicitly run application startup/shutdown.

## Frontend connection

From `investiq-fe`, run `npm ci` and `npm run dev`, then open **http://localhost:5173**. The Vite proxy already forwards `/api` to port 8080. Registration/login, onboarding, profile/settings, session revocation and email-link forms are connected. Cookies and CSRF are managed by the API client; no tokens or account records are saved into localStorage.

Open **http://localhost:8025** for local verification/reset emails. Mailpit captures messages locally. No real user activity is seeded and no demo activity is uploaded. The frontend now includes its missing `.env.example`.

See [Phase 2 identity contracts](docs/PHASE-2.md), [Phase 3 market schema, policies and tests](docs/PHASE-3.md), [Phase 4 contests](docs/PHASE-4.md), [Phase 5 portfolios](docs/PHASE-5.md), and [Phase 6 simulated results and worker setup](docs/PHASE-6.md). The portfolio screen uses backend catalogue, filtering and timestamped synthetic EOD quotes. Signed-out portfolio previews remain separate. Signed-in contest members use server-owned drafts and immutable submissions. Contest discovery, draft creation/revision, publication, in-app invitations, joining and My Contests now use PostgreSQL. Verify your email before hosting/joining; invitations appear in My Contests and send no external email. Published rules are frozen. Drafts and submissions are available; valuation and rankings are available through the results APIs.

## Layout and architecture

```text
src/investiq/
  main.py              application factory, middleware, dependency lifecycle
  api/                 HTTP routing, identity dependencies and operational probes
  schemas/             validated public response and request contracts
  core/                settings, error handling, JSON logging
  db/                  declarative base, async engine, request session dependency
  models/              identity, market, contest, portfolio and valuation persistence/constraints
  services/            identity, market, contest, portfolio and valuation services
  analytics/           pure deterministic Decimal allocation/performance
  jobs/                Celery/Beat periodic simulation valuation
  valuation_cli.py     manual trusted valuation/backfill command
  adapters/            SMTP and market provider interfaces/adapters
  data/                versioned synthetic dataset and reviewed calendar
  market_cli.py        development market seed
  contest_cli.py       optional private draft seed for an existing verified host
  cli.py               operator role provisioning
migrations/            versioned schema changes (Alembic)
tests/                 HTTP, configuration, PostgreSQL and Redis verification
docs/                  assessment, decisions, schema policy, progress
```

FastAPI routers play the role of Spring MVC controllers; Pydantic schemas are validated DTOs, settings resemble `@ConfigurationProperties`, and `get_session` is a dependency provider. SQLAlchemy's `AsyncSession` is the persistence context. Application services own `async with session.begin()` boundaries, analogous to `@Transactional`; request teardown never silently commits. Alembic provides Flyway/Liquibase-style version history.

Identity, market, contest and portfolio services/models, deterministic allocation, SMTP and a fixture market provider are implemented. Add the remaining domain, job, analytics and AI modules as their phases arrive. They are deliberately not empty service stubs. Celery now runs valuation scans; LangChain, LangGraph and PostgreSQL checkpointing begin with the coach; pgvector begins with retrieval. These packages are not installed before they have a runnable use.

See [frontend assessment](docs/PHASE-0.md), [architecture decisions](docs/DECISIONS.md), [database policy](docs/SCHEMA.md), [dependency verification](docs/DEPENDENCIES.md), and [progress](docs/PROGRESS.md).

## Market data scope

Prices use fixed synthetic scenarios for October 14–November 6, 2026 (with the public-contest extension enabled), with explicit freshness checks, source metadata and a reviewed 2026 calendar. They are not actual historical or live quotes. Stale/missing data blocks simulation eligibility; no automatic current-date price generation occurs. Production market reads/fixture seeding are disabled pending an approved feed. See [provider research and policies](docs/PHASE-3.md).

## Phase 4

Add contests, versioned frozen rules, discovery, invitations, membership, ownership and lifecycle transitions, then connect contest discovery and My Contests. Server-side portfolio drafts/submission and valuation follow in Phases 5 and 6.

## Try Phase 4

After starting the stack and frontend, open Contests → Create contest. Save a draft, review its rules, then publish. For private contests invite another verified email; the recipient accepts under My Contests. The host joins separately. Empty history is expected for new accounts. All schedules use the reviewed 2026 exchange calendar, with Asia/Kolkata inputs/display.

Optional seed after registering/verifying your account:

```bash
uv run --locked python -m investiq.contest_cli --owner-email you@example.com
```

This creates one retry-safe private fixture draft, with no invented memberships or performance. [Phase 4 documentation](docs/PHASE-4.md) includes exact API contracts, concurrency rules, test commands and limitations.

## Try Phase 5

Join a published contest, then open **Open contest portfolio** on its detail page or **Portfolio** from My Contests. Choose quantities or weights, **Save draft → Review saved draft → Confirm contest submission**. Each accepted version freezes actual whole shares, price/source evidence, simulated fee and residual cash. Earlier submissions remain immutable; the newest accepted version is authoritative at the entry deadline. Draft-only changes do not replace a submission.

The API rejects stale/incomplete EOD data. The original fixtures cover October 14–16, 2026; the optional fixed public-contest scenario extends coverage through November 6, with due-only EOD publication. [Phase 5 documentation](docs/PHASE-5.md) includes schema, accounting/rounding, API examples, development starter data and test commands.

## Try Phase 6

After joining/submitting, open **Performance** or **Leaderboard** from My Contests. The signed-in dashboard shows actual activity/results and links to completed-contest history. Workers value all ranked portfolios at one published session close, then finalize once all required contest sessions are complete. Missing prices leave results pending or marked out of date. Everything is virtual; there are no payments or financial settlement.

The public-contest scenario extends fixed synthetic EOD coverage through November 6, 2026 when enabled. Outside configured dates, results wait for complete prices; the scheduler never invents them. [Phase 6 documentation](docs/PHASE-6.md) includes the historical test scenario, full schema/API contracts, calculations, job retry rules and exact commands.

Learning setup, API contracts, database rules and verification: [Phase 7](docs/PHASE-7.md).


## InvestIQ public contests

Administrators can create platform-managed public contests alongside community leagues. Provision a verified account using the existing operator command, sign in again, then open **Contests → Manage InvestIQ contests → Add InvestIQ contest**. Learners find published contests using the **InvestIQ** filter, join without invitations, confirm a portfolio submission and follow standings. The Compose stack releases due prices from the fixed synthetic public-contest scenario through November 6, 2026. See [platform contest setup, authorization, API contracts and data coverage](docs/PLATFORM-CONTESTS.md).


Phase 8 connects Rewards to integer virtual coin earnings and sandbox redemption/history. Complete a first lesson to earn 50 coins, then open Rewards. See [PHASE-8.md](docs/PHASE-8.md) for schema, transaction guarantees, API examples, commands and sandbox limits. No real rewards are fulfilled.


Community contracts, membership rules and usage: [Community feeds](docs/COMMUNITIES.md) and [Phase 9](docs/PHASE-9.md). Open `http://localhost:5173/#/social`; My feed shows only joined communities. Verified accounts can create communities and join others. General discussions remain public; administrators can review reports through the moderation API.


The AI coach uses Ollama locally by default, without an API key. Open `http://localhost:5173/#/insights` after confirming a contest portfolio and its first successful valuation. Docker reaches Ollama at `host.docker.internal:11434`. Set `INVESTIQ_AI_PROVIDER=disabled` to keep deterministic evidence/journals and core features without generation. Gemini is an explicit future backend switch with model/key configuration; there is no automatic cloud fallback. Full configuration, checkpoint setup, worker commands and limitations: [Phase 10](docs/PHASE-10.md).


## Test a full contest without waiting for market hours

Use the isolated [manual frontend sandbox](docs/MANUAL-CONTEST-TESTING.md). Run `uv run --locked python scripts/manual_sandbox.py` from this directory, then open `http://127.0.0.1:8082/__sandbox__`. It starts a separate frontend at port 5175, uses fresh test accounts and lets you advance from entry to first valuation and final standings. Existing normal-app accounts/contests remain separate; Ctrl+C deletes the temporary sandbox database.


Ask Martin now uses private persisted conversations and the existing Ollama/Gemini configuration. Migration `0012_martin` is applied by the Compose app profile; the existing worker/Beat also processes Martin questions. Rebuild/restart the app profile after updating. No extra provider dependency or API key is needed for local Ollama. [Complete chat setup, endpoints and privacy](../investiq-fe/docs/ASK-MARTIN.md).


Contest Explorer supports `GET /api/v1/contests?activity=active` for scheduled, open, locked and running contests. The effective lifecycle is evaluated with the server clock and filtered before cursor pagination. Explicit `status` takes precedence, and the default API listing and My Contests behavior are unchanged. Each contest response includes `server_time` so the frontend can calculate consistent countdowns, including in the simulation sandbox. Rewards and prize amounts are not configured by the current contest schema; the Explorer displays that absence.

Contest schedule and holdings-invariant validation return fixed, actionable messages and field locations. The validation handler exposes only an allowlist of application-owned contest messages; raw Pydantic inputs, context and arbitrary messages remain excluded. Chronology is enforced as entry opening < entry closing < contest start < contest end for creation and revision, including admin-created public contests.

### Optional Yahoo daily market prices

Yahoo EOD prices can power new virtual contests, with Nifty 50 as the benchmark.
Existing synthetic contests retain their source. Migration `0013_yahoo_eod` and
worker/Beat support are included. See [setup, behavior and limits](docs/YAHOO-EOD.md).

### Market news

Home includes a rotating market brief beside the Nifty 50 overview, and Portfolio
lists five recent market headlines linking to the original articles. The existing
worker/Beat fetches the Economic Times Markets RSS hourly during NSE sessions.
No news API key or database migration is required. See
[schedule, caching, local setup and tests](docs/MARKET-NEWS.md).

### Subscription activation without billing

Migration `0015_subscriptions` adds account subscription state. `POST
/api/v1/me/subscription` accepts `{"plan":"student"}` (₹99/month) or
`{"plan":"standard"}` (₹199/month) with the usual authenticated cookie, CSRF and
origin checks. It returns `MeOut`, including the persisted plan, monthly price,
active/expired state, start/end dates, `auto_renew:false` and
`payments_enabled:false`. `GET /me` and all existing profile responses include
this state. No payment gateway, charge, invoice, automatic renewal or new feature
gating is involved. Free access remains available.

Activation lasts one calendar month using IST dates, with month-end clamping.
Concurrent retries for the active plan return the same dates; a different plan
returns `409 subscription_active` until the current term ends. Expiry is evaluated
on reads, and a later activation starts a fresh month. Audit events record each
new activation once. The Compose app profile applies the migration; host setups
run `uv run --locked alembic upgrade head` before restarting the API and workers.
