# Phase 3 implementation status

The backend now implements `/sectors`, `/instruments`, `/quotes` and `/market/sessions`. Portfolio catalogue, filters/pagination and price previews are connected through `src/api/market.js`. Every price is a labeled synthetic fixture with provenance/freshness. There is no live-feed adapter or server-side portfolio submission yet. The authoritative market contracts are in `../../investiq-be/docs/PHASE-3.md`; older proposals below remain historical notes.

# Phase 2 implementation status

Identity, onboarding, profile/settings, session controls and verification/recovery are connected to FastAPI in `../investiq-be`. The implemented contracts and security decisions are authoritative in `../../investiq-be/docs/PHASE-2.md`. The remaining domain helpers and the historical proposal below are still future integration points; do not treat demo financial/learning/reward records as real account data.

# InvestIQ backend integration guide

This archive contains the latest deployed frontend, including refined UI, page transitions, chart/score animations, and continuous background effects. It does **not** contain an implemented backend or existing API client.

## Current structure

| File | Purpose |
|---|---|
| `index.html` | Application entry point and stylesheet/script loading |
| `src/app.js` | Hash routing, page templates, mock data, form handlers, local state |
| `src/styles/style.css` | Base desktop/mobile layouts |
| `src/styles/polish.css` | Refined surfaces and interaction styles |
| `src/lib/motion.js` | Route reveals, chart drawing, score animation |
| `src/styles/ambient.css`, `src/lib/ambient.js` | Persistent background animation and pause control |

## Integration points in app.js

| Existing code | Replace or extend with backend behavior |
|---|---|
| `defaults` in `src/data/demo-data.js`; `state`, `save()` in `src/app.js` | Load authenticated user state from API; save individual resources rather than sending the entire state object |
| `authform` submit handler | Actual registration/login; replace validation-only navigation |
| `resetform` | Password reset request and token completion |
| `questions`, `onboard()`, `next` action | Store answers with a question-set version; calculate learning category server-side |
| `stocks`, `stockRows()` | Search instruments and fetch timestamped market quotes |
| `allocations`, `submit-portfolio`, `confirm-portfolio` | Save drafts; validate and snapshot contest submissions server-side |
| `contests`, `join`, `leaders()` | Contest configuration, entry, scheduling, valuation and leaderboard APIs |
| `courses`, `quiz`, `complete` | Content retrieval and authoritative quiz/lesson completion |
| `stats()`, `chart()`, `donut()`, `score()` | Replace illustrative/hardcoded values with consistent calculated results |
| `insights()`, `journalform` | AI review jobs and persisted decision journals |
| `postform`, `like`, `delete-post` | Paginated social feed, ownership checks and moderation |
| `profileform`, `reminders` | User preferences and optional notification delivery |
| `interest` | Optional persisted waitlist interest; marketplace currently has no purchasing flow |

## Suggested API contract (proposed, not implemented)

