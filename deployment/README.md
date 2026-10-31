# InvestIQ on Vercel

This directory prepares the existing application for an HTTPS educational deployment.
No cloud resources or production accounts are created by these files. Existing local
accounts/data remain local unless deliberately exported and restored. Subscriptions
remain activation-only: no billing, payment collection or renewal is introduced.

## Deployment layout

Use the **repository root**, not `investiq-fe`, for the main Vercel project.
`../vercel.json` defines:

- `web`: Vite frontend from `investiq-fe`, output `dist`.
- `api`: Python 3.13 FastAPI instance at `investiq-be/app.py`.
- `/api/*` routes to FastAPI unchanged; all other paths route to the frontend.
- `worker`: existing Dockerfile/Celery app, concurrency 2, one instance.
- `scheduler`: the same image with `python -m investiq.jobs.scheduler`.

The scheduler holds a PostgreSQL session advisory lock per queue. A replacement
waits for the old scheduler to stop before publishing. A lost database connection
stops its child Beat process, then exits so the platform can restart it. Use a
**direct database endpoint**, not a transaction-pooling URL: the scheduler and
release lock require session affinity. Workers keep the existing persisted job
claims, idempotency and retry behaviour. Grace periods allow current jobs to finish.
The scheduler's temporary timing file can be lost on restart; persisted valuation
and report records prevent creating duplicate results.

The example region is `iad1`. Select a supported region close to the database for
both daemons and configure the API region consistently in Vercel. Each daemon requests
1 GiB memory. Review Vercel quotas/costs before activating them. Services and Daemons
are beta features; daemons currently run only in production deployments, not previews.
Use a separate staging project/data/queue for a complete pre-launch rehearsal.

Official references:
- https://vercel.com/docs/services
- https://vercel.com/docs/frameworks/backend/fastapi
- https://vercel.com/docs/daemons/config-reference

## 1. Provision dependencies

Create a dedicated PostgreSQL database, Redis instance supporting normal TCP/TLS
connections (not REST-only), SMTP credentials/verified sender and Gemini credentials.
Keep passwords in the provider dashboards/Vercel, never in Git or frontend variables.
Your selected model must be available to your Gemini account. AI may temporarily be
explicitly disabled while setting up the other features.

Use Redis with persistence/no-eviction for the broker. Different logical database
numbers are optional; some providers support only database 0. Production, staging,
and previews must never consume each other's queues or use the same account data.

## 2. Configure the production environment

Copy `production.env.example` to the ignored root `.env.production.local`, fill its
placeholders, and add those same values to Vercel **Production** environment settings.
When linked, `vercel env pull --environment=production .env.production.local` can pull
these values locally. Do not shell-source the file: use uv's `--env-file` option below.

- `INVESTIQ_ENVIRONMENT=production` retains Secure/HttpOnly `__Host-` session cookies.
- `INVESTIQ_HOSTED_SIMULATION_ENABLED=true` explicitly enables virtual-money market,
  contest, valuation and bundled educational/sandbox catalogue initialization.
  Without this flag production market operations remain disabled.
- `INVESTIQ_DATABASE_URL` accepts `postgres://`, `postgresql://` or
  `postgresql+asyncpg://` and normalises to asyncpg internally. Set `sslmode=verify-full`.
  `require` also uses certificate/hostname verification for asyncpg. Provider CA roots
  can be supplied using `sslrootcert`. Remove `channel_binding=require` from provider
  URLs: asyncpg does not implement it; the preflight rejects it explicitly.
- Pool size 1 and overflow 0 limit per-process database usage. Account for API instance
  scaling, worker processes, the scheduler lock and the release lock when sizing Postgres.
- `INVESTIQ_CELERY_BROKER_URL` must be `rediss://...?...ssl_cert_reqs=required`.
- Set explicit HTTPS learner/admin CORS origins (JSON array, without trailing paths).
  `FRONTEND_URL` is the learner origin used in verification/reset links.
- Use SMTP STARTTLS (normally port 587), a verified sender and real credentials.
- `VITE_API_BASE_URL=/api/v1` keeps cookies/CSRF same-origin. No API secrets need a
  `VITE_` prefix. `API_PROXY_TARGET` is development-only.

Do not copy production credentials into Vercel Preview or CI. Configure a separate
preview backend/database if needed. Daemons will not run in previews.

## 3. Initialise before the first production promotion

From `investiq-be` with uv installed:

```sh
uv sync --locked
uv run --locked --env-file ../.env.production.local python -m investiq.deploy_cli check
uv run --locked --env-file ../.env.production.local python -m investiq.deploy_cli initialize
```

`check` validates configuration without contacting providers. `initialize` takes a
release lock and applies Alembic migrations, initializes the Nifty 50 catalogue and
reviewed exchange sessions, publishes the bundled courses/lessons and sandbox rewards,
and sets up AI checkpoint tables. It creates **no users, contests, learner activity,
portfolio submissions or fabricated market prices**. Reruns preserve published
content; differing definitions require a new content version. No automatic promotion
or deployment is part of the command.

The bundled exchange calendar currently covers 2026. Extend/review it before running
contests outside that supported range. Import Yahoo data through the existing worker
or an explicit operator import after initialization:

```sh
uv run --locked --env-file ../.env.production.local python -m investiq.market_cli --yahoo
```

Provider availability must be verified from the hosted region. Failed/missing imports
remain unavailable and do not get replaced with synthetic prices. This switch does
not grant any additional market-data usage rights.

For subsequent releases: back up production data, run the release command against
the target database, then promote the matching build. Only run reviewed migrations;
code rollback does not roll back database migrations.

## 4. Link and deploy the main application

Once the GitHub URL is supplied, push this repository and connect it to Vercel.
Use Root Directory `.`. Let the services configuration drive each build; do not
set a project-wide frontend output directory or build command. The web service
already specifies `npm run build` and `dist`; the API has `pyproject.toml`/`uv.lock`.

With an authenticated Vercel CLI you can link the project without publishing it:

```sh
npx vercel link
```

After step 3 and production environment configuration, deploy/promote the matching
commit. Check both daemon logs and `/api/v1/health/ready`. Configure Gemini quotas and
spending limits in the provider dashboard. Do not point hosted Ollama at localhost.

## 5. Deploy the separate admin project

After the main HTTPS origin is known, run from the repository root:

```sh
node scripts/prepare-admin.mjs https://YOUR_APP_DOMAIN
```

This writes `investiq-fe/vercel.json` from the template, proxying `/api/*` to that
origin. Commit the generated routing before enabling Git deployments for the admin
project. The main application's routing remains in the repository-root config.

Create a second Vercel project with Root Directory `investiq-fe`, framework Vite,
build `npm run build`, output `dist`. Set `VITE_APP_MODE=admin` and
`VITE_API_BASE_URL=/api/v1`. It needs no database, mail or AI credentials. Include
its final HTTPS origin in the main backend's CORS list, then redeploy.

Register and verify the operator account through the learner app, then assign its
role through the backend CLI (never a public role-grant endpoint):

```sh
cd investiq-be
uv run --locked --env-file ../.env.production.local python -m investiq.cli set-role ADMIN_EMAIL admin
```

Use the separate admin origin to sign in. Check verification/reset URLs return to
the intended learner origin and admin authentication is enforced after redirects.

## 6. Verify the complete deployment

From the repository root:

```sh
node scripts/deployment-smoke.mjs https://YOUR_APP_DOMAIN
```

The read-only script checks frontend HTML, health/readiness, CSRF bootstrap,
no-store headers and secure production-cookie flags. It never prints CSRF/session
credentials. Then verify in a browser:

1. Registration, verification email, login, logout and password recovery.
2. Learner/admin sessions open side by side; CSRF failures/cross-origin mutations blocked.
3. Published contests, joins, saving/reviewing/confirming a portfolio, stock filters/sorting.
4. Yahoo daily imports and valuations, private holdings and public leaderboard results.
5. Daily AI report generation/refresh and an Ask Martin answer via Gemini.
6. Course enrollment/quiz, community membership/feed, photo upload, subscription activation.
7. Narrow mobile layouts, polling/refresh, error states and user data after reload.

CI runs lint/type/unit/integration checks against disposable/test databases. Browser
checks remain available with `npx playwright test` in `investiq-fe`; the test harness
owns a separate migrated database and requires local Postgres/Redis/Mailpit. A full
hosted smoke pass is still required after actual provisioning and deployment.

## What is still needed from the owner

- The GitHub repository URL and permission to push.
- Vercel account/project connection, with Services/Daemons available and appropriate quotas.
- PostgreSQL, Redis, SMTP and Gemini resources/credentials added through secure settings.
- Learner/admin domain choices and the verified sender address.
- Whether existing local accounts/results should be migrated or the hosted app starts empty.

No live deployment or provider integration has been performed by this preparation.
