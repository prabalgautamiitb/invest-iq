# InvestIQ: free demo deployment

The default configuration targets a small, non-commercial MBA demo using free
plans. It starts no Vercel Daemons, Celery workers or scheduler. No paid resources
or subscriptions have been activated. Provider quotas still apply: a free service
may pause or reject requests when its allowance is exhausted. Do not enable
paid plans, auto-upgrades or billing just to bypass a quota.

## Architecture

- Main Vercel Hobby project: Vite frontend and FastAPI, from repository root `.`.
  `vercel.json` routes `/api/*` to the API and other paths to the frontend.
- Separate Vercel Hobby admin project: frontend from `investiq-fe`, proxying to
  the main API. Both projects can use their included `vercel.app` addresses.
- Neon Free PostgreSQL: application data and persisted results. Free-demo mode
  closes database connections after use so an idle database can suspend.
- Upstash **Free** Redis: normal TCP/TLS (`rediss://`), for authentication rate
  limits, optional AI allowance and cached news. No queue broker is needed.
- Brevo Free (or another free authenticated SMTP relay): verification/reset email.
- Daily processing: a standard Ubuntu GitHub Actions runner in this **public**
  repository. Nothing runs continuously. Private repositories are deliberately
  excluded by the workflow's condition to avoid consuming paid runner minutes.
- Optional Gemini free-tier AI: off initially. Deterministic performance metrics,
  portfolio results, strengths/weaknesses and lessons still use saved results.

