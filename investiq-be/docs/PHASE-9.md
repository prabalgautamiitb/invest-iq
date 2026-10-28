# Phase 9 — Community

## Goal and decisions

Connect the existing Community screen to shared PostgreSQL activity: public posts and replies, likes, private saved posts, polls, public learning groups, reports and administrator moderation. Phases 0–8 are prerequisites. No dependency or external service is added.

Communities are discoverable by name and description, but their posts, replies,
reactions and polls require current membership (or administrator access for
moderation). Verified accounts can join openly, and creators join automatically.
My feed contains only joined communities; saved lists also exclude communities
that the viewer has left. Direct post/reply URLs enforce the same rule. Existing
ungrouped discussions remain public in General discussion. Leaving does not delete
posts or saves; rejoining restores access. Invitations, attachments, rich text,
nested replies, editing, reputation and automatic moderation remain outside this slice.
See [the current community feed contract](COMMUNITIES.md).

The feed starts empty. Browser fixtures, sample authors, likes, poll totals, memberships and old local posts are never imported. No community activity is seeded. Create a genuine community through the Community screen to start a discussion; test data exists only in disposable test databases. Prices and portfolios remain simulated, and community participation does not award XP, coins or contest ratings.

## Schema and ownership

Migration `0010_community`, after `0009_rewards`, adds eight tables. Identifiers are UUID, timestamps are UTC with timezone, counts are integers. Foreign keys restrict deletion. Existing users, profile privacy and audit events are reused.

| Table | Purpose and constraints |
| --- | --- |
| `community_groups` | Unique name (3–80 characters), description (1–500 at API boundary), creator FK and created timestamp; discoverable metadata and member-only content are an API contract, not a user-selectable privilege |
| `community_members` | Composite group/user PK, representing an explicit current membership; creators count only after insertion |
| `community_content` | UUID author FK, request UUID/hash, optional root parent and group FKs, kind, 1–4,000-character body, JSONB options, poll closing time, state and creation time; unique author/request key; author/parent/group/time indexes |
| `community_reactions` | Composite content/user PK; one like per account per content |
| `community_saves` | Composite content/user PK; only root posts may be saved through the API; lists are private |
| `community_votes` | Composite content/user PK and zero-based option; one immutable final vote per account per poll |
| `community_reports` | UUID content/reporter FKs, 5–500-character reason, resolution flag and timestamp; unique content/reporter pair |
| `community_moderation` | Decision evidence with content/moderator FKs, hide/restore/dismiss action, 5–500-character reason and timestamp; ordinary APIs cannot modify or delete decisions |

Content CHECKs enforce allowed kinds and states, comment/parent equivalence, poll/closing-time equivalence and 2–6 poll options versus no options for other content. Poll options are stored on their immutable parent rather than in a separate options table; a trigger validates their strings, lengths, uniqueness and vote indexes. No floating-point accounting is involved.

A content trigger freezes body, author, parent, group, options, closing time, creation time and retry evidence. Only state may change; author deletion is terminal, and hard deletion is blocked. Replies must refer to a visible root in the same group. Polls must close after creation and within 30 days. A vote trigger independently verifies a visible unexpired poll and valid option, locks that poll and rejects changes/deletion of accepted votes.

`CommunityService` owns each SQLAlchemy transaction, comparable to a transactional application service in Spring. Mutations reauthenticate and lock the current user/session before checking membership, ownership or current administrator role. Post creation and all interactions are serialized for the same user. Poll and moderation operations additionally lock their content row. Public reading never returns account email, author/user IDs, holdings, member identities, reporter identities or other people's individual votes/saves.

## Privacy and moderation

Author names are resolved against **current** `user_privacy.public` on each read. Other viewers see `Private learner` by default; authors see their own display name. Changing the preference affects old posts and replies too. This is a display-name preference, not a private-content setting: group content requires membership, while general discussions remain public. Names and private state are kept in memory on the frontend and cleared on account changes.

Authors may soft-delete visible content. Verified accounts may report visible posts or replies once per content; retries do not duplicate reports. Reports are private to current administrators. Hide excludes content from feeds, saved lists, details and interaction APIs. Hiding/deleting a root also makes its replies unavailable. Restore can reveal moderator-hidden content; it cannot recover author-deleted content. Dismiss resolves reports without changing content visibility. Every decision stores its reason and an audit event in the same transaction. The moderation screen includes reviewed reports so an administrator can restore hidden content later.

Every mutation requires cookie authentication, CSRF and allowed Origin. Writes share a separate per-user Redis bucket, default **60 writes per 60 seconds**, controlled by `INVESTIQ_COMMUNITY_WRITE_LIMIT` and `INVESTIQ_COMMUNITY_RATE_WINDOW_SECONDS`. Rate-limit failures fail closed, with 429/Retry-After for exhausted limits. Administrator privileges are rechecked from PostgreSQL; frontend role flags do not grant access.

## API contracts

All paths below are relative to `/api/v1/community`. Paginated responses have `{items, next_cursor}`. Feed/replies default to 20, maximum 50; groups/reports default to 20, maximum 100. Cursors bind their filters and current viewer; changing accounts or filters requires restarting pagination. Listings are live views rather than immutable snapshots.

