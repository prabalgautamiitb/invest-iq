# Phase 4 — Contests

## Goal and prerequisites

A runnable contest vertical slice: public discovery, filters/detail, private drafts, creation/revision/publication, invitations, seat allocation, lifecycle and My Contests. Requires Phases 1–3, migrated PostgreSQL, Redis, the reviewed calendar, fixture catalogue and verified accounts. No additional dependencies were needed.

The API is a FastAPI router → reusable `ContestService` → SQLAlchemy transaction. Like a Spring `@Transactional` service, the service commits the whole operation or rolls it back; routers only handle HTTP/authentication/rate limits. Existing cookie/Origin/CSRF protections apply to every mutation. The actor is reauthenticated and locked inside the transaction, rather than trusting a previously cached role or client user ID.

## Files

- `models/contest.py`, `schemas/contest.py`, `services/contest.py`, `api/contest.py`: persistence, typed contracts, business rules and routing.
- `migrations/versions/0004_contests_contest_rules_invitations_and_.py`: five tables, constraints, indexes and immutability triggers.
- `contest_cli.py`: explicit, repeatable development seed.
- `main.py`, `migrations/env.py`, `db/session.py`: service/router registration and readiness revision.
- `services/identity.py`: expose the existing transaction-level `authenticated_user` helper for reuse.
- `tests/test_contest.py`: PostgreSQL HTTP/concurrency/security coverage. `scripts/e2e_server.py` fixes both market and contest clocks for browser tests.
- Frontend `src/features/contests.js`, `src/app.js`, `src/api/services.js`, `tests/browser/contest.spec.js`: preserve the existing visual shell, replacing contest fixtures/localStorage with APIs. Build syntax checks include the new module.

## Schema

All IDs are UUIDs, timestamps are timezone-aware UTC, and FKs use `RESTRICT`: contest history is retained instead of disappearing when a user, rule or instrument is deleted. Deactivation is the current account policy. There is no contest DELETE endpoint.

| Table | Purpose, columns and constraints |
| --- | --- |
| `contests` | Host-owned aggregate: UUID PK `id`, indexed `owner_id` → users; UUID `creation_key` unique with owner, SHA256 `request_hash` varchar(64); name varchar(80), description varchar(500), visibility varchar(8), level varchar(8), status varchar(12), capacity integer 1–10000; entry open/close, start/end and created timestamps. Indexed visibility, level, status, start. Checks constrain enums and `entry_opens_at < entry_closes_at < starts_at < ends_at`. Published details are frozen by a DB trigger. |
| `contest_rule_versions` | UUID PK, indexed contest FK, positive integer version unique per contest, `capital NUMERIC(14,2)` >0 and ≤100000000 (NaN prohibited), typed JSONB configuration and created timestamp. Unique `(contest_id,id)` supports the membership composite FK. JSON contains integer holdings limits/position and fee basis points, benchmark UUID and fixed execution-policy strings. Version rows cannot be updated or deleted; inserts require a draft contest. |
| `contest_eligible_instruments` | Immutable version-owned universe. Composite PK `(rule_id,instrument_id)` with FKs to rules and instruments; instrument index. Inserts require a draft, updates/deletes are prohibited by a DB trigger. Historical versions retain their instrument references. |
| `contest_memberships` | UUID PK, indexed contest/user FKs, rule UUID, joined timestamp. Unique `(contest_id,user_id)` makes joins retry-safe. Composite FK `(contest_id,rule_id)` prevents binding another contest's rules. Memberships bind the published version, not a mutable browser draft. |
| `contest_invitations` | UUID PK, indexed contest FK and normalized email varchar(320), status varchar(10), created/expiry timestamps; unique `(contest_id,email)` and expiry > created checks. Expiry index; status enum pending/accepted/declined/revoked. `expired` is derived when a pending invitation's expiry is reached. Email appears only in host/recipient invitation responses. |

`audit_events` from Phase 2 records creation, seed, revisions, publish/cancel, joins and invitation changes atomically. There are no payments, rewards, fabricated users, memberships or performance rows.

## Rules and lifecycle

