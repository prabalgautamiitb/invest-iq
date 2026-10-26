# InvestIQ — complete frontend development source

This is the complete **editable source project** for the current InvestIQ design, including every page, all interactions, UI refinement, and continuous background animation. It uses **vanilla JavaScript ES modules and Vite**, not React. There is no hidden source or minified bundle needed to customize the application.

## Admin workspace

Run the frontend as usual with `npm run dev`, then open these in separate tabs in the same browser:

- Learner app: **http://localhost:5173** (http://127.0.0.1:5173 also works).
- Admin app: **http://admin.localhost:5173** — opens the admin sign-in page.

Both addresses use the same frontend server and backend. The different hostnames keep their host-only session cookies separate, so signing in or out of one does not replace the other account. Keep using the admin hostname for admin tabs. A different path or port on the same hostname would still share cookies. No hosts-file entry is needed in browsers supporting `.localhost` loopback resolution, including Chrome. Use the existing admin email and password; public registration is not available on the admin portal.

The admin view also supports `VITE_APP_MODE=admin` when building a dedicated deployed admin frontend. Configure its exact origin in the backend's `INVESTIQ_CORS_ORIGINS` and serve `/api` through the same origin, retaining host-only cookies.

Administrator accounts open a focused workspace with two navigation items: **Contests** (`#/contests/admin`) and **Learning content** (`#/admin/courses`). Learner pages redirect administrators back to contest administration, and Ask Martin is hidden for administrators.

Use **Add InvestIQ contest** to save a draft, review it, and publish its fixed rules. In **Learning content**, use **Add course** to publish a course and its first lesson, or **Add lesson** on an existing course. Lessons include plain-text paragraphs, completion XP, and one or more multiple-choice questions with answer explanations. Publishing makes the content immediately available in Learn. Existing lessons, quiz attempts, and earned XP are preserved.

## Start developing

Use Node.js 22.12 or newer (Node 24 also works).

```bash
npm install
cp .env.example .env
npm run dev
```

On Windows, copy `.env.example` to `.env` using Explorer or `Copy-Item .env.example .env` in PowerShell. Open http://localhost:5173. Vite reloads changes during development.

```bash
npm run check
npm run build
npm run preview
```

`npm run build` generates the deployable `dist/` folder. **Edit `src/`, not generated `dist/`.** The ZIP deliberately excludes `node_modules` and build output; install dependencies using the lockfile.

## Where to customize

| Change | Edit |
|---|---|
| Page content, form behavior, navigation | `src/app.js` |
| Demo users, stocks, contests, lessons and questions | `src/data/demo-data.js` |
| Layout, desktop/mobile breakpoints | `src/styles/style.css` |
| Final Lovable design: layout, colors, responsive rules | `src/styles/lovable.css` |
| Earlier motion and visual foundations | `src/styles/polish.css` |
| Continuous background appearance | `src/styles/ambient.css` |
| Motion timing, chart and score animations | `src/lib/motion.js` |
| Background elements and pause toggle | `src/lib/ambient.js` |
| Request handling, base URL and errors | `src/api/client.js` |
| Proposed endpoint service methods | `src/api/services.js` |
| Local backend proxy | `vite.config.js`, `.env` |

## Backend connection

Phase 2 identity flows use the sibling FastAPI backend: registration/login/logout, verification and recovery, onboarding, profile/settings and session revocation. Start the backend as described in `../investiq-be/README.md`; use http://localhost:5173 for this UI and http://localhost:8025 for the local verification/recovery inbox.

The API client uses HttpOnly cookie sessions and in-memory CSRF values. No account session/token is saved in localStorage. Existing demo activity remains separate and is never uploaded. Phase 3 connects the portfolio instrument catalogue, search/filters/pagination and timestamped synthetic quotes. Portfolio allocations/submission, contests, academy, community, rewards and AI remain previews; the remaining API service methods are future integration points.

`.env.example` sets `VITE_API_BASE_URL=/api/v1` and `API_PROXY_TARGET=http://localhost:8080`. Secrets belong on the backend. The Vite proxy only runs in development; production needs an equivalent reverse proxy and HTTPS cookie/CORS configuration.

For browser tests with local PostgreSQL, Redis and Mailpit running:

```bash
npm ci
npx playwright install chromium
npm run test:e2e
```

