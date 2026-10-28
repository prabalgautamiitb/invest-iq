# Community feeds

Community metadata is discoverable; posts and replies require current membership.
Any active, verified account may create or join a community. Creation automatically
adds the creator once. There is no approval or invitation requirement in this version.
The creator is labelled in their own community list, without exposing their identity
to other viewers. Administrator moderation retains access to reported content.

## Experience

- `/#/social`: My feed, newest first across joined communities. The composer requires
  an explicit joined community (a single available community is selected automatically).
- `/#/social/discover`: search discoverable communities by name or description and join.
- `/#/social/groups`: communities joined or created by the current account.
- `/#/social/group/{id}`: metadata preview for non-members; feed, polls and composer
  after joining. Leaving removes access without deleting authored posts.
- `/#/social/{post-id}`: discussion and replies, subject to the same membership rule.
- `/#/social/saved`: private saves that the viewer currently has permission to read.
- `/#/social/create`: create a community with a name and description.
- `/#/social/lounge`: existing ungrouped general discussions, still publicly readable.

Posts are plain text and may be discussions, investment ideas, market discussions,
or polls. Existing likes, final votes, replies, reports, author deletion and moderation
continue to work. Drafts are scoped to account and route; ambiguous post submissions
retain their original payload and idempotency key, including poll closing times.
No sample activity or member counts are invented.

## API additions

Paths are relative to `/api/v1/community`.

| Endpoint | Behaviour |
| --- | --- |
| `GET /posts?scope=joined` | Only posts from the caller's current communities; empty for guests |
| `GET /posts?scope=accessible` | Default: public general posts plus accessible community posts |
| `GET /posts?scope=public` | Only ungrouped general discussions |
| `GET /posts?group={id}` | Requires membership; non-members receive `403 membership_required` |
| `GET /groups?scope=all&q=…` | Search discoverable metadata |
| `GET /groups?scope=joined` | Caller memberships; requires sign-in |
| `GET /groups?scope=created` | Caller-created communities; requires sign-in |

Group responses include `visibility: "members"`, `joined`, `owned`, real member counts,
and visible root-post counts. Post responses include `group_name` so feed labels do
not depend on loading every directory page. Filters and membership access are applied
before pagination. Cursors include scope, search/filters and viewer identity.

The existing create-group, membership, post/comment and interaction endpoints remain.
Group creation, joins and leaves are audited. No schema migration or external service
is required; rebuild the API/worker/scheduler using the normal Compose command.

## Access and privacy

Membership is checked on root posts, comment details, comment lists, writes,
idempotent replay, reactions, votes, reports and saved-post reads. Leaving excludes
that community from My feed and Saved posts immediately on the next request, even
with an old cursor. Saved flags and authored content remain stored so rejoining
restores access. Member-only posts never appear in anonymous general feeds.

The public-profile setting controls display names, independently of membership.
Account emails, member identities, individual votes, saved lists and profile photos
are not exposed. Group metadata and aggregate activity counts remain discoverable.

## Validation

`tests/test_community.py` covers anonymous/member isolation, direct and saved reads,
reply access, joining/leaving, filtered pagination, cursor scope, ownership metadata,
polls, idempotency, reporting, moderation and database guards. Browser tests cover
two-account discovery/join/feed access, member posts and replies, leaving/rejoining,
creation, search, polls, retries, public general discussions and mobile layout.
