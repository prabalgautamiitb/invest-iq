# Database and API contract policy

## Phase 1 schema

The baseline revision is `0001_foundation`; the current head is `0003_market`. Alembic owns `public.alembic_version`: `version_num VARCHAR(32) NOT NULL PRIMARY KEY`, containing the applied revision. This internal migration table has no owner, foreign keys, user data, deletion behavior or domain state. Upgrading the baseline adds no domain tables; downgrading removes the revision marker through Alembic's normal mechanism. Migrations run as a separate deployment step, never implicitly on web requests.

The baseline's empty upgrade/downgrade are intentional: no speculative users, portfolios or ledger tables exist yet. There is no business seed in Phase 1 because there is no domain schema. Infrastructure readiness plus PostgreSQL/Redis tests provide the runnable slice. Do not seed the frontend's sample activity.

## Domain schema delivery requirements

Each subsequent phase documents purpose/ownership, typed columns, primary/foreign keys, unique and check constraints, indexes, deletion behavior, state transitions, transaction locking/retry policy, sample requests/responses and versioned migrations. A constraint must accompany any invariant that the database can enforce. Never use cascading deletion to erase immutable accounting, submissions or audit records accidentally.

| Phase | Minimum schema introduced |
|---|---|
| 2 | Users/credentials, sessions, verification/recovery tokens, profiles/preferences/privacy, question-set versions/options, responses/classifications, identity audit events |
| 3 | Sectors, instruments, prices and benchmarks, ingestion runs, exchange sessions, corporate-action exclusions |
| 4 | Contests, frozen rule versions, eligible instruments, invitations, memberships |
| 5 | Versioned drafts, draft holdings, immutable submissions and holdings, active submission reference |
| 6 | Valuation snapshots/results, leaderboard snapshots, contest finalization events and reliable outbox |
| 7 | Courses/lessons/versions, enrollments/progress, questions, quiz attempts/answers, XP events, achievements/streak events |
| 8 | Coin accounts, immutable ledger, tiers, catalog/inventory, idempotency records, redemptions/fulfillment states |
| 9 | Posts/comments/reactions/saves, polls/options/votes, groups/memberships, moderation |
| 10 | Owned journal entries, jobs/workflow runs, reports/versions/evidence, checkpoint tables |
| 11 | Approved documents/versions/chunks/embeddings, owned assistant threads/feedback |
| 12 | Notifications/preferences/delivery, remaining audit/outbox and operational retention |

UUID keys apply to application entities, not Alembic's internal version marker. Use UTC timestamps; display exchange events in Asia/Kolkata. Monetary API fields will be decimal strings; weight fields integer basis points. Proposed starting precisions are NUMERIC(20,4) for prices, NUMERIC(20,2) for posted currency amounts, integer shares and NUMERIC(24,8) for calculated ratios; each domain migration must justify and constrain its chosen range.

## Phase 1 HTTP contracts

`GET /api/v1/health/live` → HTTP 200 `{"status":"ok"}`.

`GET /api/v1/health/ready` → HTTP 200 `{"status":"ready","checks":{"postgresql":"ok","redis":"ok"}}` or HTTP 503 `{"status":"unavailable","checks":{"postgresql":"unavailable","redis":"ok"}}`. Each dependency check has a configurable bounded timeout and no credential-bearing diagnostics in output.

Unknown paths use HTTP 404 with, for example:

```json
{"error":{"code":"http_404","message":"Not Found","details":[]},"request_id":"server-generated-uuid"}
```

No authentication is required for probes. Business routes are absent, rather than returning fake success.

## Collection contracts for later phases

Use an opaque keyset cursor, a bounded `limit` (default 20, maximum 100), an explicit sort allowlist and stable UUID tie-breakers. Responses use `{items: [...], next_cursor: "..."}` with a null cursor at the end. Filters use validated enums/IDs; never interpolate client sorting into SQL. These collection helpers will be implemented with the first collection, rather than shipped unused now.

## Phase 2 schema

