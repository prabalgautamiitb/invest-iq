# Phase 7 — Learning

## Goal and prerequisites

Add a complete learning flow to the existing modular monolith: published courses and lessons → enrollment → quiz submission → immutable attempt/answer evidence → first completion, XP, achievements and streaks. Phases 1–6, PostgreSQL and Redis are prerequisites. This phase introduces no dependencies and uses the existing pinned FastAPI, Pydantic and SQLAlchemy stack.

`LearningService` owns transactions, like a Spring service with `@Transactional`. Pydantic models validate API contracts, while SQLAlchemy maps database entities. The router handles transport, authentication and rate limiting; clients never calculate XP or submit a user ID or score.

## Decisions

- The development curriculum contains two courses, six lessons and two questions per lesson. Content is authored for this simulation, and explains existing accounting and evidence policies. It is not a live investing course or personalized advice.
- Course/lesson identities are stable. Lesson versions contain the immutable text and versioned question bank. A question has a stable key within its version, options, correct option and explanation. JSONB stores the small question bank; each submitted answer has its own relational row.
- Current lesson reads return the highest published version. Updates require inserting a new version, never editing old text or keys. There is no authoring/upload API in this phase. Operators must validate and review new content before inserting a version; draft publishing and content retirement are deferred.
- Every question must be answered correctly to pass. Lessons may be taken in any order after enrollment. Failed attempts and retakes are retained. Answer explanations are intentionally available after submitting a complete quiz.
- Each stable lesson awards 25 integer XP at its first pass. Different quiz versions and retakes cannot award it again. Enrollment and course completion add no extra XP; no multiplier or coins are awarded.
- A first completion records one activity day using **Asia/Kolkata**. Multiple completions that day count as one day. Retaking completed lessons does not create activity days. The current streak remains active if the latest activity was today or yesterday, and becomes zero after a full missed day. Longest streak and earned achievements remain historical.
- Achievements: `first_lesson`, `first_course` (all current lessons in one course completed), `three_day_streak`. Each is awarded once per user. New course lessons do not revoke historical achievements.
- Published content and learning evidence are immutable at the database level. Administrative correction, deletion and retention procedures need a separate reviewed migration/policy.
- Enrollment and submission require a verified account, cookie authentication, Origin/CSRF checks, and Redis rate limits. Read-only account progress requires a valid signed-in session. Public lesson responses omit correct answers and explanations. Attempts and progress are private to the authenticated learner.

## Schema and ownership

Migration: `0007_learning`. All identifiers use UUID; timestamps use `timestamptz` in UTC. Learning-day dates are explicitly IST calendar dates. Course content belongs to the platform; all learner records belong to their `user_id`.

| Table | Columns and purpose | Keys, constraints and indexes |
| --- | --- | --- |
| `learning_courses` | UUID id, slug varchar(80), title varchar(160), description varchar(1000) | PK id; unique slug |
| `learning_lessons` | UUID id/course_id, integer position/xp | FK course RESTRICT, indexed course; unique course/position; positive position, XP 1–1000 |
| `learning_lesson_versions` | UUID id/lesson_id, integer version, title, JSONB paragraphs/questions, published_at | FK lesson RESTRICT and indexed; unique lesson/version and id/lesson; positive version, 1–20 questions |
| `learning_enrollments` | UUID user_id/course_id, enrolled_at | Composite PK user/course; FKs RESTRICT; repeated enrollment is a no-op |
| `learning_quiz_attempts` | UUID id/user_id/lesson_id/version_id/idempotency_key, request_hash varchar(64), integer correct_count/total/xp_awarded, passed boolean, submitted_at | Unique user/key and id/user/lesson; composite FK version/lesson; user/lesson FKs RESTRICT; user and submitted_at indexes; bounded score and XP, passed exactly when all correct |
| `learning_quiz_answers` | UUID attempt_id, question_key varchar(40), integer choice, correct boolean | Composite PK attempt/question; FK attempt RESTRICT; choice 0–9 |
| `learning_completions` | UUID user_id/lesson_id/attempt_id, completed_at | Composite PK user/lesson; unique attempt; composite attempt/user/lesson FK; user/lesson FKs RESTRICT |
| `learning_xp_events` | UUID id/user_id/lesson_id/attempt_id, integer amount, created_at | Unique user/lesson and attempt; composite attempt/user/lesson FK; indexed user; positive bounded amount, FKs RESTRICT |
| `learning_days` | UUID user_id, local_date DATE, created_at | Composite PK user/date; user FK RESTRICT |
| `learning_achievements` | UUID user_id, code varchar(40), awarded_at | Composite PK user/code; approved code CHECK; user FK RESTRICT |

