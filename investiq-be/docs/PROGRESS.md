# Implementation progress

- [x] Phase 0: inspect actual frontend, map pages/actions/endpoints, record inconsistencies and assumptions.
- [x] Phase 1: FastAPI factory, Pydantic settings, pinned dependencies and uv lockfile.
- [x] Phase 1: local PostgreSQL/Redis Compose stack and optional containerized API/migration service.
- [x] Phase 1: async persistence lifecycle, named constraints, Alembic baseline.
- [x] Phase 1: liveness/readiness, migration revision check, sanitized errors, request IDs, JSON logs and explicit CORS.
- [x] Phase 1: HTTPX tests, real PostgreSQL/Redis integration coverage, Ruff and mypy setup.
- [x] Phase 1: setup/run/test documentation, schema policy and architecture decisions.
- [x] Phase 2: identity, onboarding, preferences, authorization and frontend login/onboarding connection.
- [x] Phase 3: market-data foundation and fixture provider.
- [x] Phase 4: contests, invitations and membership lifecycle.
- [x] Phase 5: portfolio drafts, validations and immutable submissions.
- [x] Phase 6: deterministic simulation valuation, jobs, contest result finalization and rankings.
- [x] Phase 7: learning, quizzes, XP, achievements and streaks.
- [x] Phase 8: coin ledger, sandbox rewards and idempotent inventory/redemption.
- [x] Phase 9: community and moderation.
- [ ] Phase 10: deterministic evidence, checkpointed AI coach and evaluation.
- [ ] Phase 11: approved educational RAG, pgvector and grounding evaluation.
- [ ] Phase 12: notifications, operations, backup/restore, load/security tests and production deployment.

The original Phase 1 slice contained infrastructure only. Phase 2 adds genuine identity data and frontend identity integration; later business domains, workers and AI remain in their tracked phases.

Phase 1 verification: 15 pytest cases passed with real PostgreSQL and Redis; Ruff lint/format, strict mypy, Alembic schema comparison and uv lock validation passed. The production requirements export matches uv.lock. Docker image build, migration service and API readiness passed; both health routes were checked over HTTP.

Phase 2 adds eight identity tables, the approved version-1 question seed, secure cookie/CSRF flows, account verification/recovery through a local SMTP adapter, server-owned profile/onboarding/preferences/privacy, session controls, audited admin authorization and targeted frontend connections. See PHASE-2.md for contracts and operational limits.

Phase 2 verification: 33 backend tests passed; Chromium browser tests cover two end-to-end scenarios against disposable PostgreSQL databases and real local SMTP. Ruff, formatting, strict mypy, Alembic model comparison, frontend syntax/build, dependency-lock validation and container readiness passed.

Phase 3 adds six market tables, explicit fixture/calendar seed commands, a typed provider boundary, atomic/retry-safe EOD ingestion, instrument filters/keyset pagination, provenance and stale/missing/exclusion checks. Portfolio catalogue and quote previews now use the API without browser-price fallback. Production market data remains disabled. See PHASE-3.md for source research, exact scope and setup.

Phase 3 verification: 53 backend tests and five Chromium end-to-end tests passed. Ruff, formatting, strict mypy, Alembic schema comparison/offline SQL, lock validation, frontend syntax/build and Docker startup/readiness passed. The built wheel includes both market JSON assets. Test databases are removed on teardown.

Phase 4 adds five contest tables, immutable/frozen rule versions and instrument universes, public discovery with server filters/keyset pagination, private visibility, addressed in-app invitations, atomic seat allocation, clock-enforced lifecycle, idempotent creation and My Contests. The frontend creation/revision/publication/invitation/join flows now persist on PostgreSQL. Optional development seed requires an existing verified host and creates no invented activity. See PHASE-4.md for schema, contracts, exact commands and limitations.

Phase 4 verification: 57 backend tests and seven Chromium end-to-end tests passed. Coverage includes a concurrent race for one seat, private and unverified-email isolation, retries, exact deadlines and frozen-rule DB guards. Ruff lint/format, strict mypy, Alembic model comparison/offline SQL, uv lock validation, frontend syntax/build and rebuilt Docker startup/readiness passed. Test databases are removed on teardown. Phase 5 will add portfolio drafts and immutable submissions; Phase 6 will add simulated valuation and contest result finalization.

Phase 5 adds four portfolio tables, contest/member-scoped revision-controlled drafts, exact Decimal whole-share allocation, fee-reserved target weights, common-session price/benchmark checks, transactional validation, preview evidence hashes and idempotent append-only submissions. PostgreSQL sealing/immutability triggers prevent partial or edited snapshots; the latest accepted version freezes at entry close without a timer. Frontend contest portfolios support save/reload, server review, confirmation, history, quantity conversion and conflict handling. Signed-out practice allocations never migrate into real accounts. See PHASE-5.md.

Phase 5 verification: **78 backend tests and 10 Chromium browser tests passed**. Ruff lint/format, strict mypy, uv lock validation, Alembic model comparison/offline SQL and a disposable PostgreSQL downgrade/upgrade round trip passed. Frontend syntax/build and the rebuilt Docker migration/seed/API stack passed. Readiness reports PostgreSQL/Redis OK on revision `0005_portfolios`. The wheel includes analytics and the versioned starter input; disposable test databases were removed. Browser regressions also cover switching portfolios during a pending save.

Phase 6 adds four valuation/finalization tables, copied common-session price evidence, Decimal virtual valuation/returns/benchmark comparisons/concentration/drawdown, deterministic per-contest ranks and retry-safe simulation completion. Celery/Beat reconcile durable database work; one missing point blocks a whole day's ranking, with prior snapshots explicitly out of date. Dashboard, My Contests metrics, leaderboards, private performance and completed history now use recorded results. There are no real trades, payments, payouts, coins or XP. See PHASE-6.md.