The suite starts isolated API/Vite servers on 8081/5174 and a disposable migrated PostgreSQL database. See `../investiq-be/docs/PHASE-2.md` for full contracts, scope and test details.

## Included pages

Landing; login/signup; password reset; five-step onboarding and learning profile; home dashboard; My Contests; Leaderboard; contests and details; portfolio allocation and submission; academy and lesson quizzes; AI insights and journal; marketplace; social feed; profile; separate settings; privacy; terms; missing-page state.

The application currently uses hash routes (`#/portfolio`, etc.). Demo state is stored in `investiq-demo-v1`; ambient-motion preference uses `investiq-ambient-motion`.

The original files named `dist` were also uncompiled source. This project reorganizes that same design into a conventional development setup with separate data, styles, animation modules, and API scaffolding. It does not convert the application to React or implement a backend.

## Complete Lovable UI redesign

The signed-in Lovable MVP informed the complete navy, emerald and blue design system. The home dashboard now uses a performance hero, learning IQ ring, summary cards, quick actions and contest cards. Contests use compact information strips; Portfolio uses a two-step builder; Academy uses course progress; AI Insights includes benchmark comparisons and review sections. Separate My Contests, Leaderboard and Settings pages follow the reference navigation. All pages share responsive surfaces, typography, controls, and restrained background motion.

Edit `src/styles/lovable.css` for the final design layer. Page templates remain in `src/app.js`. Product rules and demo interactions are preserved; no live backend or Lovable source was imported.

## Page content sync — 18 October 2026

All primary signed-in pages now follow the supplied Lovable app's visible sections and reference fixtures. Shared fixture definitions live in `src/data/demo-data.js`: six contests, sixteen stocks, four course summaries, eight ranked learners, community posts, thirty-eight catalog rewards and achievements. `src/styles/sync.css` contains the final parity layout rules.

Home includes active contests, resume learning, insights, allocation, coins and community highlights. My Contests has a contest switcher and live summary. Contests has search/category filters, full details and local contest creation. Portfolio supports sector/cap filters, quantity/weight entry and 5–12 holdings with a 25% cap. Learn includes quizzes, achievements and streaks. Rewards includes filtering/sorting, details, tiers, earning methods and local redemption history. Community includes filters, polls, saved posts and groups. Profile, AI reports, Settings and Leaderboard now contain their reference sections.

Reference figures are explicitly illustrative. Coins, rewards, standings and course summaries are seeded UI fixtures, not verified activity. Redemptions, community joins, privacy switches and contest creation affect this browser only. No external invitations, posts, reward orders, billing, trading or security operations are performed. API scaffolding is not connected.

On first use, the new reference fixture migration preserves your name, journal and learning answers, while replacing the old practice stock allocations and seeded contest entries. It uses `referenceVersion: 2` inside `investiq-demo-v1`. To start from the reference defaults again, use Settings → Reset local demo.

The app retains its existing hash URLs and also accepts aliases `#/home`, `#/build`, `#/learn`, `#/community` and `#/rewards`. Home remains `#/dashboard`; My Contests is `#/my-contests`.

## Phase 3 market data

Start the backend using its migration and `python -m investiq.market_cli` seed, or the full Docker app profile. The Portfolio screen displays API-backed synthetic EOD prices, source/timestamps, server search/filtering and Load more. Missing/stale quotes disable selection; failed requests offer retry without a local-price fallback. The fixed dataset covers 14–16 October 2026 and will become stale as the expected session advances. It is not a live or real historical feed. Server drafts and submission arrive in Phase 5. Full policy and commands: `../investiq-be/docs/PHASE-3.md`.

## Phase 4 contests

Contests now use the backend for discovery/search/filters, details, configurable draft creation/revision, publication, private in-app invitations, joining and My Contests. Start the backend with the [backend README](../investiq-be/README.md), register and verify your email using local Mailpit, then open Contests. Save a draft and publish to freeze its rules. Joining is separate from the future server portfolio submission. My Contests supports Joined/Hosted views and a contest switcher; it shows genuine memberships without fixture ranks/returns. Invitations appear in the recipient's My Contests; no external email is sent. See [Phase 4 contracts and setup](../investiq-be/docs/PHASE-4.md).

## Phase 5 portfolio builder