Creation saves version 1 in `draft`; PUT appends a new immutable version while the contest is still a draft. Publishing freezes **all** details, schedule, capacity, universe and rules. No draft can have participants. Owners join through the same entry endpoint as everyone else; hosting does not allocate a seat.

The persisted status records explicit commands (`draft`, published state, `cancelled`; later `completed`). Time-driven status is a deterministic projection of the frozen schedule and current server UTC clock in **both SQL filters and detail/mutation checks**:

```text
draft --publish--> scheduled --> open --> locked --> running --> settling
  |                    |          |
  +-----cancel---------+----------+--> cancelled
```

At exactly entry-open, entry is allowed; at exactly entry-close, it is forbidden. Locking is strictly before the exchange start. At start it becomes running; at end it becomes settling. Publication can open immediately if entry-open has passed. Cancellation is host-only and permitted before entry locks, retaining memberships/history. Publish/cancel retries return the current resource; cancelled contests cannot be republished. `completed` is reserved for simulation result finalization in Phase 6 and cannot be asserted by a host. The `settling` API state means calculating final simulated results; it does not represent financial settlement. GETs do not mutate state or emit spurious audit events; time projections do not need a scheduler to enforce deadlines. The database's persisted status may lag the effective phase; use API status (or the same projection), not raw status for operational deadlines. A browser refresh retrieves the current phase.

Start must match a reviewed NSE session open; end must match a session close. Every intervening date must be covered and special unsupported sessions are rejected. Active fixture equities only; exclusions overlapping the entry-lock–end window reject the universe, including unsupported corporate actions. A benchmark must be an active fixture benchmark. Calendar coverage currently ends in 2026. Market/contest fixture functionality fails closed in production.

Configurable defaults: INR 1000000.00 capital, 5–12 holdings, 2500 position basis points (25%), 10 cost basis points (0.1%). Capital remains Decimal/NUMERIC; no monetary calculation uses float. The immutable execution policy is `published_eod_before_lock`, `whole_shares_floor`, residual cash allowed, cost once on submission notional, and no in-contest trades. Phase 5 will implement that policy and reject stale/incomplete prices. Phase 4 does not sample prices or claim to have accepted a portfolio; a membership is distinct from a submission.

## Visibility, invitations and concurrency

Guests see published public contests. Signed-in users additionally see their own drafts/contests, their memberships, and published private contests with an unexpired pending invitation matching their verified address for acceptance. A draft is always owner-only. An unauthorized private detail or invitation ID returns 404. Public viewers never receive invitation emails. Profile privacy is independent of contest visibility; no participant name/email list is exposed.

Invitations are **in-app**, addressed to an email that may register later; no external email/Slack messages are sent and there is no bearer invitation secret. Owner creates them after publishing, before lock. They expire at the earlier of seven days or entry-close. A verified matching account can accept/decline; the owner can revoke pending invitations. Repeated creation returns the same invitation; terminal/expired invitations are not silently reactivated. Repeated accept/decline/revoke of the same terminal state returns that state. A revoked/declined/expired invitation needs a future explicit reissue design, not an automatic retry. Accepting during scheduled time fails until entry opens. Join requires a private invitation except for the host. Cancellation hides unaccepted invitations from recipients and blocks acceptance. Existing memberships remain visible for history.

Write lock order: actor user → session → contest → invitation. All join/accept operations lock the contest row before counting and inserting seats; simultaneous final-seat requests cannot oversubscribe. Unique membership constraints provide a second line of defense. Acceptance, membership allocation and audit commit together; full/closed contests roll back all invitation changes. Duplicate membership requests return the existing membership even after lock/cancellation without allocating another seat. Revocation/recovery and role changes remain serialized by the same identity lock order.

Creation requires a UUID `Idempotency-Key`, unique per owner. Identical retries return the existing contest; another payload with the same key is 409. The key/hash never appears in the public DTO. Draft revision is an explicit new version each time; repeated revisions are not falsely described as idempotent. Creation/revision and invitations use Redis rate limits. Reads paginate with opaque keyset cursors bound to actor/filter/sort/scope; cursors confer no authorization. Page sizes are 1–100, default 20. Concurrent creation/name edits may alter discovery ordering; refresh after changes.

