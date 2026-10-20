# Phase 8 — Virtual coins and sandbox rewards

## Goal and decisions

Add auditable integer coin earnings, tiers, a catalogue with inventory, idempotent redemption and private history. Phases 1–7 plus the public-contest/results-information extension are prerequisites. This phase uses the existing locked Python stack; no packages or external fulfillment services are added.

- A genuine first-time lesson completion earns **50 virtual coins**, policy `lesson-coins-v1`. Quiz retakes, repeated HTTP requests and new versions of the same stable lesson earn no extra coins. Failed quizzes earn none. XP remains a separate counter.
- Existing genuine completion records are eligible once. The startup CLI and periodic worker reconcile missing credit events; browser demo progress/balances are never imported. There are no signup credits, editable-balance endpoints, contest coin prizes, multipliers or cash conversion.
- Bronze starts at 0 lifetime earned coins, Silver at 100, Gold at 250 and Platinum at 500. Spending reduces available balance and leaves lifetime earnings/tier intact. The small six-lesson curriculum currently supports 300 earned coins; additional curriculum is required for higher thresholds.
- Seed six explicitly sandbox catalogue items costing 50–250 coins. Each redemption consumes one inventory unit and records `sandbox_confirmed`. Vouchers do not unlock avatars, lessons or paid features; merchandise is not shipped. No gift codes, addresses, payments, subscriptions, bookings, emails or provider fulfillment are involved.
- Confirmed redemptions and ledger entries are immutable. Refund/cancellation/adjustment events, inventory restocking and catalogue administration need a future explicit policy and API; this slice does not silently edit historical records.

`RewardsService` owns the transaction boundary, analogous to a transactional Spring application service. Learning calls a small shared credit function using its existing SQLAlchemy transaction; no generic repository layer or background dependency is introduced on the quiz submission path.

## Schema and ownership

Migration **`0009_rewards`** adds six tables. UUID identifies records; coin quantities use integer/BIGINT units, never monetary NUMERIC or floating point. Event timestamps use timezone-aware UTC. Catalogue/tier definitions belong to the platform; accounts, ledger entries and redemptions belong to their `user_id`.

| Table | Columns and purpose | Keys, constraints, indexes and deletion |
| --- | --- | --- |
| `coin_accounts` | UUID user_id; BIGINT balance, lifetime_earned, entry_count | PK/FK user RESTRICT; balance ≥0, lifetime_earned ≥balance, entry_count ≥0. Deferred checks require exact ledger totals; deletion blocked |
| `reward_tiers` | UUID id; slug varchar(40), name varchar(80), BIGINT minimum_earned | PK; unique slug and threshold; threshold ≥0; immutable |
| `reward_items` | UUID id; slug varchar(80), name varchar(160), description varchar(1000), category varchar(20), integer cost/version, boolean active, mode varchar(10) | Unique slug; category indexed and limited to digital/learning/merchandise; cost 1–1,000,000; version >0; mode must be sandbox. Published terms immutable; active may be toggled |
| `reward_inventory` | UUID item_id; integer capacity/remaining | PK/FK item RESTRICT; capacity 0–100,000, remaining 0–capacity; capacity immutable. Deferred equality: remaining = capacity − confirmed redemption count; deletion blocked |
| `reward_redemptions` | UUID id/user_id/item_id/idempotency_key; request_hash varchar(64); item_version, copied item_name/cost, BIGINT balance_after, status varchar(24), created_at | Unique user/key and id/user; account/item FKs RESTRICT and indexed; created_at indexed; positive bounded cost/version, nonnegative balance; status only sandbox_confirmed; immutable |
| `coin_ledger` | UUID id/user_id/lesson_id?/redemption_id?; BIGINT sequence/delta/balance_after; kind varchar(24), policy_version varchar(40), created_at | Unique user/sequence, user/lesson and redemption_id; account FK RESTRICT and user index; composite source FKs to the same user's completion or redemption; immutable; strict source/kind/policy/amount checks |

Existing `learning_completions` is the source for earned coin events; it is not recreated.

Database rules provide independent protection:

- Lesson credit must reference `(user_id, lesson_id)` in genuine completions, use exactly +50, and have no redemption source. The unique key prevents a second credit for that lesson across all policy retries and quiz versions.
- Redemption debit must reference `(redemption_id, user_id)`, have a negative integer delta, and have no lesson source. Exactly one debit must match each redemption's copied cost and recorded balance.
- Ledger insertion locks the account and requires the next consecutive sequence and exact running balance. Every account total must equal the sum of ledger deltas, positive deltas and row count at commit. Direct edits cannot create an unbacked balance.
- Inventory and redemption/debit checks are deferred until commit, allowing service writes to complete atomically. Partial inventory consumption, redemption records without debits, or debits without matching records cannot commit.
- Foreign keys use RESTRICT, and triggers reject deletion/mutation of ledger/redemption/tier evidence. Catalogue content/capacity is frozen; re-seeding does not refill stock or reactivate an item.

