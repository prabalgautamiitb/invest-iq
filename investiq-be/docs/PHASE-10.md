# Phase 10 — Evidence-backed AI coach

## Goal and decisions

Replace the Insights fixture with private reviews of a learner's own saved simulation results. Use **Ollama for development**, with a separate **Gemini adapter** ready for an explicit operator switch. Phases 0–9, a confirmed portfolio, a successful immutable valuation and published Academy lessons are prerequisites for generation. A model is never required to use identity, contests, portfolios, valuation, learning, rewards, community or the private decision journal.

The model selects useful observations and learning priorities from a constrained Pydantic plan. It cannot generate arbitrary report prose, numbers, security-sensitive identifiers or executable actions. Python validates every selected fact/citation/category and renders statements from deterministic templates and saved source records. This is an intentionally constrained coach, not an open-ended chat agent or personalized investment adviser. Unsupported IDs, extra fields and malformed structured output fail validation; they are never displayed as a provisional report.

The report includes portfolio value/return/rank, benchmark/excess return, largest exposure and concentration HHI, holding/sector counts, largest/smallest contributions, observed positive contributions where present, review points, cited learning actions, a reflection question and limitations. It does not invent a risk score, claim motives or trades, diagnose mistakes from price movement alone, calculate counterfactual returns or recommend purchases/sales. No trading, settlements, reward issuance, account mutation, arbitrary SQL, browsing or shell tools are given to the model.

Published lesson versions are retrieved from the existing reviewed Academy curriculum, frozen with the request, and supplied as untrusted data. The model chooses relevant lessons from this bounded candidate set (at most 12 latest published stable lessons). Quiz questions/keys, profiles, emails, community posts and private reflections are excluded. Semantic retrieval, pgvector, document ingestion and open-ended educational Q&A remain Phase 11 work; they are not represented as completed RAG here.

## Provider configuration

`adapters/coach.py` defines `CoachProvider`, the typed generation/usage result, and a LangChain implementation selecting ChatOllama or ChatGoogleGenerativeAI. Requests use native JSON-schema structured output, temperature zero, bounded output and an explicit asynchronous timeout. Provider exception text, prompts and raw responses are not logged or stored. There is no automatic fallback from local Ollama to a cloud model.

Defaults:

| Setting | Default / purpose |
| --- | --- |
| `INVESTIQ_AI_PROVIDER` | `ollama`; also `disabled` or `gemini` |
| `INVESTIQ_OLLAMA_MODEL` | `llama3.1:8b`; must already be installed; the app never pulls models |
| `INVESTIQ_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` for a host API/worker; operator-controlled origin, never a client URL |
| `INVESTIQ_OLLAMA_DOCKER_URL` | `http://host.docker.internal:11434`; Compose maps it to the container's `OLLAMA_BASE_URL` |
| `INVESTIQ_AI_TIMEOUT_SECONDS` | 45, supported 5–60 seconds per provider call |
| `INVESTIQ_AI_SCAN_SECONDS` | 10, supported 5–60 seconds, existing Beat schedules scans |
| `INVESTIQ_AI_REQUEST_LIMIT` | 5 new/request retries per account per 15 minutes |
| `INVESTIQ_GEMINI_MODEL` | Empty; operator must select an available Gemini model explicitly |
| `INVESTIQ_GEMINI_API_KEY` | Empty SecretStr; backend only; never a Vite variable |

The settings endpoint reports whether generation is configured; it is not a live provider-health probe. Readiness continues to check PostgreSQL/Redis, so a stopped Ollama server cannot take down the core application. Generation failures remain visible as queued/retry/failed jobs with stable error codes. `disabled`, missing Gemini model or missing Gemini key disables new generation while preserving deterministic evidence, old reports and journal access.

To switch later, set `INVESTIQ_AI_PROVIDER=gemini`, `INVESTIQ_GEMINI_MODEL=<selected-model>` and `INVESTIQ_GEMINI_API_KEY=<backend-secret>` in the deployment environment, then recreate API/worker. The Gemini adapter is contract-tested with mocked transport; no live Gemini call or key was used during this phase. When explicitly enabled, it receives private simulation observations and approved lesson excerpts, so deployment privacy/retention arrangements must account for that provider. Keep tracing disabled unless its destination and data handling have been deliberately configured.

