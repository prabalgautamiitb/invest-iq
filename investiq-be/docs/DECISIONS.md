# Architecture decision log

## ADR 001 — modular monolith and incremental delivery

Accepted: one Python application, one PostgreSQL database, Redis infrastructure, colocated with the existing frontend. Phases 0–3 are implemented. Routes translate HTTP, schemas validate DTOs, services own reusable rules and transactions, persistence models express constraints, adapters isolate providers. Analytics never delegate arithmetic to an LLM. No generic repository layer, extra database or microservice is introduced.

## ADR 002 — sessions and CSRF (decided before Phase 2 implementation)

Use random opaque server-side sessions, with only a hash of each secret persisted. A browser receives an HttpOnly, SameSite=Lax cookie scoped to `/`; use Secure and the `__Host-` prefix in HTTPS production. Local HTTP development uses an explicitly different non-Secure cookie name. Session expiry, logout and revocation are server-authoritative; do not put tokens in localStorage.

SameSite and CORS are insufficient on their own. Before cookie authentication goes live, issue an unpredictable session-bound CSRF token and require `X-CSRF-Token` for state-changing requests, including pre-authentication login/registration. Validate Origin against the configured allowlist, with a documented same-origin fallback for legitimate clients. Expose the CSRF token through a dedicated authenticated/pre-auth bootstrap endpoint, never the session cookie. Rotate sessions on login and privilege changes; invalidate them after recovery. Add server-side rate limiting for sensitive routes and derive user identity/role from sessions. Phase 2 implements this policy; public probes, approved question text and anonymous CSRF bootstrap are available before sign-in.

## ADR 003 — async database and explicit transactions

Use SQLAlchemy 2.x with asyncpg, one engine per application process and one session per request. Lifespan closes pools and Redis connections. Services explicitly begin and commit transactions; dependencies close/roll back unfinished work. Use named database constraints and versioned Alembic migrations. Do not call `metadata.create_all` at runtime. Readiness checks the expected migration revision, not just TCP connectivity.

## ADR 004 — errors and observability

Domain/API errors use `{error: {code, message, details}, request_id}`. Validation details retain only location/type, excluding raw input. `X-Request-ID` is generated server-side for every response; untrusted incoming IDs are ignored. Application request logs are JSON and omit bodies, headers, URLs/query strings, DSNs and raw exception text. Disable Uvicorn access logging in documented commands to avoid logging recovery-token URLs later. Operational readiness responses deliberately use a stable health schema at both HTTP 200 and 503. Production monitoring, metrics export and secure error tracing arrive in Phase 12.

## ADR 005 — stable financial and market policies

Use UUID domain keys, TIMESTAMPTZ UTC, Python Decimal and NUMERIC. Currency rounds half-up to two decimals at accounting boundaries; prices/holdings use explicitly chosen per-domain precision rather than binary floats. Coins/XP are integer units and immutable events. Market data must retain provenance and observation/ingestion times, with deterministic fixtures isolated from production. Choose a production Indian-equity source only after checking licenses, coverage and freshness requirements in Phase 3.

## ADR 006 — deferred execution frameworks

Redis connectivity exists now. Celery workers/scheduling start with actual valuation jobs. LangChain integrations, typed LangGraph workflows and PostgreSQL checkpoints start with report evidence and authorization in Phase 10. pgvector and versioned document retrieval start in Phase 11. Core user journeys must work without an LLM key. Dependency versions for these later phases will be verified at implementation time rather than locked speculatively.

## ADR 007 — account/demo separation and local email

Accepted: frontend identity is fetched from server cookies and retained in memory, separate from `investiq-demo-v1`. Account writes never upload the demo state object. Version-1 onboarding questions are seeded from an immutable migration snapshot, with answer-option allowlists and server-derived classifications. All new users have no seeded financial/learning/reward activity.

Use a typed SMTP adapter and Mailpit for local verification and recovery. Tokens are hashed in PostgreSQL and placed in email URL fragments; the UI consumes and removes the fragment before rendering. Delivery failures create sanitized audit events and a fresh link can be requested; durable background email delivery is deferred explicitly rather than represented by a fake provider.