An immutable trigger rejects updates and deletes on all ten tables. Deferred constraint triggers on attempts, answers, completions and XP events validate complete answer evidence and scores at commit. A positive XP award must match the lesson XP and have both completion and ledger evidence. Zero-XP attempts cannot create completion or XP rows. Composite foreign keys prevent evidence from referring to another user's attempt or a different lesson.

## Transactions, concurrency and retries

1. Begin a transaction and lock the current user, then session, using the shared identity helper. Recheck session expiry/revocation and verification. The user lock serializes learning writes across browser tabs and sessions.
2. Look up `(user, Idempotency-Key)`. An identical canonical lesson/version/answer set returns the original immutable result, including its original XP award. Reordering answers is equivalent. Reusing the key for another payload returns 409.
3. Load current lesson version and require enrollment. Reject stale versions with 409, except exact retries of already accepted attempts. Validate an exact, distinct question-key set and option bounds.
4. Score against the persisted answer key and store attempt/answer rows. Only the first pass inserts completion, XP, day and any newly earned achievements.
5. Commit all rows together. The immutable unique keys are a second defense against duplicate awards. Any validation or persistence failure rolls the transaction back.

No Celery job is necessary: these small deterministic updates complete atomically in the request. XP total is the sum of immutable integer events, with no editable cached balance. Coin issuance belongs to Phase 8.

## API contracts

| Method and path | Access | Result |
| --- | --- | --- |
| GET `/api/v1/courses?limit=20&cursor=…` | Public | `items` of courses with ordered lesson summaries, `next_cursor` |
| GET `/api/v1/lessons/{id}` | Public | Current version UUID/number, text paragraphs, XP, question keys/prompts/options |
| POST `/api/v1/courses/{id}/enrollment` | Verified + CSRF | `{"message":"Enrolled"}`; retry safe |
| POST `/api/v1/lessons/{id}/attempts` | Verified + CSRF + UUID Idempotency-Key | Immutable scored attempt, per-question feedback and XP awarded in that attempt |
| GET `/api/v1/lessons/{id}/attempts?limit=20&cursor=…` | Own account | Private attempt page, including original version and feedback |
| GET `/api/v1/me/learning` | Own account | XP, completed lesson UUIDs, enrollment UUIDs, current/longest streak, last date, timezone, achievements |

Pagination is ascending UUID with opaque cursors, limit 1–50. Attempt cursors are bound to the authenticated user and lesson; timestamps in each item identify submission time. Errors use the existing envelope and request IDs: 401 no session, 403 verification/CSRF, 404 missing content, 409 enrollment/version/idempotency conflict, 422 invalid question sets/options and 429 rate limit.

Example submission after logging in, verifying and enrolling (cookie/CSRF from the identity flow):

```bash
curl http://localhost:8080/api/v1/courses
curl http://localhost:8080/api/v1/lessons/LESSON_UUID
curl -b cookies.txt -X POST \
  -H "X-CSRF-Token: $CSRF_TOKEN" \
  http://localhost:8080/api/v1/courses/COURSE_UUID/enrollment
curl -b cookies.txt -X POST \
  -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H 'Idempotency-Key: 223b8f2e-734a-4569-8c22-f3b096036b90' \
  -H 'Content-Type: application/json' \
  -d '{"version_id":"VERSION_UUID","answers":[{"question_key":"capital","choice":0},{"question_key":"fee","choice":0}]}' \
  http://localhost:8080/api/v1/lessons/LESSON_UUID/attempts
curl -b cookies.txt http://localhost:8080/api/v1/me/learning
```