Model tags, provider, prompt version, metric/evidence/report versions and lesson-version IDs are recorded. Model weights are not automatically downloaded or updated; changing a provider/model or prompt policy creates distinct report work. Live model availability, prices and quotas are deployment configuration, not guessed constants.

## Data model

Migration **`0011_coach`** adds five tables and the private `investiq_ai` schema. UUID ownership/FKs use restricted deletion; time fields are timezone-aware UTC. Decimal financial calculations remain in the existing valuation engine. These tables do not modify portfolio or ranking values.

| Table | Columns / invariants |
| --- | --- |
| `coach_jobs` | UUID user/contest/valuation-record ownership, provider/model/prompt version, positive generation, SHA-256 evidence fingerprint and frozen JSON snapshot, status, attempts 0–3, stable error code, UUID lease token/expiry, next-attempt/created/updated timestamps; unique source/provider/model/prompt/generation and id/user keys; user/contest/status/due indexes |
| `coach_requests` | Composite user/request-key PK, normalized request fingerprint and same-user job composite FK; multiple explicit retry keys can point to the same deduplicated work |
| `coach_reports` | One row per job, same-user composite FK, frozen typed report JSON and timestamp; immutable |
| `coach_attempts` | Composite job/attempt PK; nullable input/output token counts, latency in ms, estimated USD Decimal and stable error; nonnegative/count checks; incomplete crash telemetry remains unknown |
| `coach_reflections` | UUID owner/contest, UUID request key, 1–2,000-character body and timestamp; unique user/key; immutable append-only entries; private user/contest indexes |
| `investiq_ai.*` | LangGraph's own checkpoint tables/indexes and migration tracking, managed by its pinned PostgreSQL saver rather than SQLAlchemy model autogeneration |

A job trigger checks that the source valuation belongs to the same user and contest and that stored record/run/submission identifiers agree. Source identity, evidence, generation and provider policy cannot change. Terminal jobs are frozen. A deferred constraint requires a succeeded job and exactly one report to agree at commit. Report/request/reflection UPDATE/DELETE operations are rejected. The report row, success transition and audit event are written in one transaction.

`evidence_version=coach-evidence-v1`, `prompt_version=coach-selector-v1` and `format_version=coach-report-v1` identify the initial policies. A report is an immutable historical result, not a continuously changing page: a newer valuation creates a different source job. The evidence snapshot marks whether its source was current/final at request time. Facts include source-record/run references; learning actions retain exact version IDs and excerpts even when the current lesson later changes.

## Workflow, authorization and recovery

`ai/workflow.py` compiles a typed LangGraph:

`authorize → load_evidence → retrieve frozen approved lessons → generate → validate → persist`

At enqueue, the authenticated verified user/session is rechecked under the shared identity locks. The service loads only that user's contest membership and newest successful valuation, builds deterministic observations, snapshots approved lessons and creates a durable DB queue row. Missing submissions/valuations return 409 with a waiting explanation. Identity, rank, prices, facts, model choice and provider URLs are never accepted from the frontend.

Thread IDs are constructed internally from owner/job UUIDs. There is no public checkpoint/thread API. Workers recheck the owner's active/verified account, source membership and evidence fingerprint before running/resuming, before calling the model, and before persisting. Administrators cannot read someone else's report, usage or journal. Signing out does not cancel authorized background work; future reads still require a valid session for the owner. Disabled owners cannot receive newly persisted reports.

The durable queue reuses the existing Celery worker and Beat. Scans process at most one due job, under a PostgreSQL advisory transaction lock, so only one AI call runs globally and a second worker slot remains available for valuation. At most one active job per user is allowed. A short claim transaction gives the job a 120-second lease and increments its attempt count. No user/resource lock is held during model generation; a dedicated coordination transaction holds only the advisory lock.

