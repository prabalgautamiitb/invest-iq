# Phase 5 — Portfolio builder

## Goal, dependencies and files

Contest-scoped server drafts, quantity/weight allocation, deterministic validation, review, immutable submission snapshots, resubmission before lock and frontend integration. Requires verified membership from Phase 4, the reviewed exchange calendar and a complete fixture EOD publication from Phase 3. No dependencies were added or upgraded. Workers and ranking remain Phase 6.

New files: `models/portfolio.py`, `schemas/portfolio.py`, `services/portfolio.py`, `api/portfolio.py`, `analytics/portfolio.py`, migration `0005_portfolios`, `data/portfolio_draft_fixture_v1.json`, and `tests/test_portfolio.py`. Frontend: `src/features/portfolio.js`, `tests/browser/portfolio.spec.js` and browser `helpers.js`. Modified registration/readiness/model imports, membership constraints, API helpers, contest detail/My Contests links, app routing/account resets and syntax checks.

`PortfolioService` owns a transaction from authorization through validation and persistence, like a Spring service with `@Transactional`. Pydantic models are validated DTOs; SQLAlchemy's async session is the persistence context. `analytics/portfolio.py` contains pure deterministic Decimal calculations without database/provider/LLM calls. Routers handle HTTP, UUID idempotency headers, CSRF/session dependencies and Redis rate limits. Existing package locks remain unchanged.

## Decisions and exact accounting

A membership owns one draft. Drafts can be empty or below the minimum holdings while work is in progress; each included position must be distinct, positive, in the frozen universe and use the selected mode. Drafts cannot exceed the frozen maximum or include newly inactive/excluded instruments. Each save requires the current `expected_revision` and increments it. A stale tab receives 409, without overwriting another tab's draft. Revision 0 represents no persisted draft. A GET never invents activity.

Submission requires a saved revision, a successful server review and its `preview_hash`. The same calculation and authorization checks run again during confirmation. Changed price/evidence requires another review. No client price, user ID, fee, rank, return, cash or rule configuration is accepted.

### Prices

`published_eod_before_lock` means the **latest expected completed/published session at the server submission time**, which must be strictly before entry closes. We do not sample a future lock-time price or silently reprice an accepted snapshot at the deadline. Preview is provisional: if the expected session or any evidence changes before confirmation, re-review is required. Different submissions can sample different EOD sessions; Phase 6 must use a common valuation time when comparing results.

All selected equities **and the frozen benchmark** must have their expected session's closing observation, a source publication no later than the pricing cutoff, and belong to one succeeded `investiq-synthetic / fixture-v1` batch. Missing/stale/inactive/excluded instruments or a missing benchmark fail with 409. There is no fallback to an earlier session. Calendar coverage, unsupported special sessions, and exclusions through contest end fail closed. Eligibility is rechecked even though the whitelist was frozen. Source ingestion time is retained as provenance; fixture ingestion may occur after its historical observation/publication, and the reviewed as-of cutoff is based on source publication, not a claim that historical ingestion happened earlier.

Every accepted equity and benchmark stores its copied price and provenance plus a reference to the original price snapshot. Later source changes do not change the immutable copy. Freshness is checked at submission, not when retrieving history. Reads of an accepted snapshot continue to work after prices become stale or a contest locks/cancels.

### Shares, fees and cash

All accounting uses Decimal with a local precision of 50 and PostgreSQL NUMERIC. Prices have four decimal places; exact `quantity × price` notionals and cash have four places. The simulated fee is calculated once on aggregate notional, rounded to two decimal places with **ROUND_HALF_UP**. There is no per-row fee rounding.

For weights, reserve the fee before converting to shares:

```text
fee_rate = simulated_cost_bps / 10000
allocation_budget = floor_to_paise(capital / (1 + fee_rate))
target_notional_i = allocation_budget × weight_pct_i / 100
quantity_i = floor(target_notional_i / price_i)
notional_i = quantity_i × price_i
notional = sum(notional_i)
fee = round_half_up_to_paise(notional × fee_rate)
cash = capital − notional − fee
```