## Transactions, concurrency and retries

**Lesson completion:** retain the existing user→session locks and verified-account checks. After persisting the first completion, credit its coin event and update the account in the same transaction as quiz answers, XP, streaks and achievements. A failure rolls the whole submission back; retrying its original quiz key remains safe. The credit helper also recovers any older uncredited completions for the same user, capped at 100 events per transaction.

**Historical/retry recovery:** a periodic reconciliation selects at most 100 active verified users with durable uncredited completions, locks each user in a separate transaction and credits up to 100 missing sources. Startup runs the same reconciliation after seeding definitions. Repeated/concurrent scans cannot issue duplicate credits. This reuses the existing 60-second scheduled scan; it does not need an extra Beat instance, queue or outbox because completion evidence itself is the durable work source. Inactive/unverified users are skipped.

**Redemption:** begin a transaction, lock user→session, and require verification. Look up `(user, Idempotency-Key)` before checking current stock/item availability. An identical item/version request returns the original immutable receipt, including its original balance-after value; changing the payload under that key returns 409. Reconcile missing genuine earnings, lock the account, then item and inventory. Validate active item/version, stock and sufficient balance. Copy server-owned terms, consume one unit, debit the account, insert redemption/ledger evidence and one audit event, then commit everything together. The server never accepts a client-selected price, balance, user, reward status or fulfillment instruction.

The user lock prevents concurrent overspending across sessions; item/inventory locks prevent different accounts from overselling the same last unit. Database uniqueness/deferred checks protect retries and partial writes as well.

## API contracts

| Method and path | Access and result |
| --- | --- |
| GET `/api/v1/rewards?query=…&category=digital&limit=20&cursor=…` | Public active catalogue page; case-insensitive name search, category filter, ascending C-collated name/UUID; remaining sandbox inventory |
| GET `/api/v1/rewards/{id}` | Public active item; 404 for absent/inactive item |
| GET `/api/v1/me/coins` | Own signed-in wallet: balance, lifetime_earned, tier/next_tier, coins_to_next_tier, lesson_completion_coins=50, mode=sandbox |
| GET `/api/v1/me/coins/ledger?limit=20&cursor=…` | Own private ledger, newest account sequence first |
| GET `/api/v1/me/redemptions?limit=20&cursor=…` | Own private history, newest timestamp/UUID first |
| POST `/api/v1/me/redemptions` | Verified account, cookie/CSRF/Origin checks, Redis rate limit, UUID Idempotency-Key; body `{item_id, item_version}`; immutable receipt, HTTP 201 |

Pages use limits 1–50 and opaque cursors bound to filters (catalogue) or authenticated account (histories). All endpoints use the existing sanitized error envelope. New accounts have zero coins, no ledger entries and no redemptions. Read-only wallet requests do not fabricate activity or a credit.

Example after identity registration, verification and login:

```bash
curl 'http://localhost:8080/api/v1/rewards?category=digital'
curl -b cookies.txt http://localhost:8080/api/v1/me/coins
curl -b cookies.txt -X POST http://localhost:8080/api/v1/me/redemptions \
  -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H 'Idempotency-Key: fd9742d7-6fb2-4192-b435-322b40ee273c' \
  -H 'Content-Type: application/json' \
  -d '{"item_id":"ITEM_UUID_FROM_CATALOGUE","item_version":1}'
curl -b cookies.txt http://localhost:8080/api/v1/me/redemptions
curl -b cookies.txt http://localhost:8080/api/v1/me/coins/ledger
```

After a first passing lesson, the wallet shows 50 available/lifetime coins, Bronze and 50 more to Silver. Redeeming the 50-coin practice avatar returns a receipt with `cost:50`, `balance_after:0`, `status:sandbox_confirmed`, the copied item name/version and recorded timestamp. The wallet then shows balance 0, lifetime 50; ledger entries are +50 and −50. Repeating the redemption key returns that same receipt without consuming another unit. A new request with insufficient funds returns 409.

Other failure cases: 401 for no authenticated account, 403 for missing verification/CSRF, 404 for absent/inactive items, 409 for sold out/version mismatch/idempotency conflict, 422 for forged/extra fields or wrong cursor, 429 for the rate limit. No shipping addresses or external fulfillment parameters are accepted.

## Frontend

