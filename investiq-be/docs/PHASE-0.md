# Phase 0 — frontend assessment

Inspected `src/app.js`, `src/data/demo-data.js`, `src/api/client.js`, `src/api/services.js`, `vite.config.js`, the README and both frontend docs. The frontend is vanilla JS ES modules with hash routing, not React. `app.js` imports illustrative fixtures and persists `investiq-demo-v1`; no API service imports connect its page actions. Motion preferences use a separate localStorage key.

The backend uses port 8080 to match the existing Vite proxy. API paths use `/api/v1`. The API client sends cookie credentials and understands `error.message`. Proposed helpers are useful starting contracts, not a complete specification.

## Page-to-endpoint map

Every path below has `/api/v1` prefix. Operational endpoints, Phase 2 identity/onboarding and Phase 3 market rows are implemented. Other rows define proposed contracts for their scheduled phases.

| Page / actions | Proposed endpoints | Phase |
|---|---|---|
| Landing, signup, login, logout | POST `/auth/register`, `/auth/login`, `/auth/logout`; GET `/auth/csrf`; DELETE `/me/sessions/{id}` | 2 |
| Recovery and verification | POST `/auth/password-reset/request`, `/auth/password-reset/complete`, `/auth/verification/request`, `/auth/verification/complete` | 2 |
| Five-question onboarding and result | GET `/onboarding/questions`; PUT `/me/onboarding` | 2 |
| Profile and settings/privacy | GET/PATCH `/me`; GET/PATCH `/me/preferences`; GET/PATCH `/me/privacy`; GET `/me/sessions` | 2 |
| Stock search, sector/cap filters and quotes | GET `/instruments?query=&sector=&market_cap=&cursor=&limit=`; GET `/quotes?instrument_ids=` | 3 |
| Contest list/search/filter/detail/create | GET/POST `/contests`; GET `/contests/{id}`; POST `/contests/{id}/invitations` | 4 |
| Join, My Contests and switcher | POST `/contests/{id}/entries`; GET `/me/contests` | 4 |
| Portfolio quantity/weight entry, confirm | GET/PUT `/contests/{id}/portfolio-draft`; POST `/contests/{id}/submissions` | 5 |
| Dashboard, contest history and leaderboards | GET `/me/dashboard`, `/contests/{id}/leaderboard`, `/me/portfolios/{id}/performance`; GET `/leaderboards` | 6 |
| Academy, lessons, quiz completion | GET `/courses`, `/lessons/{id}`, `/me/learning`; POST `/lessons/{id}/attempts` | 7 |
| Achievements/streaks | GET `/me/achievements`, `/me/streaks` | 7 |
| Coins, tiers, reward filters/detail/redeem/history | GET `/rewards`, `/rewards/{id}`, `/me/coins`, `/tiers`; GET/POST `/me/redemptions` | 8 |
| Feed, create/delete posts, comments, helpful reactions, saves | GET/POST `/posts`; DELETE `/posts/{id}`; GET/POST `/posts/{id}/comments`; PUT/DELETE `/posts/{id}/helpful`, `/posts/{id}/saved` | 9 |
| Poll votes and groups/join | PUT `/polls/{id}/vote`; GET `/groups`; PUT/DELETE `/groups/{id}/membership` | 9 |
| AI reports and decision journal | POST `/me/portfolio-reviews`; GET `/me/portfolio-reviews/{id}`; GET/POST `/me/journal` | 10 |
| Educational assistant | POST `/me/assistant/threads`; POST `/me/assistant/threads/{id}/messages` | 11 |
| Notifications and delivery controls | GET `/me/notifications`; PATCH `/me/notifications/{id}`; GET/PATCH `/me/notification-preferences` | 12 |
| Health and infrastructure | GET `/health/live`, `/health/ready` | 1, implemented |
| Terms, privacy information, presentation/motion | Static pages and local presentation settings | No backend needed |

## Findings and inconsistencies

- `BACKEND-INTEGRATION.md` first says no API client exists, but the project contains `client.js` and `services.js`; its later export note is accurate. Its suggested Spring backend is superseded by the requested FastAPI stack.
- The README mentions `.env.example`, but no frontend environment file exists. Vite and client defaults already work without it.
- Helper endpoints are incomplete for rewards, polls, groups, settings, creation, recovery completion and sessions. Draft helpers use a single `/me/portfolio/draft`, which cannot distinguish multiple contests. Adopt contest-scoped draft URLs in Phase 5 and update helpers then.
- The draft example has three holdings weighted 30/30/40 percent, violating the 5–12 holding requirement and 25% cap. It is illustrative, not a valid submission contract.
- Different cards use ₹1 lakh, ₹10 lakh and other starting capital; capital must come from contest rules, never a global frontend default.
- Four executable sample lessons differ from the course-summary lesson totals and seeded progress. There is no authoritative course progress to migrate.
- `xpTotal`, `coins`, rank rows, streaks, dashboard performance, seeded memberships, achievements and redemptions are illustrative. A new backend user starts without those activities.
- AI copy refers to sample trades and exit decisions; the locked MVP has no trading history, so it cannot support those claims.
- Discovery, dashboard and My Contests contain fixed participant counts/times/returns. Render authoritative empty/loading states when their backend phase lands.
- Reference IDs are slugs/symbols. Persist stable UUIDs and expose separate slugs/symbols; never treat a symbol as permanent identity.

## Working assumptions for later phases

MVP portfolios lock before starting and cannot trade during a contest. Drafts remain editable until the entry deadline; pre-deadline resubmission creates a new immutable version and atomically changes the active version. Rules freeze once the contest opens for entry.

Use a common published end-of-day snapshot for submission pricing, named in the contest rules. Percent input uses integer basis points; shares use floor division against server prices, with residual cash allowed. Include simulated fees when checking available capital; reject an over-budget conversion instead of silently scaling holdings. Apply the configurable fee once at submission, rounded half-up to paise. Fees count in the capital check; maximum position size compares market value with initial capital. These policies must receive executable tests in Phase 5.

EOD rankings require a common complete timestamp for all eligible instruments and the benchmark; stale/incomplete data blocks publication. An exchange holiday uses the previous documented trading session, not an invented observation. Exclude instruments with unsupported splits/dividends until adjustments are implemented. Tie-break by return, then earlier accepted submission, then membership UUID. None of these market policies is implemented in Phase 1.

Never import browser fixture balances, learning history, roles, prices or rankings into genuine user records. Real fulfillment remains disabled until provider integration exists.

Phase 2 follow-up: the missing frontend `.env.example` is now supplied, identity routes are wired, and the onboarding question snapshot is persisted as version 1. Other fixture inconsistencies remain tracked for their domain phases.

Phase 3 follow-up: instrument search/filter/pagination and timestamped quotes now use the API. Stable UUIDs identify instruments; symbols remain display/local-preview keys until Phase 5. Official licensing/education-data research supersedes the earlier tentative production EOD suggestion; see PHASE-3.md.