Verified contest members now save drafts on the server. Join a contest and open its portfolio from details, My Contests, or the Portfolio chooser. Use quantities or weights, **Save draft → Review saved draft → Confirm contest submission**. Server calculations supply whole shares, exact fees/cash and source evidence. Submitted versions are immutable, with the newest accepted version used at entry close; old versions remain visible. The builder detects conflicting saves from other tabs and does not overwrite them automatically. The account builder includes live stock search, sector/cap filters, an allocation progress bar, holding/weight checks and equal-weight allocation. Destructive starter/mode changes ask before clearing existing values. On mobile, **Explore stocks / Your draft** switches between panels without clearing edits; desktop shows both panels together. Review scrolls to the server calculation before confirmation, and submission history distinguishes confirmed entries from saved drafts. Signed-out practice drafts remain separate. See [Phase 5 setup, rules and API examples](../investiq-be/docs/PHASE-5.md).

## Phase 6 simulation results

The signed-in dashboard, contest leaderboards, private performance and completed-contest history now use persisted backend valuation snapshots. My Contests shows actual values/returns/ranks with snapshot dates. Use Performance or Leaderboard links after submitting; results wait for a complete published market close. The backend Compose app profile starts the required worker and one scheduler. Prices remain fixed synthetic October 14–16, 2026 fixtures; data outside that range is not invented. [Phase 6 setup and contracts](../investiq-be/docs/PHASE-6.md) explain calculations, freshness, privacy and test scenarios. No real trades, payments or payouts occur.

Phase 7 connects Academy and signed-in learning profiles to the backend. Enroll in a development course, answer its quiz and refresh to see saved XP/completion/history. Email verification is required for enrollment and quiz submission. The local Compose app profile seeds two courses and six lessons; host setups run `uv run --locked python -m investiq.learning_cli` in `investiq-be`. Retakes do not add XP. Rewards and community remain previews.


InvestIQ public contests are available under **Contests → InvestIQ**. Verified admins can use **Manage InvestIQ contests** to add/review/publish them. Provision the admin role with the backend operator command and sign in again; ordinary user creation remains available. After joining, confirm a portfolio submission to enter the standings. See `investiq-be/docs/PLATFORM-CONTESTS.md` for the full setup and fixed synthetic price coverage.


Phase 8 connects Rewards to the backend: genuine first lesson completions earn 50 virtual coins, tiers use lifetime earnings, and the catalogue supports inventory-checked sandbox redemptions. Use Rewards → Redemption history / Coin ledger to inspect persisted events. No real gift card, shipment, booking or premium entitlement is delivered. Backend Compose seeds the catalogue; host setups run `uv run --locked python -m investiq.rewards_cli`. Existing genuine completion earnings are recovered once, and browser demo balances/history are never uploaded.


Community now uses shared backend posts, replies, likes, private saved posts, polls, public groups and administrator moderation. Open `/#/social` with the API running. Sign in and verify email to participate. Public-profile settings control author display names; group content is public. See [Phase 9](../investiq-be/docs/PHASE-9.md) for setup and contracts.


Insights now opens the private performance coach at `/#/insights`. Select a joined contest with a confirmed submission and published valuation to generate a report with Ollama. Reports show deterministic metrics/evidence references, model-selected learning priorities, versioned lesson excerpts and limitations. Private decision-journal entries are saved and never sent to the model. Generation is queued, retryable and optional; a missing model does not block core features. [AI setup and Gemini configuration](../investiq-be/docs/PHASE-10.md).


For an interactive contest lifecycle without waiting for market hours, use the [manual contest sandbox](../investiq-be/docs/MANUAL-CONTEST-TESTING.md). Its frontend runs separately at `http://127.0.0.1:5175`, with a local clock/control page, fresh accounts and a disposable database. Normal development at port 5173 remains separate.


## Clearer results and charts

Signed-in Home shows a portfolio value chart in virtual INR for a selected contest, its latest value/return, and an AI guidance card with up to two priorities and a suggested lesson. Choose another recent contest from the selector; use **Exact portfolio values** or **Load earlier portfolio values** to inspect history. **Generate AI insights** requests a report through the existing coach worker, with status refreshed every five seconds while Home is open. Existing reports are reused, and reports for an older valuation are labeled. Empty/error states are independent for the chart and insights. Home also shows returns by contest. Performance shows a daily portfolio-versus-benchmark chart, holdings/cash allocation, and holding contributions in percentage points. Leaderboards compare up to ten loaded standings. The builder shows the reviewed server allocation before confirmation.