The existing Rewards navigation now opens the connected catalogue, wallet/tier summary, item review/confirmation, private redemption history and coin ledger. Routes remain `/#/marketplace`, `/#/marketplace/{UUID}`, `/#/marketplace/history` and `/#/marketplace/ledger`; the rewards alias remains supported.

Guest users can browse the actual sandbox catalogue and must sign in to spend. Verified users review the cost and sandbox limitation, then confirm. Errors do not substitute sample coins, rewards or history. Confirmation retries keep the same request key and pending item/version in account-scoped memory; multiple clicks are disabled while processing. A recorded receipt remains visible if refreshing wallet/stock fails, with a request to refresh; stale balances are hidden. Leaving and returning to Rewards reloads the wallet, so newly completed lessons appear without a stale cached zero. Account/route generations discard obsolete private responses, and signing out clears private state. Real balances/history are never stored in localStorage or imported from the old browser demo.

## Files

- `models/rewards.py`, migration 0009: account/ledger, tiers, catalogue/inventory, immutable redemption evidence and database guards.
- `schemas/rewards.py`, `api/rewards.py`, `services/rewards.py`: typed contracts, authorization, integer accounting, recovery and atomic redemption.
- `services/learning.py`: same-transaction first-completion credit hook.
- `services/rewards_seed.py`, `rewards_cli.py`, `data/rewards_catalogue_v1.json`: validated development definitions and recovery of genuine earnings; no fabricated users/progress/balances/redemptions.
- `main.py`, migration registration/readiness, `jobs/valuation.py`, `compose.yaml`: service lifecycle, head revision, bounded reconciliation and initialization.
- Frontend reward controller, API helpers, app routing and Academy copy: connected flows and sandbox disclosures.
- Real PostgreSQL/Redis and Chromium tests; browser harness seeds definitions in its disposable database only.

## Start and verify

Full local stack:

```bash
cd investiq-be
docker compose --profile app up -d --build --wait
```

The app profile runs migrations, learning/reward definitions and genuine completion recovery before serving the API. Existing user/contest/portfolio data is preserved. For host development:

```bash
cd investiq-be
uv sync --locked
docker compose up -d --wait postgres redis mailpit
uv run --locked alembic upgrade head
uv run --locked python -m investiq.market_cli --public-contests
uv run --locked python -m investiq.learning_cli
uv run --locked python -m investiq.rewards_cli
uv run --locked uvicorn investiq.main:create_app --factory --reload --host 127.0.0.1 --port 8080 --no-access-log
```

Run the existing worker and one Beat for ongoing recovery/valuations, as described in Phase 6. Do not run host and container APIs on the same port or duplicate Beat.

Frontend:

```bash
cd investiq-fe
npm ci
npm run dev
```

Open http://localhost:5173/#/academy, complete a lesson, then visit http://localhost:5173/#/marketplace. Verify your email first (local inbox http://localhost:8025). Try the 50-coin sandbox voucher and inspect the ledger/history.

Checks:

```bash
cd investiq-be
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

Tests cover first-pass/retry awards, genuine-history recovery, atomic learning/coin rollback, tiers after spending, private pagination, CSRF/verification/forged fields, identical/conflicting keys, stock depletion, inactive/stale rewards, seed idempotency without refilling stock, forged account balances, immutable ledger rows and incomplete redemption evidence. Concurrent tests use real PostgreSQL locks for repeated and distinct same-account requests and two accounts competing for the last unit. Browser tests interrupt a committed redemption response and retry the confirmation without a second charge, interrupt the subsequent wallet refresh, and verify history/ledger/reload persistence, account isolation and guest/failure states.

Phase 8 verification: **104 backend tests and 19 Chromium browser tests passed**. Ruff lint/format, strict mypy, dependency lock validation, frontend syntax/build, Alembic model comparison/offline SQL, a disposable populated PostgreSQL rewards downgrade/upgrade with genuine-completion recovery, wheel packaging and the rebuilt hash-locked container stack passed. The API/worker are healthy, one Beat is running, and readiness reports PostgreSQL/Redis OK. Desktop/mobile catalogue inspection passed with six items and no mobile horizontal overflow.

## Limits and next phase

This is a virtual sandbox economy with a small development catalogue. It does not deliver real rewards, grant premium entitlements, award contest coins, support refunds/cash-out or expose catalogue/restocking administration. Published reward terms and inventory capacity are immutable; production catalogues/policies and correction workflows need a separate reviewed design. The development seed is disabled in production.

Next is Phase 9: community posts, comments, reactions, saves, polls, groups, moderation and privacy rules. Real settlements and fulfillment remain disabled.
