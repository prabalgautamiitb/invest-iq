# Yahoo end-of-day prices

The optional Yahoo provider uses `yfinance` directly, rather than the third-party
hosted Indian-Stock-Market-API. Prices are downloaded; the catalogue is curated.
This integration does not grant data-use rights. The existing production
market-data guard remains in place.

## Docker setup

Set `INVESTIQ_MARKET_DATA_MODE=yahoo` in `investiq-be/.env`, then run from that folder:

```sh
docker compose --profile app up -d --build
docker compose exec -T api python -m investiq.market_cli --yahoo
```

The app profile applies migration `0013_yahoo_eod`, initializes the catalogues and
starts the API, worker and Beat. The import command loads recent completed
sessions immediately. The worker checks every five minutes for a missing session.
`GET /api/v1/market/status` reports the active source, latest successful session,
import time and latest failed-session code. Import retries retain saved prices.

For Python processes outside Docker:

```sh
uv sync --locked
uv run alembic upgrade head
uv run python -m investiq.market_cli --public-contests
uv run python -m investiq.market_cli --yahoo
```

Restart the API, worker and Beat after changing the source setting. Without
worker/Beat, run the import command after market close. For a bounded backfill:

```sh
uv run python -m investiq.market_cli --yahoo --start 2026-10-19 --end 2026-10-23
```

Explicit imports accept up to 32 calendar days. Only completed, reviewed sessions
are imported. Data is available from its actual retrieval time, never backdated
for historical portfolio submissions.

## Product behavior

- Home shows Nifty 50 daily opening/closing levels and open-to-close movement.
- New contests use all 50 constituents from the official NSE snapshot retrieved
  on October 25, 2026, plus the Nifty 50 benchmark (`^NSEI`).
- Contest, quote, portfolio, performance and leaderboard responses identify source.
- Values and standings use saved daily closes. All holdings and money are virtual.
- Missing prices stay unavailable; synthetic prices are never a fallback for Yahoo.

The official constituent CSV and its checksum are saved alongside
`yahoo_catalogue_v2.json`. Names, sectors and Yahoo ticker mappings are reviewed
metadata. Membership is a dated snapshot rather than a live constituent feed.
Refresh the snapshot and version the dataset when the index is reconstituted.

Expanded imports use `yahoo-eod-v2`. Existing `yahoo-eod-v1` prices remain readable,
including historical cutoffs. Readers choose one complete preferred batch for a
session, never a mix of versions. Wipro is retained as a legacy background pricing
instrument for older portfolios, but does not appear in new Nifty 50 selection.
Existing published contests keep their frozen eligible stocks; create a new contest
to offer the full 50-stock universe. New batches contain 52 prices: 50 constituents,
the index, and the legacy Wipro price. The default stock catalogue shows exactly 50.
`GET /instruments?include_legacy=true` also serves legacy holdings to portfolio editors.

## Source separation and valuation

A contest's frozen benchmark determines its source. Yahoo and fixture instruments
have distinct IDs even when their symbols match. Draft revisions cannot switch
source. Existing portfolios, submissions and results are preserved; synthetic
contests continue to use their original source after the regular app switches.

Portfolio confirmation uses the latest complete available closing session,
including the benchmark. It does not simulate execution at the next morning's
open. Daily value is shares at that session's closing prices plus residual cash.
Starting capital, whole-share rounding and the initial simulated fee keep their
existing rules. Index open-to-close movement is context, not portfolio return.

Imports request daily bars with `auto_adjust=False` and `actions=True`. Dividends
are not reinvested: portfolios use price returns, not total returns. A reported
split blocks that session's batch pending operator review. Automatic split,
merger and demerger accounting is not implemented.

Our availability policy starts at 18:00 IST; Yahoo availability is not guaranteed
at that instant. Every instrument must have exactly one bar for the requested
session, with finite positive open and close. Missing/invalid/duplicate/wrong-date
bars publish no prices. Successful batches are immutable; concurrent retries
retain the first stored publication. Scans include missed days of active Yahoo
contests and skip sessions already imported.

The reviewed exchange calendar covers 2026. Yahoo mode removes the fixed fixture
price-window restriction but does not create future calendars or invent special
sessions. The manual sandbox always uses its October 14–16 fixture scenario,
regardless of the regular application's mode.

## Verification

```sh
uv run pytest tests/test_yahoo_market.py -q
```

Tests inject provider responses without external requests. They cover dated bars,
missing data, corporate actions, idempotent imports, catch-up, publication beyond
the fixture window, source isolation, submissions, valuations, final standings,
and continued valuation of existing synthetic portfolios.