## API contracts

`/api/v1` prefix applies throughout. All typed mutation bodies reject unknown fields. Errors retain the existing `{error:{code,message,details},request_id}` envelope.

| Method and path | Contract |
| --- | --- |
| GET `/contest-template` | Nonpersisted valid starting configuration using the next five covered exchange sessions; no fake contest/activity seed. |
| GET `/contests` | `{items:[ContestOut],next_cursor}`; filters `query`, `visibility=public/private`, `level=all/beginner/advanced`, effective `status`, `scope=discover/joined/hosted`, `sort=name/-name`, `cursor`, `limit`. Joined/hosted require authentication. Literal `%`/`_` search characters are escaped. |
| GET `/contests/{uuid}` | Visible contest, effective status, immutable rules/version, actual member count, `is_owner`, `joined`; hidden resources 404. |
| POST `/contests` | Verified actor + CSRF + UUID Idempotency-Key; `ContestInput`, 201 draft. |
| PUT `/contests/{uuid}` | Verified owner, full ContestInput; append version, draft-only. |
| POST `/contests/{uuid}/transitions` | `{action:"publish"}` or `{action:"cancel"}`; frozen/late/conflicting changes 409. |
| POST `/contests/{uuid}/entries` | No user ID/body required; verified account joins atomically, returns ContestOut. Full/closed 409. |
| GET `/me/contests` | Contest page, `scope=joined/hosted`, cursor/limit. Includes historical/cancelled memberships without invented performance. |
| POST `/contests/{uuid}/invitations` | Verified host, `{email:"learner@example.com"}`, 201 InvitationOut; up to 1000 unique addressed invitations per contest. |
| GET `/contests/{uuid}/invitations` | Host-only invitation page, cursor/limit. |
| GET `/me/contest-invitations` | Current account's addressed invitation page, cursor/limit. |
| POST `/contest-invitations/{uuid}/accept` | Verified recipient; atomic invitation + seat + audit. |
| POST `/contest-invitations/{uuid}/decline` | Verified recipient declines. |
| POST `/contest-invitations/{uuid}/revoke` | Verified host revokes a pending invitation. |

Example input (use real UUIDs from `/instruments`; `/contest-template` supplies a ready-to-use equivalent):

```json
{
  "name": "Campus learning league",
  "description": "Fixture simulation, no prizes.",
  "visibility": "private", "level": "beginner", "capacity": 100,
  "entry_opens_at": "2026-10-18T00:00:00Z",
  "entry_closes_at": "2026-10-19T03:40:00Z",
  "starts_at": "2026-10-19T03:45:00Z",
  "ends_at": "2026-10-23T10:00:00Z",
  "rules": {
    "capital": "1000000.00", "min_holdings": 5, "max_holdings": 12,
    "max_position_bps": 2500, "simulated_cost_bps": 10,
    "benchmark_id": "<benchmark UUID>",
    "eligible_instrument_ids": ["<at least five distinct equity UUIDs>"]
  }
}
```

The response adds actual UUID `id`, `owner_id`, `rule_id`, `rule_version:1`, `status:"draft"`, `member_count:0`, `is_owner:true`, `joined:false` and explicit fixed rule policies. Decimal capital serializes as a string. Schedules are UTC; the UI inputs/display are explicitly Asia/Kolkata. The angle-bracket UUID markers above are explanatory, not runnable UUIDs.

Example requests after registering/verifying through the UI, with a local cookie jar and CSRF environment variable (never paste these into logs):