| Method/path | Contract |
| --- | --- |
| GET `/posts?kind=idea&group=UUID&saved=true&cursor=…&limit=20` | Visible root posts, newest first; category/group optional; saved requires sign-in and includes only the caller's saved posts |
| GET `/posts/{id}` | Visible post/reply; includes safe author label, counts, current viewer flags and poll totals |
| POST `/posts` | Verified; `{body,kind,group_id?,options?,closes_at?}` and UUID `Idempotency-Key`; 201 |
| GET/POST `/posts/{id}/comments` | Paginated newest-first replies; creation takes `{body}` plus UUID retry key; group membership follows the root |
| PUT `/posts/{id}/like`, `/posts/{id}/save` | Verified; explicit `{enabled:true/false}`, safe to retry; saves accept root posts |
| PUT `/posts/{id}/vote` | Verified; `{option:0}`; exact retries succeed, changing an accepted vote returns 409; closed polls reject new votes |
| DELETE `/posts/{id}` | Verified author; soft deletion; no hard-delete operation |
| POST `/posts/{id}/reports` | Verified; `{reason}`; deduplicated per reporter/content |
| GET `/groups?cursor=…`, `/groups/{id}` | Public definitions, genuine member count, caller's joined flag; groups sorted by name/UUID |
| POST `/groups` | Verified; `{name,description}`; 201 `{id}`; exact same creator/name/description retries return the group; conflicting names return 409 |
| PUT `/groups/{id}/membership` | Verified; `{enabled:true/false}` join/leave, safe to retry |
| GET `/reports?cursor=…` | Current administrator; unresolved reports first, then oldest time/UUID; includes reviewed records, content state and report reason |
| POST `/posts/{id}/moderation` | Verified current administrator; `{action:"hide"|"restore"|"dismiss",reason}`; stores decision/audit and resolves associated reports atomically |

Unknown mutation fields are rejected. Missing/invisible content returns 404; invalid input/cursors return 422; unverified participation and role/ownership/membership violations return 403; retry payload conflicts and unavailable poll votes return 409. A stale signed-in cookie is rejected rather than silently treated as a guest.

Creating a post/reply binds a UUID retry key to the normalized payload and parent. Exact retries return the same visible content; changing the payload under that key returns 409. If content has since been removed, retry returns 404 without revealing the old text. Unique keys plus user locks also protect simultaneous requests. Group-name allocation uses a short advisory lock and uniqueness constraint. Likes, saves and memberships use explicit set/clear semantics rather than toggles, so repeated requests cannot invert intent.

Example: with an authenticated cookie jar `cookies.txt` and its CSRF token in `$INVESTIQ_CSRF`, create a public discussion (reuse the UUID when retrying this exact request):

```bash
curl -b cookies.txt -X POST http://localhost:8080/api/v1/community/posts \
  -H 'Origin: http://localhost:5173' \
  -H "X-CSRF-Token: $INVESTIQ_CSRF" \
  -H 'Idempotency-Key: 0b1c9fd4-a8aa-4bf7-b68b-72c4a8345bd2' \
  -H 'Content-Type: application/json' \
  -d '{"body":"What did diversification teach you in your last simulation?","kind":"discussion"}'

curl 'http://localhost:8080/api/v1/community/posts?limit=20'
```

Creation returns 201 with a server UUID, creation time, body, safe author label, `own:true`, zero initial counts and empty poll fields. A separate guest request returns the same public text with `Private learner` unless the author has explicitly enabled a public profile. Interactive schemas/examples are also available at `/docs`.

## Start, use and verify

From the project root:

```bash
cd investiq-be
docker compose --profile app up -d --build --wait
```

Compose applies migrations before starting the API/worker. The existing market/learning/rewards definition seeds remain; community needs no fixture seed or scheduler. Open `http://localhost:8080/docs` or `http://localhost:8080/api/v1/community/posts` (initially an empty page).

In a second terminal:

```bash
cd investiq-fe
npm ci
npm run dev
```

Open `http://localhost:5173/#/social`. Sign in and verify email through Mailpit at `http://localhost:8025`. Create a discussion or public group, publish a poll, follow replies and use Saved. A current admin sees Moderation; the existing `python -m investiq.cli set-role EMAIL admin` operator command requires a verified account and revokes its sessions. Do not promote normal accounts automatically.

For host API development, use the standard `.env` setup in README, start PostgreSQL/Redis/Mailpit, then:

```bash
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked uvicorn investiq.main:create_app --factory --reload --port 8080
```

Tests use disposable real PostgreSQL databases and the local Redis/Mailpit infrastructure:

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

The backend suite covers public/private DTOs, current privacy changes, verified/CSRF writes, group membership and leave behavior, root/reply visibility, duplicate/concurrent creation, reaction/save retries, final concurrent votes, poll expiry, moderation permissions/current roles and audit evidence, pagination, database guards and independent write limits. Browser coverage includes persistence/reload, no demo import, public pseudonyms and private vote/save flags, group creation, an accepted poll POST followed by a deliberately lost response and same-key retry, preserved draft text, mobile overflow, feed failure/retry and administrator hide through the UI.

New files: `models/community.py`, `schemas/community.py`, `services/community.py`, `api/community.py`, migration `0010_community…`, `tests/test_community.py`, frontend `features/community.js` and `tests/browser/community.spec.js`. Modified wiring: app lifecycle/router, Alembic metadata/head, rate-limit settings/helper, frontend API/controller lifecycle/check script and privacy/terms copy, plus project docs.

Next: Phase 10, deterministic report evidence followed by the checkpointed AI coach workflow.

Verification completed: 111 backend tests and 21 Chromium browser tests passed. Ruff/format, strict mypy, lock validation, frontend build/syntax, Alembic comparison/offline SQL, disposable downgrade/upgrade preserving existing identity data, wheel packaging and container readiness checks passed. Live desktop/mobile Community inspection showed no console errors or mobile overflow.