Target weights can total up to 100%; lower totals deliberately leave cash. Each target must purchase at least one whole share. Quantity mode uses the exact submitted whole-share counts, without another weight conversion. Quantities are positive strict integers ≤1,000,000,000; weights are positive exact decimal strings ≤100 with at most four decimal places (integer JSON values are also exact). Floats, booleans, NaN/Infinity, duplicate instruments and mixed modes are rejected.

Validate frozen min/max holdings, `notional_i × 10000 <= capital × max_position_bps`, total weights, positive whole shares, eligibility, and `notional + fee <= capital`. The position limit is measured against starting capital, excluding the fee. Residual cash is allowed; no redistribution or automatic purchase of more shares occurs. A submitted snapshot must satisfy `capital = notional + fee + cash` exactly.

For example, five 20% targets, INR 1000.00 capital, 10-bps fee, and prices 3.3333 produce 59 shares each: notional 983.3235, fee 0.98, cash 15.6965. Five shares with aggregate notional 5.0000 and a 10-bps fee produce a half-paise amount that rounds to fee 0.01.

## Lifecycle, authorization and concurrency

Only a verified member accesses their own draft/history. Contest ownership or an invitation alone does not create a portfolio. The URL contains the contest UUID, never a client-controlled portfolio owner. Another member sees their own portfolio, and a nonmember receives 404. Private contest visibility remains enforced; hosts cannot inspect someone else's draft through these endpoints. Account privacy settings do not grant portfolio access.

Draft save, review and new submission require effective contest status `open`; operations fail exactly at entry-close, before the exchange start. They also fail for cancellation. Services recheck status after potentially blocking work. Existing drafts/history become read-only; successful retry of the **same accepted idempotency key and payload** still returns the original result after lock/cancellation. A new key cannot reopen entry.

Submissions are append-only versions. Saving a draft after submission does not change the accepted version. A new successful submission supersedes the previous version for eventual contest valuation; **the highest accepted version is authoritative**, even if a later unsent draft exists. At lock that latest accepted version remains fixed without a background timer or job. Old versions remain auditable. A member with only an unsent draft has no accepted portfolio. No in-contest trading, editing of snapshots, rewards or valuation is introduced.

Resubmissions recalculate one virtual initial snapshot, with one fee on its notional. Fees from replaced versions are not accumulated or debited from an account. There are no actual orders or money movements.

Transaction lock order: user → session → contest → membership → draft, followed by shared instrument/price locks. This matches identity/contest operations and serializes cancellation against writes and concurrent saves/submits. SQL unique constraints also enforce one draft per member, one submission per draft revision, unique member/version and unique member/idempotency key. The composite membership/rule FK prevents freezing another membership's rules. Creation of submission, holdings, sealing and audit is atomic. Failures roll everything back.

Confirmation uses a UUID `Idempotency-Key` scoped to the membership and a SHA256 of the typed request. Concurrent same-key/same-body confirmations return the same ID/version; a reused key with another request is 409. Different keys for one already submitted draft revision return 409 `revision_submitted`; save a new revision to create another submission. The preview hash covers the frozen rule ID, draft revision, exact quantities, copied price/provenance for equities and benchmark, common session/calendar, totals and calculation version. Pricing evaluation wall time is excluded from the hash so an unchanged review remains confirmable; the actual cutoff is stored separately. Hashes/cursors confer no authorization.

## Schema

Migration `0005_portfolios` adds four tables and a unique `(id,rule_id)` key on memberships. All IDs are UUIDs, timestamps are aware UTC. Existing contest, rule, membership, instrument and price records use restrictive FKs so financial evidence survives; no API deletes submissions. Draft positions cascade only when their draft is deleted (there is no draft DELETE endpoint; saving replaces its current positions transactionally).