```bash
curl -sS http://localhost:8080/api/v1/contests
curl -sS 'http://localhost:8080/api/v1/contests?visibility=public&status=open&sort=name&limit=20'
curl -sS http://localhost:8080/api/v1/contest-template -o /tmp/investiq-contest.json
# Review/edit the file, then use a fresh key from: uv run python -c 'import uuid; print(uuid.uuid4())'
curl -sS -b /tmp/investiq-cookies.txt -X POST http://localhost:8080/api/v1/contests \
  -H "X-CSRF-Token: $INVESTIQ_CSRF" -H "Idempotency-Key: $INVESTIQ_CREATION_KEY" \
  -H 'Content-Type: application/json' --data-binary @/tmp/investiq-contest.json
curl -sS -b /tmp/investiq-cookies.txt -X POST "http://localhost:8080/api/v1/contests/$INVESTIQ_CONTEST_ID/transitions" \
  -H "X-CSRF-Token: $INVESTIQ_CSRF" -H 'Content-Type: application/json' -d '{"action":"publish"}'
curl -sS -b /tmp/investiq-cookies.txt -X POST "http://localhost:8080/api/v1/contests/$INVESTIQ_CONTEST_ID/entries" \
  -H "X-CSRF-Token: $INVESTIQ_CSRF"
curl -sS -b /tmp/investiq-cookies.txt http://localhost:8080/api/v1/me/contests
```

Cookie/CSRF bootstrap details are in PHASE-2.md. A fresh local database returns `{"items":[],"next_cursor":null}` until a verified host publishes a contest. Date examples are valid for the stated October 2026 scenario; use the template rather than replaying past deadlines.

## Run and exercise

```bash
cd investiq-be
# Existing .env from Phases 1–3; fresh clones: cp .env.example .env
uv sync --locked
docker compose up -d --wait
uv run --locked alembic upgrade head
uv run --locked python -m investiq.market_cli
uv run --locked uvicorn investiq.main:create_app --factory --host 127.0.0.1 --port 8080 --reload --no-access-log
```

Or run the complete container stack: `docker compose --profile app up -d --build --wait`. Do not run both APIs on 8080 simultaneously. Frontend, in another terminal:

```bash
cd investiq-fe
npm ci
npm run dev
```

Open http://localhost:5173, register and verify through http://localhost:8025. Go to Contests → Create contest → save draft → review/edit → Publish and freeze rules. Join explicitly. For a private league create an in-app invitation to another verified account; that account accepts under My Contests. Joined/Hosted tabs and the switcher retain server state across reloads. Browser demo data is never uploaded; contest API failures have error/retry states and no demo fallback. Private responses remain in account-scoped memory and obsolete route/account requests are discarded.

Optional development seed after verifying an account:

```bash
cd investiq-be
uv run --locked python -m investiq.contest_cli --owner-email you@example.com
# Or, for a container-only setup:
docker compose exec api python -m investiq.contest_cli --owner-email you@example.com
```

This creates one private draft owned by the specified account using the next five covered sessions. Repeats return that draft, even after publication; no extra users/memberships are fabricated, no email is sent and no rewards issued. Review/publish it in Hosted contests. Nothing automatically seeds contests into real account history.

## Verification and limits

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

Tests migrate disposable real PostgreSQL databases. Coverage includes verification/CSRF/ownership, invisible drafts/private contests, changing payloads under an idempotency key, append-only versions and DB guards, invitation cross-account access/retries/revocation/decline/expiry, frozen membership version, exact deadline boundaries, cancellation/terminal states, unsupported universe/schedule, stable filter pagination, a race for one seat, development seed and production fail-closed behavior. Chromium verifies creation/revision/publish, cross-account invitations, persistence/My Contests and API-failure behavior. Test DBs are removed on teardown.

Phase 4 provides contest metadata and membership, not accepted portfolios, live prices, returns, final leaderboard results, prizes, XP or coins. The existing builder remains a separate market-data practice preview; no contest detail button falsely claims its local draft is a server submission. Benchmark UUID stays in the typed rule snapshot (future rule/schema migrations can normalize additional benchmark metadata). The next phase implements server-side drafts, integer share conversion, Decimal validations, pre-start locking and immutable submissions using these frozen rule IDs.

Verified result: **57 backend tests and seven Chromium browser tests passed**. Ruff lint/format, strict mypy, Alembic model comparison/offline SQL, uv lock validation and frontend syntax/build passed. The rebuilt Docker migration/seed/API stack is healthy and `/api/v1/health/ready` reports PostgreSQL/Redis OK.