Sources checked for this setup:
[GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions),
[Vercel Hobby](https://vercel.com/docs/plans/hobby),
[Neon Free](https://neon.com/pricing),
[Upstash Free](https://upstash.com/pricing/redis),
[Brevo plans](https://help.brevo.com/hc/en-us/articles/208589409-About-Brevo-s-pricing-plans),
[Gemini free tier](https://ai.google.dev/gemini-api/docs/pricing).
Recheck free-plan allowances when creating accounts; app configuration cannot
verify a provider account's billing settings.

## 1. Create free services and configure secrets

Create a Neon Free database, Upstash Free database, and a free SMTP account with
an approved sender. Keep the services in compatible nearby regions. Use a direct
PostgreSQL endpoint with `sslmode=verify-full`; remove `channel_binding=require`
because asyncpg does not implement it. Upstash's REST URL/token is not a Redis
connection string. Use its TLS connection URL instead. Check sender approval and
email delivery before inviting learners; the app retains email verification.

Copy `deployment/production.env.example` to the ignored root `.env.production.local`.
Fill placeholders and add the same values to Vercel **Production** settings:

- `INVESTIQ_DEPLOYMENT_MODE=free_demo`: connections close between transactions;
  manually requested AI work executes inside the authenticated POST request.
- `INVESTIQ_ENVIRONMENT=production` and `INVESTIQ_HOSTED_SIMULATION_ENABLED=true`:
  secure production cookies plus explicit virtual-money simulation opt-in.
- `INVESTIQ_FRONTEND_URL`: the main learner HTTPS origin.
- `INVESTIQ_CORS_ORIGINS`: JSON array of exact learner/admin HTTPS origins.
- `VITE_API_BASE_URL=/api/v1`: same-origin cookie/CSRF requests.
- `INVESTIQ_AI_PROVIDER=disabled`: no model calls or AI-provider costs initially.
- SMTP credentials and verified `MAIL_FROM` are required for account email.

Do not put credentials in Git or in variables prefixed `VITE_`. Keep production
credentials out of Preview and CI. Do not shell-source dotenv files; use uv's
`--env-file` below. Keep the example's rate-limit prefix consistent between the
web app and daily runner, and separate from development/staging.

## 2. Initialize the hosted database

From `investiq-be`:

```sh
uv sync --locked
uv run --locked --env-file ../.env.production.local python -m investiq.deploy_cli check
uv run --locked --env-file ../.env.production.local python -m investiq.deploy_cli initialize
```

`check` validates settings without contacting providers. `initialize` takes a
short-lived release lock, migrates the schema, initializes Nifty 50 definitions,
reviewed exchange sessions, published lessons and sandbox rewards, and AI
checkpoint tables. It creates no users, contests, submissions or fabricated
market prices. Reruns preserve published content. Existing local data stays local
unless deliberately exported/restored. Back up data before subsequent migrations.

The reviewed calendar currently covers 2026. Extend it before contests in 2027.
Market quotes remain unavailable when upstream imports fail; synthetic prices
never silently replace missing Yahoo prices.

## 3. Deploy the main and admin projects

Sign in using `npx vercel login`, connect the GitHub repository, and choose **Hobby**.
For the main project use Root Directory `.`. Let the two services in root
`vercel.json` configure their builds; do not override a project-wide output folder.
The API has a 120-second request limit for a bounded AI call and database work.
There are no cron HTTP endpoints or publicly callable batch jobs.

After the main HTTPS domain is known, run from the root:

```sh
node scripts/prepare-admin.mjs https://YOUR_APP_DOMAIN
```

Commit the generated `investiq-fe/vercel.json`, then create a second Vercel project
with Root Directory `investiq-fe`, Vite, build `npm run build`, output `dist`.
Set `VITE_APP_MODE=admin` and `VITE_API_BASE_URL=/api/v1`. No backend credentials
belong in this frontend project. Add its actual HTTPS origin to the backend CORS
list and redeploy. Register/verify an operator account, then grant its role locally:

```sh
cd investiq-be
uv run --locked --env-file ../.env.production.local python -m investiq.cli set-role ADMIN_EMAIL admin
```

No custom domain purchase is required. Subscriptions in the app remain simulation
activations: no payment gateway, charge or renewal is introduced.

## 4. Enable the free daily update

In GitHub Settings → Environments, create `production` and restrict it to `main`.
Add environment secret `INVESTIQ_PRODUCTION_ENV`: the complete contents of your
filled production dotenv file (never the placeholder example). GitHub Actions
writes it into a temporary private file and removes it after use. Ensure workflow
logs never print the file. Do not add production secrets to the test CI job.

Add repository Actions variable `FREE_DEMO_JOBS_ENABLED=true`. In Actions, select
**Daily simulation update** and use **Run workflow** on `main` to verify it.
The workflow is deliberately opt-in, has no push/PR trigger, uses read-only repo
permissions, and has a 20-minute timeout with a 15-minute processing deadline.
It performs no migrations or deployments.

The schedule is **20:47 IST Monday–Friday** (`17 15 * * 1-5` UTC). GitHub may delay
or skip a scheduled run; this is not an exact-time service. Public-repository
schedules can be disabled after 60 days of repository inactivity. Check Actions
before your presentation and rerun manually if necessary:
[GitHub workflow controls](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows).

The job imports up to five missing published daily closes, evaluates due contest
portfolios (up to five catch-up passes), reconciles rewards, refreshes shared news,
queues/attempts up to 20 reports and processes up to five queued chat requests.
Expired chat leases become failures that the learner can retry.
A database advisory lock prevents overlapping daily runs. Existing publication,
valuation and report idempotency prevents duplicate results. The lock/connection
exists only during this short job, not between days. Larger backlogs require
another manual run. Missing prices and blocked results remain labelled as such.

To run the same update manually from your own machine:

```sh
cd investiq-be
uv run --locked --env-file ../.env.production.local python -m investiq.jobs.daily
```

## 5. Optional free-tier AI

To enable Ask Martin and generated per-contest reports, choose a Gemini model
currently eligible for your account's **free tier**, use a project without paid
billing, and set `INVESTIQ_AI_PROVIDER=gemini`, `INVESTIQ_GEMINI_MODEL` and
`INVESTIQ_GEMINI_API_KEY` in both Vercel and the GitHub production secret. Do not
use local Ollama URLs from Vercel. A provider key does not itself prove free-tier
eligibility; verify that in Google AI Studio.

The default shared cap is **20 attempted model generations per UTC day**, across
all users, web requests, daily jobs and retries. `INVESTIQ_FREE_DEMO_AI_DAILY_LIMIT`
can be lowered. Requests fail closed if the allowance check is unavailable.
Failed calls also consume allowance; cached/idempotent answers do not. This limits
app usage, not provider billing: only a free, non-billed provider account prevents
paid API charges. Provider rate/model/token quotas can be lower than the app cap.

Manual answers/reports await one bounded generation during their POST request,
using only the already authorized turn/job. Existing database leases prevent
concurrent duplicate processing. A dropped connection or process interruption
may leave a durable queued/running item; the daily job recovers it. Normal worker
mode remains available for local Docker development. Daily reports update after
the daily valuation run; news refreshes daily rather than hourly in this setup.

## 6. Verify before sharing

```sh
node scripts/deployment-smoke.mjs https://YOUR_APP_DOMAIN
```

Check email verification/login/reset, learner/admin sessions side by side, contest
creation/publication/join/submission, a manual daily run, prices/values/standings,
AI if enabled, lessons, community, profile photos, subscription activation and
mobile navigation. Check reloads preserve private user data. Readiness checks
exercise dependencies, so do not schedule frequent external uptime polling that
keeps the database awake.

Free tiers have finite compute/storage/request/email allowances and no promise of
production reliability. Usage caps should stop features rather than trigger paid
upgrades. No provider credentials have been provisioned by these code changes;
real hosted builds, emails, imports and end-to-end smoke checks remain required.