Anonymous sessions last one hour; authenticated sessions default to seven days with a service-enforced maximum of 20 active sessions. Session collection endpoints return that bounded set without pagination. Operator role changes require a verified email for admin assignment and revoke existing sessions.

## ADR 008 — synthetic market evidence and reviewed calendar

Accepted: prices remain fixed synthetic EOD fixtures with source/version, observation, publication and ingestion timestamps. No live/EOD production feed is selected; official NSE licensing and current SEBI educational-data rules need to be accounted for first. Production market routes and fixture initialization fail closed.

Use stable UUID instrument identity, a shared instrument table for equities/benchmark indices, explicit cap/sector metadata and a bounded reviewed NSE calendar. Publication cutoff is an explicit fixture policy. Unsupported special sessions and corporate actions block eligibility. Never infer uncovered calendar dates or relabel old fixture prices as current.

Ingestion validates the exact batch universe and commits all price evidence with its run atomically. Unique batch identity and row locks arbitrate retries; changed published content is rejected. The canonical hash normalizes point order, UTC and decimal scale. Quotes can expose stale/missing evidence for inspection, while strict requests reject it. Future financial services must use a server-chosen common timestamp.

## ADR 009 — catalogue pagination and preview integration

Accepted: keyset cursors bind to filters/sort/local date, with explicit C collation and UUID tie-breakers. Small sector lookups and date-bounded calendar ranges use the same envelope with a null next cursor. Market data is public reference information, never user-owned authorization data.

Frontend prices are decimal-formatted strings, fetched from the API and shown with synthetic/source/time labels. Error paths never fall back to browser prices. Existing local allocation previews remain separate from account/server holdings; Phase 5 will replace them with accepted Decimal-based drafts/submissions. Redis price caching is deferred; each quote request checks database evidence against the calendar.

## Phase 4 — Contest rules and access

- A contest starts as an owner-only draft. Revisions append immutable rule versions; publishing freezes metadata, calendar schedule, capital, eligible universe and policies. PostgreSQL triggers also reject edits/deletions of versions or published detail changes. Historical universes retain instrument FKs.
- Time-driven status is a deterministic projection in service mutations, responses and SQL filtering. This closes entry exactly at the deadline without relying on a worker. Reads do not write. Completed status is reserved for Phase 6 simulation result finalization; end-of-contest projects `settling`, meaning results are being calculated.
- Start/end align with reviewed exchange sessions, lock is strictly before start, unknown/special sessions and overlapping instrument exclusions fail closed. Synthetic fixtures remain development/test only.
- Explicit immutable policy: last published EOD before lock, whole shares rounded down, residual cash allowed, simulated cost once on submitted notional, no in-contest trades. Phase 5 implements execution/validation; Phase 4 only records rules and membership.
- Invitations are addressed in-app records, scoped to a verified matching email, with no bearer secrets or external delivery. Revocation/decline/expiry cannot be undone by retry. No unverified account receives private invitation information.
- User → session → contest → invitation lock order serializes seat allocation and invitation changes. Unique contest/user membership and contest/rule composite FK protect identity and frozen rules. Creation uses an owner-scoped UUID Idempotency-Key; mismatched retries fail.
- Frontend contest screens use API data and account-scoped memory, never fixture ranks/returns or localStorage activity. Optional seed requires an existing verified owner and creates one private draft with zero members. No fake users, prizes, XP or coins are seeded.

## Phase 5 — Portfolio drafts and immutable submissions

- Membership owns one current draft, with server revision checks and incomplete drafts allowed. No user IDs, prices, fees or returns are accepted from the client. Authorization and deadline checks run in the same service transaction as the write.
- Freeze the latest complete published EOD session available at submission, strictly before entry close, including a common-batch benchmark. No lock-time repricing or stale-day fallback. Preserve copied equity/benchmark prices and provenance plus source snapshot references.
- All calculations use Decimal (precision 50). Weights apply to capital after reserving the simulated aggregate fee, rounded down to paise; shares round down to integers. Notional and residual cash retain four places; the one aggregate fee rounds half-up to paise. Residual cash is allowed. Position limits use actual notional divided by starting capital.
- Submission requires a server review hash, UUID idempotency key and saved draft revision. Recheck the same evidence during confirmation; changing evidence requires review. Same-key retries return the accepted resource, including after lock; different keys cannot submit one revision twice.
- New successful versions supersede earlier versions without editing them or accumulating old virtual fees. The highest accepted version is authoritative at lock; newer unsent drafts are ignored for eventual valuation. No in-contest trades or real orders.
- PostgreSQL allows atomic unsealed construction → sealing, rejects header/holding edits or appending afterwards, and defers a completeness/aggregate check until commit. Unique/composite FKs provide additional membership/version integrity.
- Frontend real contest portfolios use account/route-scoped memory and server persistence. Signed-out previews remain separate. Starter data only populates unsaved fields or an explicit API input; no genuine activity is automatically fabricated.

