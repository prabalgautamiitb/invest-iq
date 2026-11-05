# Shared virtual wallet

Every user starts with ₹10,00,000 of virtual INR. This balance is separate from
reward coins, subscription access, and real money. There are no deposits,
withdrawals, top-ups, billing, or external financial settlements.

## Lifecycle

1. Registration creates a wallet and one opening ledger credit in the same
   database transaction as the user.
2. Joining a new contest reserves its full frozen capital, not just allocated
   equity. Joining requires sufficient **available** funds. Invitations use the
   same check. Hosting does not reserve funds unless the host also joins.
3. A reservation initially has its starting capital as current value. Saving or
   replacing a portfolio submission does not reserve funds again.
4. Each successful published daily valuation updates the reservation to the
   portfolio's exact total value, including residual cash and its simulated fee.
   A blocked valuation leaves the previous value visible. Unrealized profits
   cannot fund another contest.
5. Finalization credits the final portfolio value back to available funds and
   closes the reservation. An entry without a confirmed submission receives its
   reserved capital back once the contest finalizes.
6. Cancelling a contest releases reserved principal. Existing cancellation rules
   still apply: cancellation is allowed only before entries lock.

Example: reserving ₹4,00,000 leaves ₹6,00,000 available. If the active portfolio is
valued at ₹4,20,000, total wallet value is ₹10,20,000, with ₹6,00,000 available.
When final results are published, the ₹4,20,000 returns to available funds.

## Accounting

```text
Total wallet value = available balance + latest value in active wallet-funded contests
Wallet P&L        = total wallet value - ₹10,00,000
```

Decimal accounting retains four decimal places, matching persisted portfolio
valuations. The interface displays rupees to two decimal places. A user may join
a contest whose capital equals the available balance. Client balances are never
authoritative; the server checks and reserves funds atomically.

`virtual_wallets` stores available funds. `wallet_positions` links each new funded
membership to its principal, latest valuation, and release status. `wallet_entries`
records opening credits, reservations, final returns, cancellation refunds, and
unsubmitted-entry refunds, with the resulting available balance.

Contest joins hold the existing user/session/contest locks, then lock the wallet.
Valuation and cancellation hold the contest lock and acquire affected wallets in
user-ID order. Available funds, membership, reservation, ledger changes, and final
results commit or roll back together. Rejoining an existing membership is a no-op;
unique event keys and finalization guards prevent duplicate debits or credits.
Database checks prohibit negative balances. Ledger rows and released funding
evidence cannot be rewritten or deleted through ordinary SQL updates.

## Existing accounts and contests

Migration `0016_virtual_wallet` gives each existing user a ₹10,00,000 opening
balance. **Existing memberships remain pre-wallet entries.** Their submissions,
results, and standings are preserved, but their returns do not debit or credit
the wallet. Rejoining an old membership does not retroactively fund it. Only
memberships created after rollout receive wallet positions.

This policy avoids negative opening balances for users who previously joined
several independently funded contests. The wallet page discloses the number of
pre-wallet contests; contest views label the funding source.

## API and interface

Authenticated `GET /api/v1/me/wallet` returns only the current user's wallet:

- Opening capital, available funds, reserved principal, invested value, total
  value, P&L, and return percentage.
- Active positions with contest links, the latest valued date, and current value.
- The latest 30 available-balance transactions and pre-wallet membership count.

The endpoint revalidates the current session. No route accepts a requested wallet
owner, balance, credit, debit, or portfolio valuation from clients. Anonymous
requests receive 401. Rewards continue using their separate coin wallet.

Contest responses expose the viewer's own `wallet_available` and the viewer's own
membership's `wallet_backed` flag. New joins with insufficient funds return HTTP
409 with code `insufficient_wallet_balance`; they consume no seat or invitation.

Learners can open `/#/wallet` from the sidebar, profile, or home summary. The
interface refreshes while visible and after contest actions, shows funding
requirements before entry, and confirms reservations for joins and invitations.

The header wallet shortcut shows **available funds**, while Home shows the
**overall portfolio value** instead of a duplicate wallet card. Authenticated
`GET /api/v1/me/portfolio` supplies that value, net P&L, return on the original
₹10,00,000, and the aggregate daily history. The history begins with the opening
grant, retains completed contest P&L, and carries each funded contest's latest
published P&L forward. Multiple contest valuations on one market day produce one
overall point. Reservations, refunds, and releasing final value do not themselves
create performance. Unvalued entries retain principal until valuation. Pre-wallet
memberships are excluded from both this total and its history.

Home has no contest selector: its portfolio graph covers all wallet-funded
activity and its learning analysis uses all saved contest results, including
pre-wallet history. Strengths and improvement areas use the existing daily
coach overview, rather than a single contest report. Individual contest cards
link to their own values, allocation charts, benchmarks, and AI reports.

## Rollout and operation

Apply the migration before starting the new API and job code:

```bash
# From investiq-be, against the intended environment
uv run --locked alembic upgrade head
```

For the complete local Docker stack:

```bash
docker compose --profile app up -d --build --wait
```

Hosted deployments must migrate the production database and then deploy both the
API and daily workflow code from the same revision. Do not run the command against
production without the privately configured production environment. Readiness
requires schema `0016_virtual_wallet`. Existing published prices and results are
not recalculated during migration.

The downgrade refuses to discard a wallet with contest funding history. Back up
the database before a hosted release; reversing an active wallet rollout needs a
deliberate data-preservation plan rather than dropping its tables.

Tests cover opening grants, account isolation, simultaneous joins, insufficient
funds, retries, invitations, cancellation, final gains and losses, missing
submissions, immutable evidence, legacy entries, and migration backfill. The
browser test covers the entry/refund journey and mobile layouts.