Phase 6 verification: **85 backend tests and 12 Chromium browser tests passed**, including a real Celery subprocess consuming an isolated Redis queue, concurrent completion, immutable snapshots, deterministic ties, missing-price retry/backfill and all previous identity/portfolio flows. Ruff lint/format, strict mypy, uv lock checks, hash-locked container build, Alembic comparison/offline SQL, a disposable PostgreSQL downgrade/upgrade round trip, frontend syntax/build and wheel asset checks passed. API and worker are healthy, Beat is running, and readiness reports revision `0006_valuations` with PostgreSQL/Redis OK. Normal API test-clock routes return 404; temporary databases were removed.

## Phase 7 completed

Persistent courses, immutable lesson/question versions, enrollment, quiz attempts/answers, first-pass completion and XP events, achievements and IST streak days are implemented. Academy and the signed-in profile now use actual learning records. Published development content seeds two courses and six lessons without creating learner activity. Verification: 92 backend tests and 14 browser tests passed, including concurrent retry/XP protection, version preservation, server scoring, account isolation and IST date boundaries. See [PHASE-7.md](PHASE-7.md) for contracts and commands. Phase 8 is next.

Phase 7 operational checks also passed: Ruff lint/format, strict mypy, uv lock validation, Alembic model comparison/offline SQL, a disposable PostgreSQL downgrade to 0006 and upgrade to 0007 with seeded content, and wheel curriculum packaging. The rebuilt local API and worker are healthy, one Beat is running, readiness reports PostgreSQL/Redis OK, and the live course API returns the seeded curriculum.


## Platform public contests (Phases 4–6 extension)

Implemented a distinct platform organizer, shared verified-admin management, InvestIQ discovery badges/filter and administration forms, public participation through the existing submission/performance/leaderboard services, and publication checks for complete baseline prices and supported scenario dates. A separate due-only synthetic scenario extends development EOD data through November 6, 2026. No users are promoted and no genuine user activity is seeded. See [PLATFORM-CONTESTS.md](PLATFORM-CONTESTS.md). Phase 8 remains next.

Verification: **96 backend tests and 16 Chromium browser tests passed**. Ruff lint/format, strict mypy, dependency lock validation, Alembic model comparison/offline SQL, a migration downgrade/upgrade preserving an existing published community contest, wheel scenario packaging and the rebuilt container stack passed. API/worker are healthy, Beat is running, readiness reports PostgreSQL/Redis OK, and the normal API returns 404 for test-only admin controls.


## Results information enhancement

Added reviewed-calendar timelines to contest details, portfolio submission, leaderboard and performance pages. Server responses explain the actual waiting stage and publication times, separate confirmed from ranked portfolios and identify only the current viewer's submission state. Participants see confirmation/next-step guidance and explanations of upcoming metric categories. Non-participating administrators see public-standing/privacy guidance. This is a read-only presentation enhancement; no contest schedule, accepted submission or accounting rule is changed. See [platform contest guidance](PLATFORM-CONTESTS.md#results-timeline-and-submission-guidance).


Results information verification: **97 backend tests and 17 Chromium browser tests passed**. Ruff lint/format, strict mypy, frontend syntax/build and Alembic comparison passed. The rebuilt API/worker are healthy. Desktop/mobile inspection of the actual public contest confirms the October 21, 6:00 PM IST first-results timestamp and the distinction between one confirmed portfolio and zero ranked portfolios; the mobile page has no horizontal overflow.


## Phase 8 completed

Added integer virtual coin accounts and immutable earning/debit evidence, first-completion learning awards, bounded genuine-history recovery, lifetime-earning tiers, sandbox catalogue/inventory and atomic idempotent redemption with private histories. Connected Rewards replaces browser balances/redemptions, and every item explicitly disables real fulfillment/entitlements. New-account balances remain zero; demo activity is not migrated. The earlier public-contest/results changes were committed as `09a5ab8` before this phase. See [PHASE-8.md](PHASE-8.md). Phase 9 community is next.

Phase 8 verification: **104 backend tests and 19 Chromium browser tests passed**. Ruff lint/format, strict mypy, dependency lock validation, frontend syntax/build, Alembic model comparison/offline SQL, a disposable populated PostgreSQL rewards downgrade/upgrade with genuine-completion recovery, wheel packaging and the rebuilt hash-locked container stack passed. The API/worker are healthy, one Beat is running, and readiness reports PostgreSQL/Redis OK. Desktop/mobile catalogue inspection passed with six items and no mobile horizontal overflow.


## Phase 9 completed

Connected shared public posts/replies, likes, private saved posts, immutable final-vote polls, public groups and membership, private reports and current-admin moderation. Added PostgreSQL migration/guards, verified CSRF writes, normalized retry keys, keyset pagination and a separate Redis write limit. Names follow current profile privacy; hidden/deleted roots also restrict replies. No demo activity or community rewards are imported/generated. See [PHASE-9.md](PHASE-9.md). Phase 10 AI coach is next.

Phase 9 verification: **111 backend tests and 21 Chromium browser tests passed**. Ruff lint/format, strict mypy, frontend syntax/build, dependency lock validation, Alembic model comparison/offline SQL, disposable PostgreSQL downgrade/upgrade preserving existing account records and wheel contents passed. The rebuilt API/worker are healthy; one Beat is running; readiness reports PostgreSQL/Redis OK. Guest desktop/mobile inspection of the live Community route found no console errors or mobile horizontal overflow. Lost-response and route-change browser checks verified retained drafts, same-key post retries and usable moderation controls. Phases 8 and 9 are included in the same implementation commit.