Charts use saved API evidence, never demonstration results for signed-in users. One close shows a single point; an unvalued contest shows a waiting state. Daily chart points run oldest to newest across the loaded snapshot page; open **Daily snapshots → Load earlier snapshots** for additional history. Different contests can have different snapshot dates, so Home does not present their returns as a single combined return.

Schedules, advanced filters, metrics and submission versions are expandable. The portfolio flow remains **Choose stocks → Save draft → Review & confirm**. Chart rendering lives in `src/features/charts.js`; final spacing, chart and mobile styles live in `src/styles/clarity.css`. All chart data is also available as labeled values or expandable tables. Contest cards in discovery, My Contests and administration show prominent start/end dates and times in IST, a status-specific entry deadline, and expandable schedule details for entry opening and first-result timing. Cancelled contests label dates as planned; missing result timing is shown as to be announced. My Contests has a separate, compact results layout with portfolio value, net P&L, return and rank before dates. It uses two-decimal INR/percent formatting, explicit snapshot freshness and submission states, and prioritizes Performance once entries are closed or valued. Full schedules and descriptions are expandable; repeated contest-name tabs are removed. Personal results reload when returning to the page, and memberships outside Home’s latest 20 use their private performance endpoint. Failed results or invitation requests are labeled without hiding the other available information.


AI Insights now opens one report at a time. **Overview** contains up to three key takeaways, what worked, what to review and a next learning step. **Learning** holds suggested lessons and cited excerpts; **Journal** holds private reflections; **Evidence** holds all recorded facts, source references, limitations and technical details; **Past reports** opens saved reports individually. The contest name and snapshot date stay visible, earlier snapshots are labeled, and **Show latest report** returns from a selected historical report. Unsaved journal text survives section changes, and report polling leaves navigation available while generation runs.


## Ask Martin

The circular Martin avatar opens private educational chat on workspace pages. Sign in and verify your email, choose a learning or performance question, and send it. Replies cite approved Academy passages and your own recorded contest evidence. Follow-ups, paginated chat history, cancellation, retry and deletion are connected to the backend. Keep Ollama and the backend worker/Beat running. See [setup, API, privacy and grounding](docs/ASK-MARTIN.md).


## Contest Explorer and joining page

Explorer cards use the discovery layout: host/type, learning level, prize availability, virtual capital, free entry, joined count, seat progress, countdown, dates and a single **View contest** action. Portfolio, performance and leaderboard shortcuts remain in My Contests. No Trending/Friends categories, prize amounts, XP or coin awards are invented; the current contest contract configures practice simulations with no prize pool.

Discovery requests `activity=active` to show upcoming/open/locked/running contests, with filtering applied before pagination. An explicit status filter can show past/finalizing contests. Countdown timestamps come from the backend's `server_time`, and update without rerendering search or forms. The detail page includes join/full/joined states, rules and entry deadline, seat progress, rewards availability, copy-link, and up to five persisted public standings. Unavailable standings leave the contest and join flow usable. Draft publication, revisions, cancellation and private invitations remain available to their authorized hosts. My Contests is unchanged.

Presentation lives in `src/features/contest-explorer.js` and `src/styles/contests.css`. Rebuild the backend API to use the new activity filter and server timestamp; no migration is required.

Contest creation/revision validates the IST schedule in order: entry opens → entry closes → contest starts → contest ends. Invalid ordering highlights the affected inputs, explains the correction, and blocks the POST without discarding values. The form also checks holdings limits and the eligible-stock minimum. Server validation details map back to fields; generic calendar/publication errors remain visible in the form summary. AM/PM selections stay under the host's control.

Yahoo mode adds a Nifty 50 daily market overview to Home and source labels to
contests/portfolios/results. Catalogue requests follow each contest’s frozen source.
The backend controls source configuration and imports; the browser uses saved
prices only. See [Yahoo EOD setup](../investiq-be/docs/YAHOO-EOD.md).

Portfolio stock discovery shows each company’s exchange, sector and market-cap
category, plus the displayed session’s opening price, closing price and signed
open-to-close percentage change. Cards label the trading date, source and freshness.
Missing openings or changes remain unavailable; old closing prices are labelled
as earlier sessions and cannot be used to add an ineligible holding.