A whole attempt is bounded at 75 seconds, below the existing 90/120-second Celery soft/hard limits. Provider/framework failures retry at 10/20 seconds, up to three attempts. Unknown failures persist only `coach_processing_failed`, never exception text. Invalid schema or references regenerate rather than checkpointing an invalid completed generation. Restarted workers compile a fresh graph and resume the same PostgreSQL checkpoint with `ainvoke(None)`. Recovered expired leases retain a `worker_lost` attempt record; three expired attempts become terminal failure.

Same-key requests return the original job, even if it later failed; changed contest payload under that key returns 409. New keys for the same active/completed source/provider/prompt reuse that job and bind the new key. After terminal failure, an explicit new request creates generation N+1 with a new thread and a fresh three-attempt budget. The UI retains a key after an ambiguous POST error, and clears it only after a successful acknowledgement. There are no automatic repeated generations of a successful report.

Report persistence is idempotent, with one report and one completion audit per job. A process crash immediately after a provider call but before checkpointing can repeat inference; no provider-level exactly-once billing guarantee is claimed. Usage is recorded where available, otherwise null. Ollama's estimated API fee is zero (hardware/energy costs excluded); Gemini cost remains unknown/null until a reviewed pricing policy is configured. Tokens and latency are available through the owner's usage endpoint.

## API contracts

All endpoints require the authenticated owner. Paths are under `/api/v1/me/coach`; mutations require CSRF and allowed Origin. Create/reflect reject unknown fields.

| Method/path | Result |
| --- | --- |
| GET `/settings` | Configured enabled/provider/model/max-attempts metadata; no credentials or base URL |
| GET `/evidence?contest_id=UUID` | Deterministic source facts, limitations and approved lesson citations; works with AI disabled |
| POST `/jobs` | Verified; `{contest_id}` and UUID `Idempotency-Key`; 202 with queued/existing job |
| GET `/jobs?contest_id=UUID&cursor=…&limit=10` | Own report/job history, optional contest filter, max 20, newest first; filter/user-bound keyset cursor |
| GET `/jobs/{UUID}` | Own status, source snapshot, provider/version metadata and validated report when ready |
| GET `/jobs/{UUID}/usage` | Own attempt/token/latency/cost/error metadata, max three attempts |
| POST `/reflections` | Verified contest member; `{contest_id,body}` and UUID retry key; 201 private append-only reflection; never a model input |
| GET `/reflections?contest_id=UUID&cursor=…&limit=10` | Own contest reflections, max 20, newest first; filter/user-bound cursor |

401 means sign in; 403 covers verification/CSRF; invisible or other-owner reports/evidence return 404. Missing valuation or conflicting keys/active work return 409. Invalid fields/cursors return 422. Disabled/misconfigured generation returns 503; already queued jobs expose stable processing failures through their status rather than leaking raw provider errors. Reflections use a separate 20-per-15-minute write limit; expensive generation uses the configurable AI bucket. Redis failures fail closed.

Example, using an authenticated cookie jar and its CSRF token (substitute your contest UUID):

```bash
curl -b cookies.txt 'http://localhost:8080/api/v1/me/coach/evidence?contest_id=CONTEST_UUID'
curl -b cookies.txt -X POST http://localhost:8080/api/v1/me/coach/jobs \
  -H 'Origin: http://localhost:5173' \
  -H "X-CSRF-Token: $INVESTIQ_CSRF" \
  -H 'Idempotency-Key: 2af02004-c03e-47c8-91b0-23de34f0fc41' \
  -H 'Content-Type: application/json' \
  -d '{"contest_id":"CONTEST_UUID"}'
```

Expected: 202 with `id`, `status:"queued"`, source date/hash and provider/model metadata. Poll `/jobs/{id}` until succeeded or failed. Reuse the same request key for an ambiguous transport error. Expected before first valuation: 409 `coach_evidence_pending`, with no invented report. Interactive contracts are available at `/docs`.

## Start locally

Ollama must be running on the host with the selected model installed:

```bash
ollama list
# If the model is missing:
ollama pull llama3.1:8b
# If the server is not already running:
ollama serve
```

Do not start a second server when the Ollama desktop application already provides it. The application never changes Ollama's bind address, downloads models or enables cloud access automatically.

From the project root, the complete local stack is:

```bash
cd investiq-be
docker compose --profile app up -d --build --wait
```

Compose runs Alembic and a dedicated `coach-setup` job before API/worker startup. The setup calls `AsyncPostgresSaver.setup()` in `investiq_ai`, using autocommit and the saver's own migration tracking; it is safe to rerun. PostgreSQL checkpoint tables are excluded from normal public-schema model comparison. Keep one Beat and the existing worker concurrency of two. Docker Desktop uses `host.docker.internal` to reach the host Ollama; configure `INVESTIQ_OLLAMA_DOCKER_URL` explicitly if your environment needs another reachable origin.

For host development, after the normal PostgreSQL/Redis/Mailpit and migration/seed setup in README:

```bash
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked python -m investiq.coach_cli setup
uv run --locked uvicorn investiq.main:create_app --factory --reload --port 8080
```

Run the existing worker/Beat commands from Phase 6 in separate terminals, or process one due report manually:

```bash
uv run --locked python -m investiq.coach_cli work
```

In another terminal:

```bash
cd investiq-fe
npm ci
npm run dev
```

Open `http://localhost:5173/#/insights`, choose a joined contest and click **Generate coach report** after its first published valuation. Performance pages also link directly to the coach. Queued/retry status refreshes automatically; reports, evidence/citations, history and reflections persist across reloads. Contests awaiting their first market close cannot have a report yet. Current real contest dates/submissions are not changed to make sample reports appear.

## Verification and implementation map

Backend source: `schemas/coach.py`, `models/coach.py`, `services/coach.py`, `adapters/coach.py`, `ai/evidence.py`, `ai/workflow.py`, `api/coach.py`, `coach_cli.py`, migration `0011_coach…`. Wiring: settings, app lifecycle, migration metadata/head, existing Celery scan/Beat, Compose, locked dependencies/hash export and environment examples. Frontend: `features/coach.js`, API helpers, controller lifecycle/Insights replacement and Performance navigation. Browser harness uses an injected deterministic provider and test-only manual worker route, never a production mock setting.

Pinned integrations were verified against [LangChain Ollama](https://docs.langchain.com/oss/python/integrations/chat/ollama), [LangChain Gemini](https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai), [LangGraph PostgreSQL persistence](https://docs.langchain.com/oss/python/langgraph/add-memory) and [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs). Direct additions: LangGraph 1.2.16, PostgreSQL checkpoint saver 3.2.0, langchain-ollama 1.1.0, langchain-google-genai 4.4.2 and psycopg[binary] 3.3.6. `uv.lock` and Docker's hash-locked requirements export record resolved transitive versions.

```bash
# investiq-be
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src
uv run --locked pytest
uv run --locked alembic check

# investiq-fe
npm run check
npm run build
npm run test:e2e
```

Tests cover missing/stale/final evidence, disabled AI, schema/CSRF and ownership checks, concurrent/idempotent requests, final report uniqueness, PostgreSQL checkpoints, resumed provider failures, unknown/duplicate/wrong-category citations, private journal isolation and prompt injection, explicit new generations after bounded failure, provider adapter contracts, worker lease recovery, history cursors and immutable evidence. The live local Ollama smoke test used a disposable database and genuine synthetic valuation records; `llama3.1:8b` produced a validated report in approximately 22 seconds (2,386 input / 131 output tokens). No real account activity was seeded or modified and no live Gemini call was made.

Next: Phase 11, approved document ingestion, pgvector retrieval, cited educational answers and retrieval evaluation.

Final verification: **119 backend tests and 23 Chromium browser tests passed**, with the two coach browser cases rechecked after adding exact-version lesson excerpts. Ruff/format, strict mypy, lock/hash export, frontend syntax/build, Alembic model comparison/offline SQL, disposable downgrade/upgrade with account preservation, repeatable checkpoint setup and wheel contents passed. Rebuilt API/worker are healthy, one Beat is running, readiness reports PostgreSQL/Redis OK, and the production API returns 404 for test-only worker controls. The worker can reach host Ollama and finds the selected model. Desktop/mobile generated-report inspection passed without console errors or horizontal overflow.