| Entity | Columns, purpose and constraints |
| --- | --- |
| `portfolio_drafts` | UUID PK, unique `membership_id` FK, positive integer revision, checked mode varchar(8), updated timestamp. User owns it through membership. Only the current draft is mutable; revisions provide optimistic concurrency, not archived draft copies. |
| `portfolio_draft_positions` | Composite PK `(draft_id,instrument_id)`; draft and instrument FKs; nullable BIGINT quantity and NUMERIC(7,4) weight percentage. Exactly one must be present and positive; quantity ≤1e9, weight ≤100, NaN prohibited. Draft mode consistency is enforced by typed input/service. |
| `portfolio_submissions` | UUID PK; indexed membership FK, rule and draft FKs, draft revision and member version; UUID idempotency key, request hash and preview hash varchar(64). Unique member/version, member/key and draft/revision. Composite `(membership_id,rule_id)` FK protects the frozen version. Capital, notional, fee, cash NUMERIC(24,4) with positive/nonnegative/NaN/accounting checks. Benchmark snapshot FK, copied NUMERIC(20,4) benchmark price with positive/non-NaN check, JSONB benchmark provenance, session date, calendar version varchar(60), pricing/submitted/lock timestamps with both pricing and submission strictly before lock, calculation version varchar(40), sealed boolean. |
| `portfolio_submission_holdings` | Composite PK `(submission_id,instrument_id)`; restrictive submission/instrument/price snapshot FKs. Copied symbol varchar(30), BIGINT positive quantity, price NUMERIC(20,4), notional NUMERIC(24,4), observation/publication/ingestion timestamps, source varchar(60), dataset version varchar(40). Check notional = quantity × price, positive/non-NaN amounts, publication ≥ observation. |

A DB trigger permits a new unsealed submission, then only one update that changes `sealed` from false to true while every other field stays equal. Updates/deletes after sealing are rejected. Holdings can only be inserted while their parent is unsealed; updates/deletes are always forbidden. A deferred constraint trigger rejects a transaction that leaves a submission unsealed, empty or with holdings whose aggregate notional differs from the header. This prevents a partial immutable snapshot from committing. Audit events record successful draft saves and submissions in the same transaction. The DB enforces snapshot construction/immutability and arithmetic consistency; authorization, clock projection, full rule validation and source eligibility remain service responsibilities.

## API contracts

Prefix `/api/v1`. All routes require session cookies and verified membership. Mutations additionally require the existing Origin/CSRF policy. Typed bodies reject extra fields. Draft writes, review and confirmation use separate Redis rate-limit buckets. Responses use decimal strings, never binary-float monetary values.

| Method/path | Input and result |
| --- | --- |
| GET `/contests/{id}/portfolio/draft` | Own draft, `{id,contest_id,rule_id,revision,mode,positions,updated_at,editable}`. No saved draft: id/updated_at null, revision 0, empty positions. |
| PUT `/contests/{id}/portfolio/draft` | `{expected_revision,mode:"quantity"/"weight",positions:[...]}` → updated DraftOut. Unknown/not eligible positions 422, stale revision 409. |
| POST `/contests/{id}/portfolio/preview` | `{draft_revision:1}` → PreviewOut with converted holdings, fee/cash, benchmark/equity price evidence, common session, cutoff, lock time, calculation version, preview hash. |
| POST `/contests/{id}/submissions` | UUID Idempotency-Key and `{draft_revision:1,preview_hash:"64 hex characters"}` → 201 SubmissionOut, including ID, member version, submitted time and `is_latest`. Same accepted retry also returns 201 with original ID. |
| GET `/contests/{id}/submissions` | Own newest-first history `{items:[SubmissionOut],next_cursor}`; limit 1–100/default 20, opaque membership-bound keyset cursor. No other-user history endpoint. |

An individual position is exactly one of:

```json
{"instrument_id":"<frozen eligible UUID>","quantity":10}
```