Use `/api/v1` as a prefix. All user-owned endpoints should derive the user from the authenticated session.

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register`, `/auth/login`, `/auth/logout` | Account/session lifecycle |
| POST | `/auth/password-reset/request`, `/auth/password-reset/complete` | Account recovery |
| GET / PATCH | `/me` | Profile and preferences |
| GET | `/onboarding/questions` | Versioned questions/options |
| PUT | `/me/onboarding` | Persist answer option IDs and return learning profile |
| GET | `/me/dashboard` | Learning score, lesson progress and contest summaries |
| GET | `/instruments?query=&sector=&cursor=` | Search/paginate eligible instruments |
| GET | `/quotes?instrumentIds=` | Quotes with timestamp and source |
| GET / PUT | `/me/portfolio/draft` | Fetch/update draft allocations |
| GET | `/contests`, `/contests/{id}` | Contest list and rules |
| POST | `/contests/{id}/entries` | Idempotent contest entry |
| POST | `/contests/{id}/submissions` | Immutable validated portfolio snapshot |
| GET | `/contests/{id}/leaderboard?cursor=` | Calculated leaderboard |
| GET | `/me/portfolios/{id}/performance` | Valuation history and benchmark comparison |
| GET | `/courses`, `/lessons/{id}` | Academy content |
| POST | `/lessons/{id}/attempts` | Grade answers and update completion |
| POST | `/me/portfolio-reviews` | Start an AI review job; return job ID |
| GET | `/me/portfolio-reviews/{id}` | Review status/result |
| GET / POST | `/me/journal` | Decision reflections |
| GET / POST | `/posts` | Feed and new posts |
| DELETE | `/posts/{id}` | Delete an owned post |
| PUT / DELETE | `/posts/{id}/helpful` | Idempotent helpful toggle |
| GET | `/me/notifications` | Notification list |

Example draft payload:

```json
{
  "version": 3,
  "allocations": [
    {"instrumentId": "INFY", "weightBps": 3000},
    {"instrumentId": "HDFCBANK", "weightBps": 3000},
    {"instrumentId": "ITC", "weightBps": 4000}
  ]
}
```

10,000 basis points represents 100%. Use integer weights and decimal monetary values; validate instrument eligibility, positive holdings, total allocation, holding caps, ownership, submission deadlines, and contest status on the server. Resolve market symbols to stable provider/exchange instrument IDs.

## Suggested database entities

Users; sessions; onboarding question versions and answers; user preferences; instruments; timestamped quotes; portfolio drafts and allocations; contests and rules; contest entries; immutable submissions and holdings; valuation snapshots; courses and lessons; quiz attempts and progress; review jobs/results; journals; posts and helpful votes; notifications.

Keep draft versions separate from submitted snapshots. Use uniqueness constraints for contest entry and helpful votes. Store UTC timestamps and display local time in the client. Derive returns and scores from authoritative data, not client-submitted values.

## Suggested build sequence

1. Authentication, PostgreSQL persistence, and `/me`.
2. Persist onboarding and user preferences.
3. Instrument catalogue and portfolio drafts; keep simulated quotes initially.
4. Contest lifecycle, submissions and valuation/leaderboard jobs.
5. Academy progress and server-graded quizzes.
6. AI reviews, journals and notifications.
7. Social features, administration and moderation.

A Java/Spring Boot backend can serve these endpoints and the built `dist` assets from the same origin, or run separately behind a reverse proxy. Add a small `api.js` client and loading/error states before connecting page handlers. Keep production credentials and AI/market-provider keys on the server. If using cookie sessions, implement appropriate CSRF handling; restrict cross-origin access to your frontend origin when deploying separately.

The current frontend uses `localStorage` key `investiq-demo-v1`. Retain a distinct demo mode while introducing real accounts; do not silently upload existing demo financial records as real account data. `investiq-ambient-motion` is a presentation preference and can stay browser-local.

## Development export

This export uses Vite and editable `src/` files. All seven illustrative data collections are in `src/data/demo-data.js`. `src/api/client.js` and `src/api/services.js` provide proposed request helpers; pages are not connected to them yet. Follow the root README for setup.

## Phase 4 connected flows

Contest explorer/detail, filters/search/sort/keyset pagination, configurable draft creation/revision, publication/cancellation, in-app invitations, joining and My Contests now use `/api/v1` through `contestApi`. See [backend Phase 4 contracts](../../investiq-be/docs/PHASE-4.md). The controller lives in `src/features/contests.js` and reuses the existing shell/styles. Old local contest creation and fake My Contests performance are removed from those flows. Guest public discovery also uses the API; failures render an error with retry and no demo fallback. Private responses live only in memory, scoped to account/request generation. Rules freeze on publish; joining is separate from the Phase 5 portfolio submission. My Contests offers Joined/Hosted views, contest switching and paginated invitations. Input/display times are explicitly IST; the API receives aware UTC timestamps.

Development browser verification: `npm run test:e2e` runs disposable migrated PostgreSQL and the local SMTP sink, with fixed market/contest clocks. Phase 4 tests exercise private cross-account invitation acceptance and persisted membership, draft revision/publication and discovery failures. No real invitations/emails are delivered externally.

## Phase 5 connected flows

`src/features/portfolio.js` serves signed-in `/portfolio/{contest UUID}` (and `/build/{UUID}` alias) and the signed-in Portfolio chooser. The signed-out `/portfolio` route remains a labelled local market-data practice preview. Contest details and My Contests link to actual membership portfolios. Each contest's draft/review/history lives in account/route-scoped memory and server persistence, never localStorage.

`portfolioApi` now uses `/contests/{id}/portfolio/draft` GET/PUT, `/portfolio/preview` POST and `/submissions` GET/POST. Saves include optimistic expected revision; confirmation includes the server preview hash and a UUID idempotency key retained for network retries. Earlier versions are shown as immutable history; price display failures never invent fallback quotes or erase saved drafts. Server quotes, allocations, costs and cash are decimal strings. Quantity-mode conversion copies the server-reviewed whole shares; mode changes require explicit new allocations. See [Phase 5 contracts and schema](../../investiq-be/docs/PHASE-5.md).

Browser coverage includes save/reload, reviews/submissions, quantity conversion, immutable history, conflicting tabs, quote failure and contest isolation. Phase 6 still owns simulated returns, valuation, rankings and contest result finalization.

## Phase 6 connected flows

`src/features/performance.js` connects the signed-in dashboard, `/leaderboard` contest chooser, `/leaderboard/{id}`, `/performance/{id}` and `/contest-history`. `performanceApi` reads the backend's immutable simulation snapshots, current/final/pending metadata, owner-only metrics/contributions, ranks and actual dashboard/history aggregates. My Contests displays genuine snapshot values/ranks and links to performance/leaderboards. Signed-in dashboard fixture counts/returns/AI trade claims are replaced by actual server summaries. No global fixture ranking is presented as real competition data.

API pagination binds leaderboard pages to a run ID, and private state is discarded on account changes/obsolete route responses. Names respect current public-profile preference; emails/holdings never appear in leaderboard DTOs. Exact decimal strings supply monetary displays. Missing/failing APIs show explicit wait/error/retry states; older ranks carry their snapshot date and an out-of-date indication. `settling` displays as finalizing results. All results are virtual, with no payments or financial settlement. See [Phase 6 schema, calculations and worker commands](../../investiq-be/docs/PHASE-6.md).

## Phase 7 learning connection

`features/learning.js` owns Academy catalogue/lessons, enrollment, attempt submission/feedback/history, progress, achievements and signed-in profile learning metrics. Public GET `/courses` and `/lessons/{id}` expose published content without keys; verified cookie/CSRF-protected enrollment and attempt POSTs persist genuine activity. Quiz POSTs require a UUID Idempotency-Key; retry state preserves it for the same answers after failures. Own GET `/me/learning` and `/lessons/{id}/attempts` expose private progress/history. Server scoring, first-pass-only XP and IST streaks replace sample totals. Account/route generation checks guard stale requests. Guest localStorage is never uploaded. Full backend contracts and commands are in `investiq-be/docs/PHASE-7.md`.


## InvestIQ public contests

`ContestOut.organizer` distinguishes community and platform contests. Use `can_manage` for draft editing and publication controls; `is_owner` records original creation only. Admins use `/#/contests/admin` / `/#/contests/create-platform` and POST `/admin/contests`. Public explorer filtering uses `organizer=platform`; admin catalogue uses protected `scope=managed`. Verified learners join through existing entry APIs, confirm portfolio submissions and follow normal standings. Details explicitly distinguish a saved draft from an accepted submission. The local fixed scenario now extends through November 6, 2026 with due-only EOD release; it is not a real-time feed. Full setup and limits: `investiq-be/docs/PLATFORM-CONTESTS.md`.