## Simulation-only contest completion

InvestIQ is an educational simulation. Phase 6 calculates virtual portfolio values, simulated returns, benchmark comparisons and final rankings, then marks the contest completed. There are no real trades, payments, payouts, funds transfers or financial settlement. Capital, residual cash and fees are simulation accounting only. The existing `settling` API status is a compatibility name for calculating/finalizing contest results. Future implementation and UI wording should call this **contest result finalization**.

## Phase 6 — Simulated daily valuation and background work

- Use the latest sealed accepted submission; never an unsent draft. Value everyone at one reviewed/published NSE session close. Require all selected equities and benchmark from one complete fixture batch, with current eligibility/currency/classification and corporate-action checks. Missing data blocks the whole day without stale-day substitution.
- Process every due contest session in order. Decimal calculations include residual cash and the already-paid simulated fee exactly once. Persist copied source evidence, metrics, daily peak/drawdown, deterministic ranks and a versioned evidence hash. HHI describes equity concentration; cash is excluded from HHI.
- Finalization is simulation-only. Last-session success, a unique contest finalization, completed status and one audit event commit atomically. No payments, real trades, fulfillment, coins or XP. Successful results cannot be overwritten by retries or later source corrections.
- Rank by exact net P&L for the shared starting capital, then lower eight-place drawdown, earlier accepted submission time and entry UUID. No global ranking across different contest formats. Display names follow current public-profile preference; holdings/performance details remain owner-only.
- Celery/Beat perform periodic reconciliation over durable PostgreSQL work conditions. Lost broker ticks are recovered on subsequent scans; successful transactions are idempotent. One Beat, separate Redis DB/queue, JSON tasks with no user data, late acknowledgement, bounded retries and time limits. Fresh async pools per task avoid cross-event-loop/fork connection reuse. This workflow needs no duplicate outbox; future reward issuance is a separate ledger/outbox phase.
- Pin Celery 5.6.3 + stable Kombu 5.6.2 + compatible Redis client 6.4.0. The previous Redis client led the resolver toward a prerelease Kombu transport. Redis server 8 remains unchanged; full identity/portfolio regressions verify the compatible client.
- Replace signed-in dashboard and contest leaderboards with actual server results. Pending/stale snapshots stay explicit. Historical fixture tests use disposable databases and test-only clocks; normal API/container code provides no time-travel endpoint or fake current prices.

## Phase 7 — Learning

- Stable lesson identities with immutable content/question versions; attempts keep their exact version. Public reads omit answer keys. New attempts use the current version, while exact retries remain valid after publication changes.
- Passing every question completes a lesson once. Award 25 integer XP once per stable lesson, including across versions. Serialize writes using the shared user→session lock; preserve attempt/answer/completion/XP evidence in one transaction with unique and deferred database constraints.
- IST activity days record first completions only. Today/yesterday grace defines current streak; retain longest streak and historical achievements. Retakes do not create streak days, XP multipliers or coins.
- Development-only curriculum seed creates content, never progress or users. Academy and signed-in profiles show actual learning data, and guest localStorage is never uploaded. No new packages or workers are needed.


## Platform public contests (Phases 4–6 extension)