```json
{"instrument_id":"<frozen eligible UUID>","weight_pct":"20.0000"}
```

Example weight draft (supply five real eligible UUIDs for default rules):

```json
{
  "expected_revision": 0,
  "mode": "weight",
  "positions": [
    {"instrument_id":"<equity UUID 1>","weight_pct":"20.0000"},
    {"instrument_id":"<equity UUID 2>","weight_pct":"20.0000"},
    {"instrument_id":"<equity UUID 3>","weight_pct":"20.0000"},
    {"instrument_id":"<equity UUID 4>","weight_pct":"20.0000"},
    {"instrument_id":"<equity UUID 5>","weight_pct":"20.0000"}
  ]
}
```

Expected saved result: revision 1, selected mode/positions, bound membership rule ID, server updated time, `editable:true`. A successful review returns actual whole shares, exact monetary strings, `price_session_date:"2026-10-16"` for the current October 18 scenario, evidence and a preview hash. Successful confirmation returns version 1 and those frozen values. A later saved revision creates version 2; history marks version 1 `is_latest:false` without changing its evidence.

Errors retain `{error:{code,message,details},request_id}`. Relevant codes: 401 unauthenticated/session expired; 403 verification/CSRF; 404 portfolio/contest not found; 409 `draft_conflict`, `portfolio_locked`, `revision_submitted`, `idempotency_conflict`, `preview_changed`, `market_data_incomplete`; 422 invalid input, `holding_count`, `weight_total`, `position_limit`, `invalid_share_count`, `insufficient_capital`, `ineligible_instrument`; 503 missing/unreviewed calendar, fixture use disabled in production, dependency failure. No submission row or audit is committed on rejection.

## Development seed and API examples

The checked-in `data/portfolio_draft_fixture_v1.json` is a versioned five-equity/20%-each input for a default fixture contest. It is **not** auto-loaded as genuine activity. In the UI, **Use starter weights** populates only local unsaved inputs for the selected contest's rules. Save and submit deliberately; no fake portfolios/holdings are migrated from demo localStorage.

For API use, first register/verify, publish a suitable contest and join it using the Phase 2/4 instructions. With your own cookie jar and CSRF values (never put them in logs):

```bash
cd investiq-be
uv run --locked python -c 'from importlib.resources import files; print(files("investiq.data").joinpath("portfolio_draft_fixture_v1.json").read_text())' > /tmp/investiq-draft.json
# Review the IDs/weights against your contest. expected_revision must match your server draft.
curl -sS -b /tmp/investiq-cookies.txt "http://localhost:8080/api/v1/contests/$INVESTIQ_CONTEST_ID/portfolio/draft"
curl -sS -b /tmp/investiq-cookies.txt -X PUT "http://localhost:8080/api/v1/contests/$INVESTIQ_CONTEST_ID/portfolio/draft" \
  -H "X-CSRF-Token: $INVESTIQ_CSRF" -H 'Content-Type: application/json' \
  --data-binary @/tmp/investiq-draft.json
curl -sS -b /tmp/investiq-cookies.txt -X POST "http://localhost:8080/api/v1/contests/$INVESTIQ_CONTEST_ID/portfolio/preview" \
  -H "X-CSRF-Token: $INVESTIQ_CSRF" -H 'Content-Type: application/json' \
  -d '{"draft_revision":1}' -o /tmp/investiq-preview.json
```

Review the returned shares, source evidence, fee and cash. Copy its `draft_revision` and `preview_hash` into `/tmp/investiq-submit.json`, then use a fresh UUID from `uv run python -c 'import uuid; print(uuid.uuid4())'` as `$INVESTIQ_SUBMISSION_KEY`:

```bash
curl -sS -b /tmp/investiq-cookies.txt -X POST "http://localhost:8080/api/v1/contests/$INVESTIQ_CONTEST_ID/submissions" \
  -H "X-CSRF-Token: $INVESTIQ_CSRF" -H "Idempotency-Key: $INVESTIQ_SUBMISSION_KEY" \
  -H 'Content-Type: application/json' --data-binary @/tmp/investiq-submit.json
curl -sS -b /tmp/investiq-cookies.txt "http://localhost:8080/api/v1/contests/$INVESTIQ_CONTEST_ID/submissions?limit=20"
```

Retain the key/body for a network retry. Do not generate a new key to retry an unknown outcome, or overwrite a stale draft automatically. Angle-bracket UUIDs in documentation are explanatory; the seed file contains real fixture UUIDs. The fixture source covers only October 14–16; later dates can legitimately fail freshness. Never synthesize current prices to make submission pass.

## Run and exercise the frontend

Existing setup, container-only backend:

```bash
cd investiq-be
docker compose --profile app up -d --build --wait
```

Host development alternative (use one API process on port 8080):

```bash
cd investiq-be
# Existing .env; fresh setup: copy .env.example to .env first.
uv sync --locked
docker compose up -d --wait postgres redis mailpit
uv run --locked alembic upgrade head
uv run --locked python -m investiq.market_cli
uv run --locked uvicorn investiq.main:create_app --factory --host 127.0.0.1 --port 8080 --reload --no-access-log
```

Frontend in a separate terminal:

```bash
cd investiq-fe
npm ci
npm run dev
```

Open http://localhost:5173, sign in and verify through local http://localhost:8025. Join a published contest. Open its **Open contest portfolio** link, the **Portfolio** link in My Contests, or the sidebar Portfolio contest chooser. Pick eligible stocks, choose quantity/weight mode, enter allocations, **Save draft → Review saved draft → Confirm contest submission**. Submission history survives reload. **Use reviewed quantities** copies the server-converted shares into an unsaved quantity draft; save/review it before a new submission.

The existing shell/styles remain. Catalogue search, sector/cap filters operate on the bounded fixture catalogue and frozen universe. Prices show source/freshness; stale/missing prices disable adding those instruments. A quote-display failure keeps draft/history accessible but never creates a fallback price. Validation and accounting happen on the server; UI formatting and planning inputs are not trusted. Draft writes use revision checks, keep local input after conflict, and offer explicit reload. Account/route generation checks discard obsolete responses; no real account portfolios go into localStorage. The signed-out builder remains a separate, labelled practice preview, never uploaded on sign-in. Time-related status comes from the API, with IST display.

## Verify and next phase

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

Integration tests use disposable real PostgreSQL, Redis and local SMTP; no SQLite replacement or real email delivery. Tests cover precision/rounding, fee-reserved weights, quantity mode/custom rules, positive/distinct inputs, holdings/position/capital limits, empty drafts, updated corporate-action constraints, ownership/CSRF/verification, preview changes, missing/future/unavailable price evidence, exact lock boundaries, conflicting tabs, same-key and different-key concurrent submissions, immutable rows, incomplete-snapshot rollback and retry after lock. Browser tests cover saved state/reload, conversion without a second fee, immutable version history, conflict handling, price API failure and contest isolation.

Phase 6 will value the latest accepted snapshot at a common timestamp, compute benchmark-relative results, and add jobs, simulated contest result finalization and rankings. Phase 5 does not claim to provide those results, live quotes, trading, prizes, coins or XP. Production market/fixture operations remain disabled pending the approved market provider.

Phase 5 verification: **78 backend tests and 10 Chromium browser tests passed**. Ruff lint/format, strict mypy, uv lock validation, Alembic model comparison/offline SQL and a disposable PostgreSQL downgrade/upgrade round trip passed. Frontend syntax/build and the rebuilt Docker migration/seed/API stack passed. Readiness reports PostgreSQL/Redis OK on revision `0005_portfolios`. The wheel includes analytics and the versioned starter input; disposable test databases were removed. Browser regressions also cover switching portfolios during a pending save.