The identity migration and full column/constraint/ownership/locking contracts are documented in [PHASE-2.md](PHASE-2.md#database-schema). The only content seed is the approved version-1 onboarding question set.

## Phase 3 schema

See [PHASE-3.md](PHASE-3.md#data-model) for all six market entities, column types, ownership, constraints, deletion policies and ingestion state transitions. Prices use NUMERIC(20,4) and decimal-string JSON. Migration 0003 creates schema only; market fixtures require the guarded development seed.

## Phase 4: contests

Migration `0004_contests` adds `contests`, `contest_rule_versions`, `contest_eligible_instruments`, `contest_memberships`, and `contest_invitations`. [PHASE-4.md](PHASE-4.md#schema) documents columns/types, ownership, FK deletion restrictions, unique/check constraints, indexes, immutable snapshot triggers, lifecycle projection and transaction lock order. Capital uses NUMERIC(14,2); costs/limits are integer basis points. Memberships have a composite FK ensuring their rule belongs to the same contest. Never infer a portfolio submission or result from a membership alone. Read the effective server-clock status rather than the potentially older persisted publication status.

## Phase 5: portfolios

Migration `0005_portfolios` adds `portfolio_drafts`, `portfolio_draft_positions`, `portfolio_submissions`, `portfolio_submission_holdings` and a composite membership/rule unique key. See [Phase 5 schema](PHASE-5.md#schema) for every column, key/check/index, ownership/deletion rules, immutable/sealed snapshot construction and locking. Drafts use optimistic revisions; submissions have member/version, draft/revision and member/idempotency-key uniqueness. Capital/notional/fee/cash use NUMERIC(24,4), prices NUMERIC(20,4), target percentages NUMERIC(7,4), shares BIGINT. Pricing evidence is copied, not reconstructed from subsequently changed source rows. The latest accepted version is authoritative; an unsent draft does not change it.

## Phase 6: simulated valuation and finalization

Migration `0006_valuations` adds `valuation_runs`, `valuation_prices`, `valuation_records`, `contest_finalizations` and a composite submission/member key. [PHASE-6.md](PHASE-6.md#schema-and-constraints) documents each column, ownership, types, FKs, unique/check/index constraints, immutability/completeness triggers, state transitions and transactions. Money uses NUMERIC(24,4), prices NUMERIC(20,4), percentage/risk metrics NUMERIC(20,8). Successful snapshots and finalization are immutable; failed jobs retain retryable metadata. These are virtual contest results, not financial settlements.

## Phase 7 learning

Revision `0007_learning` adds ten learning tables for published courses/lessons/versions, enrollments, attempts/answers, completions, integer XP events, IST activity days and achievements. All are immutable; composite FKs preserve attempt ownership and deferred triggers validate complete scoring/award evidence. See [PHASE-7.md](PHASE-7.md#schema-and-ownership) for columns, constraints, indexes, deletion policy and transaction details.


## Platform contest extension

Revision `0008_platform_contests` adds indexed `contests.organizer VARCHAR(12) NOT NULL DEFAULT 'community'`, an enum-like CHECK, a platform-implies-public CHECK and an immutable organizer trigger. Existing ownership/rules/membership/submission/result constraints remain. See [platform contests](PLATFORM-CONTESTS.md) for role ownership, contracts, transactions and the separate fixed market scenario.


## Phase 8 virtual coins/rewards

Revision `0009_rewards` adds six tables: `coin_accounts`, `coin_ledger`, `reward_tiers`, `reward_items`, `reward_inventory`, `reward_redemptions`. Integer coin units, source-bound unique immutable events, account sequence/totals checks, sandbox-only receipts and deferred inventory/debit evidence protect retries and concurrency. All source/ownership FKs use RESTRICT. Full column/type/index/state/deletion/locking documentation: [PHASE-8.md](PHASE-8.md#schema-and-ownership).


## Phase 9 community

Revision `0010_community` adds `community_groups`, `community_members`, `community_content` (posts/replies and immutable poll options), `community_reactions`, `community_saves`, `community_votes`, `community_reports`, and `community_moderation`. UUID ownership/FKs, UTC timestamps, unique retry keys, composite interaction keys, soft deletion, frozen content and database-validated final votes protect activity. Existing privacy and audit records are reused. Full columns, API boundaries and concurrency: [PHASE-9.md](PHASE-9.md#schema-and-ownership).


## Phase 10 performance coach

Revision `0011_coach` adds `coach_jobs`, `coach_requests`, `coach_reports`, `coach_attempts`, `coach_reflections` and a private `investiq_ai` schema for the pinned LangGraph PostgreSQL saver's checkpoint tables. Jobs freeze same-owner valuation/lesson evidence and provider/prompt/generation policy, bind retry keys, use short claims and bounded leases, and complete atomically with an immutable report. Private reflections are append-only and excluded from inference. SHA-256 evidence fingerprints, source-ownership/immutability/deferred completion triggers, nullable usage/cost telemetry and cursor-bound private history are described in [Phase 10](PHASE-10.md#data-model). The saver manages its own checkpoint-table migrations through the explicit setup CLI, outside Alembic's public-schema model comparison.


Revision `0012_martin` adds `martin_conversations` and `martin_turns`: private bounded conversations, session-derived ownership, same-owner foreign keys, unique per-user question keys, frozen source evidence, provider policy, queued/running/terminal states and bounded leases/attempts. Successful turns require a complete validated answer; deleting a conversation cascades to its questions/evidence/answers. No decision journal or quiz answer keys enter inference. [Ask Martin contracts](../../investiq-fe/docs/ASK-MARTIN.md).
