# Ask Martin

Ask Martin is a private learning companion available through the circular avatar at the bottom right of workspace pages.

## Using Martin

1. Sign in and verify your email, then open Martin.
2. Ask naturally: Martin distinguishes explanations, benefits/trade-offs and personal assessments. **My performance** lets you choose a joined contest; otherwise the three contests with the most recent published valuations are available automatically, including in **Learn a concept**.
3. Ask a question, or choose a starter. Enter sends; Shift+Enter adds a line. Questions queue for the existing AI worker, and status updates automatically while the window is open.
4. Read the short conversational reply, expand its Academy citations or review its recorded simulation facts, then ask a follow-up. Each performance citation names its contest and date and marks interim/earlier results.
5. Use **Chat history** to reopen a saved discussion or delete it. **New chat** changes the discussion; changing its topic starts a new conversation. Minimize/Escape keeps the current conversation in memory. After reload, reopen it from history.

Questions and replies are saved privately in PostgreSQL. Unsent drafts remain in memory and clear on reload/sign-out/account change. Another account, including an administrator, cannot read these conversations. Deleting a chat also deletes its questions, frozen evidence and answers. The model receives the question, up to three previous turns, approved lesson passages and the learner's owned simulation observations from the selected contest or recent results. Account email, password, account name, decision journal, quiz answer keys and other learners' portfolios are not supplied as context. The question itself is sent as written.

## Grounding and limits

Martin interprets the latest question in conversation and writes a short answer grounded in relevant approved passages/facts. A definition, a benefits question and a personal assessment receive different responses; follow-ups use up to three previous question/answer pairs. General answers cite lessons; personal reviews require owned results or an explicit missing-results status. The server validates source IDs and checks personal numeric claims against cited evidence. Broad summaries can cite up to six sources. If a reply omits a citation for an exact metric, the server can attach its frozen source from the same already-cited contest and snapshot date; it never borrows metrics from another snapshot or accepts an absent number. Missing personal citations or unsupported numbers trigger one correction within the same provider deadline; a draft that still fails validation is not saved as an answer. Model-written interpretations can still be mistaken. Source links open the original lesson/performance page. Earlier saved replies retain their original wording; new questions use this conversational behavior. An unsupported question receives an explicit insufficient-evidence/out-of-scope answer. The seeded Academy curriculum bounds the educational topics currently available. Additive version-2 passages define diversification, stocks/bonds/ETFs, benchmarks, returns and compounding; earlier lesson/report/quiz versions are preserved.

Performance sources include the latest saved snapshot, drawdown/concentration/contribution observations and up to three earlier daily closes per selected contest. Comparisons across contests keep their individual snapshot dates; Martin does not manufacture a combined portfolio return. No valuation means a clear waiting response. Locked portfolios do not establish sales, motives or the causes of returns. No live market data, external web retrieval, journal access or portfolio mutations are enabled.

## Running locally

Use the normal backend Compose app profile, including one Beat scheduler and its worker:

```bash
cd investiq-be
docker compose --profile app up -d --build --wait
```

Install the configured Ollama model on the host (`ollama pull llama3.1:8b`) and keep Ollama running. Compose reaches it through the existing `INVESTIQ_OLLAMA_DOCKER_URL`; host execution uses `INVESTIQ_OLLAMA_BASE_URL`. Start the frontend normally with `npm run dev` in `investiq-fe`.

Martin uses `INVESTIQ_AI_PROVIDER`, `INVESTIQ_OLLAMA_MODEL`, `INVESTIQ_AI_TIMEOUT_SECONDS` and the existing optional Gemini model/key settings. Gemini is callable through the same interface when configured; no Gemini call or paid key is required for local development. `INVESTIQ_MARTIN_REQUEST_LIMIT` defaults to 20 questions per account per 15 minutes; control actions have a separate limit. One pending question per account and a bounded global queue protect local inference.

The scheduler checks Martin's queue every `INVESTIQ_AI_SCAN_SECONDS` (default 10 seconds). Failed questions can be retried explicitly up to three total attempts. Expired worker leases become retryable failures. Cancellation stops waiting and discards late answers; it may not stop an already-running remote inference request. Provider failures leave saved history available. Application logs never include question/answer bodies or raw provider errors.

In the disposable manual sandbox, send a question, then use **Answer one queued Martin question** on its local control panel. The sandbox deliberately uses manual processing instead of the normal worker, which points at the normal database. Restart an old sandbox to load the new API; its temporary data is discarded when stopped.

## API and storage

All routes require an active cookie session. Mutations also require CSRF and allowed browser Origin; question creation/retry requires verified email.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/me/martin/settings` | Configured provider availability |
| `POST /api/v1/me/martin/turns` | Queue a question, with UUID `Idempotency-Key` |
| `GET /api/v1/me/martin/conversations` | Private paginated chat history |
| `GET /api/v1/me/martin/conversations/{id}` | Private paginated questions/answers |
| `POST /api/v1/me/martin/turns/{id}/cancel` | Cancel a queued/running question |
| `POST /api/v1/me/martin/turns/{id}/retry` | Retry the latest failed question |
| `DELETE /api/v1/me/martin/conversations/{id}` | Delete a chat and all its turns |

A question contains `question` (1–1000 characters), optional `conversation_id`, `mode` (`learning`/`performance`) and optional performance `contest_id`. Ownership is always derived from the session. Scope stays fixed within a conversation. UUID request keys replay the same result while the conversation exists; changing the payload with the same key returns 409. A conversation allows up to 100 questions. Lists use user/scope-bound cursors, with at most 20 items per page.

Migration `0012_martin` adds `martin_conversations` and `martin_turns` with same-owner composite foreign keys, unique retry keys, lease/status/answer constraints and cascading chat deletion. Each turn freezes its evidence and provider/model policy. The worker commits short claims before inference, rechecks account/membership access before inference and persistence, validates cited IDs, and writes the complete answer atomically. Usage stores token counts/latency when supplied; inference is at least once after a process failure, not exactly once billing.

The frontend lives in `src/features/martin.js` / `src/styles/martin.css`, mounted outside the page root so page re-renders do not replace the editor. Question retries after a lost HTTP response reuse their original key, and account generations discard late responses after logout/account changes.

## Validation

- `npm run check`, `npm run build`, `npm run test:e2e` in `investiq-fe`.
- `uv run --locked pytest`, `ruff check .`, and `mypy src` in `investiq-be`.
- Real Ollama smoke tests use a disposable database, covering definitions, benefits, automatic private portfolio assessments and contextual follow-ups without adding user activity to the normal database.

Backend tests cover concurrency/idempotency, context, citations, malformed input/cursors, CSRF, ownership, missing/results evidence, cancellation, retries, worker interruption and account deactivation. Browser tests cover keyboard/mobile use, sending, lost-response replay, citations, follow-ups, history after reload, deletion and isolation across accounts. Gemini configuration support is implemented; live Gemini behavior requires a deployment-specific smoke test with its production model/key.
