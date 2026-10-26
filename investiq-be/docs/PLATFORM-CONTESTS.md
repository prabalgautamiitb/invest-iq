# Platform public contests

## Behavior

InvestIQ contests are public contests managed by administrators. They appear in the normal Contest explorer, an **InvestIQ** filter, My Contests after joining, and the existing portfolio, performance and leaderboard pages. Community-created public/private leagues remain available.

Administrators create a draft, review its rules and schedule, and publish it. Publication freezes the rules. Any verified active learner may join during the entry window without an invitation, subject to the published capacity (up to 10,000). Joining does not submit a portfolio: the learner must save, review and **confirm** a submission before entry closes. Only accepted submissions enter valuations and standings. Admins are not automatically enrolled, and startup creates no users, memberships, submissions or rankings.

## Add your first public contest

Start the updated stack:

```bash
cd investiq-be
docker compose --profile app up -d --build --wait
```

Register and verify the account that will manage contests. Provision its administrator role through the existing operator command, replacing the example email:

```bash
docker compose exec api python -m investiq.cli set-role your-email@example.com admin
```

This revokes that account's existing sessions. Sign in again, open **Contests → Manage InvestIQ contests → Add InvestIQ contest**, choose the details, save the draft, and click **Publish and freeze rules**. Direct routes: `/#/contests/admin` and `/#/contests/create-platform`.

The administrator role is never granted by registration or by a public API. Operators choose which verified account receives it. Existing accounts are not automatically promoted.

Other users can select **Contests → InvestIQ**, open a contest, join, then use **Open contest portfolio → Save draft → Review saved draft → Confirm contest submission**. Standings are under **Leaderboard**, and private metrics under **My performance**. Results refresh on those pages through their refresh controls; they are EOD snapshots, not streaming ticks.

## Schema, ownership and authorization

Revision `0008_platform_contests` adds `contests.organizer VARCHAR(12) NOT NULL DEFAULT 'community'`, indexed, with a CHECK limiting values to `community`/`platform`. A second CHECK requires platform contests to be public. Existing contests remain community contests. A trigger freezes organizer identity even while in draft, so editing a community contest cannot grant it the InvestIQ label. Existing published-detail/rule immutability remains enforced.

`owner_id` remains the actual creating account for provenance, with its existing RESTRICT FK. Platform management belongs to the administrator role: another verified admin can revise/publish/cancel, while a demoted creator cannot. Community management remains with the original owner. API responses distinguish `is_owner` from `can_manage`; the UI uses `can_manage` for controls. Draft platform contests are visible only to current admins. Published public contests are visible without authentication; joining and submission still require a verified authenticated account.

The shared user→session→contest locks, verification/CSRF checks, draft-only revision, append-only rule versions, capacity locking, submission idempotency, common-time ranking and exactly-once result finalization are reused. Current DB roles are checked in the transaction; stale session role snapshots cannot grant access. Creation retains UUID idempotency keys and binds the request hash to the organizer type. Reusing a key across community/platform creation conflicts. The creation audit event is `platform_contest_created`; subsequent changes use the existing actor/resource audit events.

## APIs

| Request | Access and response |
| --- | --- |
| POST `/api/v1/admin/contests` | Verified admin, cookie/CSRF and UUID `Idempotency-Key`; accepts the existing `ContestInput`, requires `visibility: public`; returns a platform draft |
| GET `/api/v1/contests?organizer=platform` | Public published platform discovery; existing search/status/sort/pagination filters apply |
| GET `/api/v1/contests?scope=managed` | Admin-only platform catalogue including drafts; cursor is bound to viewer and filters |
| GET `/api/v1/contests/{id}` | Public after publishing; platform drafts admin-only |
| PUT `/api/v1/contests/{id}` | Admin for platform drafts; unchanged owner authorization for community drafts |
| POST `/api/v1/contests/{id}/transitions` | Admin for platform publication/cancellation; existing transition body and lifecycle constraints |
| POST `/api/v1/contests/{id}/entries` | Any verified learner during entry window; no invitation for public contests |
| Portfolio, performance and leaderboard routes | Existing services and contracts; no duplicate platform-specific accounting |