Replace UUID placeholders using the catalogue and lesson response. A first passing attempt includes `correct_count: 2`, `total: 2`, `passed: true`, `xp_awarded: 25`, a timestamp and explanations. Retrying its exact key returns the same attempt; a new passing attempt awards zero. New accounts return zero XP, no completions/achievements and zero streaks. Guest localStorage is never uploaded.

## Implementation map and frontend

- `models/learning.py`, migration 0007: content, enrollment and immutable learning evidence.
- `schemas/learning.py`, `api/learning.py`: typed public/private contracts and protected writes.
- `services/learning.py`: scoring, idempotency, XP, streak and achievement transactions.
- `services/learning_seed.py`, `learning_cli.py`, `data/learning_curriculum_v1.json`: validated, deterministic, retry-safe development content seed. An advisory transaction lock serializes seed invocations; it does not create users or activity. Seed disabled in production.
- `main.py`, `db/session.py`, `migrations/env.py`, `compose.yaml`: lifecycle wiring, readiness head and container initialization.
- `investiq-fe/src/features/learning.js`, API helpers, app routing: Academy catalogue, lesson text, enrollment, quizzes, feedback, attempt history, saved progress and achievements. Signed-in profile shows these records and links to actual contest history/settings. Guest readers can browse content; submitting requires sign-in and verification.
- Controller account/route generations discard stale asynchronous results. Retryable writes keep the same key and answers after network errors. Loading, failures, empty catalogues and unavailable lessons show explicit states without fixture progress.
- Tests use real PostgreSQL, Redis, and disposable browser-test databases. Content seed is applied explicitly; no startup request generates learning activity.

## Start and verify

From the project root:

```bash
cd investiq-be
docker compose --profile app up -d --build --wait
```

This runs migrations, market and learning seeds, API, worker and one Beat scheduler. API docs: http://localhost:8080/docs. Existing local account/contest data is preserved.

For host development, use a separate API process instead of the container API:

```bash
cd investiq-be
uv sync --locked
docker compose up -d --wait postgres redis mailpit
uv run --locked alembic upgrade head
uv run --locked python -m investiq.market_cli
uv run --locked python -m investiq.learning_cli
uv run --locked uvicorn investiq.main:create_app --factory --reload --host 127.0.0.1 --port 8080 --no-access-log
```

Start the frontend in another terminal:

```bash
cd investiq-fe
npm ci
npm run dev
```

Open http://localhost:5173/#/academy, register or sign in, verify through the local inbox at http://localhost:8025, enroll and complete a quiz. Refresh the page to see saved progress.

Checks:

```bash
cd investiq-be
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest -q
uv run --locked alembic check

# In investiq-fe:
npm run check
npm run build
npm run test:e2e
```

Verification: **92 backend tests and 14 Chromium browser tests passed**. New tests cover exact/reordered retries, conflicting keys, concurrent duplicate/distinct attempts, no repeated XP, invalid/forged answers and XP, verification/CSRF, cross-user progress/history/cursor isolation, version preservation, IST midnight/gaps, course/streak achievements, immutable rows, partial evidence rollback, seed idempotency and genuine empty accounts. Browser tests cover enrollment, incorrect/correct answers, retakes, reload persistence, profile achievements, separate accounts, failure/retry states and guest read-only behavior.

Additional verification: Ruff lint/format, strict mypy, lock validation, offline migration SQL, Alembic model comparison, a disposable seeded PostgreSQL downgrade/upgrade round trip, wheel asset packaging and the hash-locked Docker build passed. The rebuilt API/worker are healthy, Beat is running, readiness is OK and the live catalogue returns the seeded content.

## Limits and next phase

This phase ships the small development curriculum, not the illustrative 180-lesson library. There are no externally hosted videos, content editor, per-answer autosave, timed exams, certificates, coin awards or streak multipliers. Publishing more content needs editorial review and a new immutable version. The existing market fixture coverage remains October 14–16, 2026. Community, rewards and AI integrations retain their later phases.

Next is Phase 8: auditable virtual coin earnings, tiers, catalogue/inventory and idempotent sandbox redemption/history. Real fulfillment remains disabled.