- Distinguish immutable community/platform organizer identity. Existing contests remain community contests; platform contests must be public and are managed by current verified admins rather than a single creator. Keep the creator FK for provenance and return separate `can_manage` capabilities.
- Reuse the existing public discovery, membership, frozen rules, portfolio submissions and common EOD standings. No automatic memberships, submissions or results. Regular users cannot claim the platform organizer type.
- Prevent publication of platform contests outside configured fixed scenario coverage or without current common submission prices. Extend development prices through November 6, 2026 using a separate immutable file/version, released only at reviewed session publication times. Do not generate current-date prices or rewrite historical submissions/successful valuations. Production fixtures remain disabled.
- Reuse existing operator role provisioning; no automatic admin promotion or public role-management endpoint. Browser-only admin helpers are confined to the disposable test harness.


## Phase 8 — Virtual coin ledger and sandbox rewards

- Credit exactly 50 integer coins per stable first-completion lesson source, including uncredited genuine historical completions. No demo balances, signup grants, contest prizes, arbitrary credit APIs or monetary value. Quiz/XP/coin writes share the user-locked transaction; background recovery replays durable source conditions rather than blind award messages.
- Keep immutable ledger entries and source FKs, account totals verified against that ledger, consecutive running balances, nonnegative balances and lifetime-earned tiers. Spending does not reduce tier. Recovery is bounded and idempotent under concurrent callers.
- Redemption locks user/session/account/item/inventory, copies server terms, debits once under a UUID key and consumes one unit atomically. PostgreSQL deferred evidence and stock constraints reject partial writes; refunds/adjustments require future explicit event types.
- Development catalogue and fulfillment are sandbox only, with no entitlements, shipping/address data, gift codes or provider actions. Seed definitions preserve consumed stock and inactive flags. Frontend confirmations retry with stable keys; private wallet/history caches reload after navigation and clear at account changes.


## Phase 9 community

- Public groups only for this slice; explicit membership gates group post/reply creation. Content remains public after leaving. Private groups and invitations require their own visibility model later.
- Resolve names from current public-profile preferences. Do not expose account/email IDs, member identities, individual votes, reporters or private saves in public DTOs. Old local community activity is never imported or seeded.
- Freeze post/reply text and poll options in PostgreSQL; soft-delete or moderate visibility rather than rewriting evidence. Store 2–6 options on the immutable poll parent; guard option indexes, expiry and final unique votes with database triggers.
- Serialize each writer through the existing user/session locks, with content locks for polling/moderation. Bind post/reply retry keys to normalized payload and parent; use set/clear interaction semantics and a separate configurable community Redis bucket (60 writes/minute by default).
- Record hide/restore/dismiss reasons and audit events transactionally. Recheck current admin role on every request; terminal author deletion cannot be restored. Paginate feeds, replies, groups and report reviews.
- Keep community participation separate from XP/coins/contest ratings; no fabricated reputation, trending or activity counters. Next work is deterministic AI-coach evidence and workflow integration.


## Phase 10 AI coach

- Develop against the already-installed local Ollama `llama3.1:8b`; add a separate Gemini adapter with backend-only model/key configuration and no automatic fallback. Do not require an LLM for accounting, deterministic evidence, journals or other product flows.
- Use LangChain native JSON-schema adapters and a typed LangGraph, with persistent PostgreSQL checkpoints in a separate schema initialized explicitly by the pinned saver's setup. Thread IDs are derived internally from owner/job IDs; no public thread or tool-execution interface is exposed.
- Freeze an own-user successful valuation and published lesson versions at request time. Build every displayed claim deterministically; let the model select observations, review points and educational priorities through validated reference IDs. Reject unsupported/duplicate/wrong-category citations. Do not infer motives, trading history, causal mistakes or a suitability score.
- Store durable work in PostgreSQL and reuse the existing worker/Beat. Serialize AI calls with an advisory lock, bound attempts/leases/timeouts, resume checkpoints after failure, and persist one report/success/audit transaction. Keep provider calls out of accounting and reward transactions.
- Deduplicate normalized retry keys and completed/current-source work. After terminal failure, a new explicit key can create the next immutable generation; transport retries retain the original key. Revalidate ownership/account state before model use and persistence.
- Keep account identity, quiz answers, community and private journal text out of model input. Persist only validated plans/reports and safe token/latency/error metadata. Local API-fee estimates are zero excluding hardware; unknown Gemini costs remain null.
- Retrieve a bounded set of published Academy versions now; approved-document ingestion, semantic retrieval, educational chat and pgvector belong to Phase 11.