`ContestOut` adds `organizer: "community" | "platform"` and `can_manage: boolean`. `organizer` is not accepted in `ContestInput`; clients cannot attach a platform badge through ordinary creation. Example with cookies/CSRF from the identity flow and a valid public `ContestInput` saved in `contest.json`:

```bash
curl -b cookies.txt -X POST http://localhost:8080/api/v1/admin/contests \
  -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H 'Idempotency-Key: 7da70578-d558-40c2-9497-3c1ccfdc7240' \
  -H 'Content-Type: application/json' --data-binary @contest.json
curl 'http://localhost:8080/api/v1/contests?organizer=platform'
```

Creation returns 201 with `organizer: platform`, `visibility: public`, `status: draft`, `member_count: 0` and `can_manage: true`. After publication, guest discovery returns it with `can_manage: false`. Non-admin writes return 403; private platform input/unsupported scenario dates return 422; missing current baseline prices prevent publication with 409. Errors use the existing safe envelope.

## Fixed synthetic market scenario

The original fixture v1 remains unchanged for October 14–16, 2026. A separate immutable, checked-in `market_public_fixture_v1.json` / `public-fixture-v1` dataset adds these explicit session closes:

- October 19, 21, 22, 23, 26, 27, 28, 29 and 30, 2026.
- November 2–6, 2026.

These are development simulation prices, not historical exchange quotes, predictions or a production feed. No prices are generated at runtime or on arbitrary current dates. The reviewed exchange calendar and existing unsupported-corporate-action exclusions remain in force.

Only points whose session publication time (18:00 IST) has passed are ingested. A scheduled valuation scan first releases due entries from this fixed file, then values due contests. Future file entries are never used by API quote/submission/valuation queries before publication. After the scenario ends, pricing correctly becomes stale until an explicitly reviewed extension or approved provider is added. The scenario is intended for functional development; it is not an undisclosed price feed for competitive play.

`INVESTIQ_PUBLIC_CONTEST_FIXTURES_ENABLED=true` enables scheduled releases and coverage checks for the extension. Compose sets it for API/worker/Beat. The default is false for isolated legacy fixture tests. The normal worker scan remains every 60 seconds. The market seed CLI uses `--public-contests` to release due entries. Production environment guards still disable fixture ingestion and market/contest operations.

A platform contest cannot be published unless:

1. Its entire supported trading-session schedule exists in the configured explicit scenario.
2. The current expected published session has a complete common price batch for the eligible equities and benchmark, so learners can submit now.
3. All existing schedule, eligibility, exclusion and lifecycle validations pass.

No existing submissions or successful valuation snapshots are rewritten. Existing saved drafts remain drafts, and a closed contest is not reopened by this change.

## Host development and checks

For a host API/worker, add the new flag to your existing `.env`, then run:

```bash
cd investiq-be
uv run --locked alembic upgrade head
uv run --locked python -m investiq.market_cli --public-contests
uv run --locked uvicorn investiq.main:create_app --factory --reload --host 127.0.0.1 --port 8080 --no-access-log
```