## Results timing and empty states

`features/results-info.js` renders the shared calendar timeline in IST. Contest responses add first-close/first-result timestamps; leaderboard and performance responses add server-derived `timing` with the entry window, start/end, first close/publication and next publication time. `timing.state` distinguishes pre-start, waiting for close, processing, blocked data, current/final/cancelled/draft and unavailable calendar. Preserve server state rather than inferring it from the browser clock. Leaderboard `submitted_count` counts confirmed portfolios, while `participant_count` counts ranked snapshot entries. `has_joined`/`has_submission` are viewer-specific and control submission guidance and private-performance navigation. Upcoming metric categories are described before the first snapshot; no provisional returns or ranks are invented.


## Phase 8 connected rewards

`features/rewards.js` owns catalogue/detail, wallet/tier summary, two-step sandbox confirmation, ledger and redemption history. Routes use `marketplace`, `marketplace/{UUID}`, `marketplace/history` and `marketplace/ledger`. Helpers call public GET `/rewards`/`/rewards/{id}`, own GET `/me/coins`, `/me/coins/ledger`, `/me/redemptions`, and verified cookie/CSRF-protected POST `/me/redemptions` with `{item_id,item_version}` plus UUID Idempotency-Key. Server amounts/stock/status are authoritative; no user ID, cost or fulfillment inputs are accepted. Retry keys survive ambiguous confirmation errors within account memory, stale route responses are discarded and navigating back reloads balances after learning. A successful receipt is retained when follow-up wallet refresh fails; stale balances are hidden. No real reward fulfillment or browser demo imports occur. Full contracts: `investiq-be/docs/PHASE-8.md`.


## Phase 9 connected community

`features/community.js` replaces the local fixture feed for guests and accounts at `social` / `community`, `social/{post UUID}` and current-admin `social/moderation`. `communityApi` reads paginated public posts/replies/groups, current-viewer flags and poll totals; verified cookie/CSRF writes create posts/replies/groups, set likes/saves/membership, record a final vote or report, and moderate content. Post/reply retries retain the normalized payload (including poll deadline) and UUID key after ambiguous responses. Drafts stay in account memory and survive refresh rerenders; no community activity enters localStorage. Account/route generations reject stale responses, and loading/error/empty/retry states replace fixture fallback. Author names honor current public-profile privacy; moderation keeps reporter identities private. Groups are public, membership is required for posting/replying, and community earns no XP/coins. Full contracts: [Phase 9](../../investiq-be/docs/PHASE-9.md).


## Phase 10 connected performance coach

`features/coach.js` owns `insights` and `insights/{contest UUID}`; Performance links directly to the contest coach. `coachApi` reads private settings/evidence/jobs/reflections, posts `{contest_id}` with a UUID Idempotency-Key for generation, and posts private `{contest_id,body}` reflections with retry keys. The chooser uses genuine memberships, pending valuation is explicit, provider failure has no sample fallback, and queued/retry status polls every 2.5 seconds while the route/account remains active. API response errors retain the same generation key; successful reports are immutable and a later valuation requires new work. Current/old source dates, provider/prompt/generation metadata, versioned lesson excerpts, evidence references and limitations stay visible. The model chooses validated evidence/lesson IDs; it does not write financial figures or arbitrary causal claims. Every displayed source/lesson/journal string is escaped. Account/route changes invalidate stale responses, stop polling and clear private caches; real activity never enters localStorage. Gemini is configured only on the backend. Contracts and commands: [Phase 10](../../investiq-be/docs/PHASE-10.md).