Run the separate worker and single Beat described in Phase 6, or use the Compose app stack. Role provisioning on the host is `uv run --locked python -m investiq.cli set-role your-email@example.com admin`. Do not run a second API or Beat alongside the container process on the same resources.

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest -q
uv run --locked alembic check
# From investiq-fe:
npm run check
npm run build
npm run test:e2e
```

New integration tests exercise authority/role changes, shared admin ownership, draft/public visibility, public-only and immutable organizer constraints, retries, coverage/baseline publication gates, a learner's submission through final standings, concurrent fixed-price release, no early release, and the new scenario's submission/valuation provenance. Browser tests use a disposable database and loopback/header-gated harness to provision test admins; that helper is excluded from the normal application and Docker image.

Verification: **96 backend tests and 16 Chromium browser tests passed**. Ruff lint/format, strict mypy, dependency lock validation, Alembic model comparison/offline SQL, a migration downgrade/upgrade preserving an existing published community contest, wheel scenario packaging and the rebuilt container stack passed. API/worker are healthy, Beat is running, readiness reports PostgreSQL/Redis OK, and the normal API returns 404 for test-only admin controls.

## Files and scope

- Models, migration 0008, contest schemas/API/service: organizer, shared admin management, discovery and publication checks.
- Frontend `features/contests.js` and API helpers: admin catalogue/form, badge/filter, public participation and explicit submission guidance.
- Fixed market JSON, adapter/ingestion service, market/portfolio/valuation readers, worker/config/CLI/Compose: due-only explicit scenario release and original-source snapshots.
- Platform integration/browser tests, test-only admin harness and operational documentation.

This extends Phases 4–6. Phase 8 (coin ledger and sandbox rewards) remains next. There are no real trades, payments, settlements, prize payouts or fulfillment.


## Results timeline and submission guidance

Contest details and portfolios now show the entry window, start, first market close, expected first results and end, using reviewed calendar timestamps displayed in IST. `ContestOut` adds `first_session_closes_at` and `first_results_available_at`. These are scheduled publication times, not a guarantee that a result will exist if required prices are missing.

Leaderboard/performance responses include a `timing` object with `entry_opens_at`, `entry_closes_at`, `starts_at`, `ends_at`, `first_session_closes_at`, `first_results_available_at`, `next_results_available_at` and a server-derived state. States distinguish `not_started`, `awaiting_close`, `processing`, `awaiting_data`, `current`, `final`, `draft`, `cancelled` and `unavailable`. Client clock changes cannot cause a premature ranking or change the server's wait explanation. Calendar failure returns an unavailable schedule while retaining authorized recorded results.

Leaderboard output also distinguishes public aggregate `submitted_count` (distinct confirmed portfolios) from `participant_count` (ranked portfolios in the displayed snapshot). Account-specific `has_joined` and `has_submission` refer only to the authenticated viewer; guests receive false. Submission presence does not reveal holdings or private account data. The UI explains confirmed submissions, unsent drafts, delayed prices, refresh behavior and private performance access. Non-participating admins can follow standings and view contest details without a misleading My performance link.

The performance empty state explains the categories that become available after valuation: virtual value/return, benchmark/excess return, concentration/diversification, daily-close drawdown and holding contributions. The shared frontend timeline is `src/features/results-info.js`; API/service changes are read-only and require no new database migration.


Results information verification: **97 backend tests and 17 Chromium browser tests passed**. Ruff lint/format, strict mypy, frontend syntax/build and Alembic comparison passed. The rebuilt API/worker are healthy. Desktop/mobile inspection of the actual public contest confirms the October 21, 6:00 PM IST first-results timestamp and the distinction between one confirmed portfolio and zero ranked portfolios; the mobile page has no horizontal overflow.


## Manual testing without real-time waiting

Admin contests still obey entry deadlines, session-open starts and published EOD valuation. For interactive frontend testing, use the separate [manual contest sandbox](MANUAL-CONTEST-TESTING.md): fresh database/accounts, suggested October 15–16 fixture schedule, isolated session cookie and local buttons for locking, first valuation and final results. It does not change the current public contest or weaken normal API rules.

The creation and draft revision forms read `/api/v1/contest-simulation-sessions`
from the active API and flag unsupported start/end dates before saving. Publishing
still checks every exchange session on the server; errors name the active
coverage range and missing sessions. The disposable manual sandbox deliberately
uses only October 14–16, 2026: keep entry open on October 14, lock/start on
October 15, and end on October 16 to use its clock controls. The normal Docker
application enables the extended scenario through November 6.

For Yahoo-mode contests, the fixed fixture price window above does not apply.
They use the reviewed exchange calendar and a complete current Yahoo price batch.
Older synthetic contests keep their original scenario and source. See
[Yahoo end-of-day setup](YAHOO-EOD.md).
