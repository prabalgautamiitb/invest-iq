# Dependency verification

Verified against PyPI's published package metadata during implementation (18 October 2026 client date). The full dependency tree, distribution hashes and platform markers are in `uv.lock`; `uv sync --locked` rejects a stale lock. Resolver success and HTTP/PostgreSQL/Redis tests verify this selected combination locally on Python 3.13.5.

| Package | Pin | Official release metadata |
|---|---|---|
| FastAPI | 0.143.5 | [PyPI](https://pypi.org/project/fastapi/0.143.5/) |
| Uvicorn | 0.54.0 | [PyPI](https://pypi.org/project/uvicorn/0.54.0/) |
| Pydantic | 2.14.1 | [PyPI](https://pypi.org/project/pydantic/2.14.1/) |
| pydantic-settings | 2.16.0 | [PyPI](https://pypi.org/project/pydantic-settings/2.16.0/) |
| SQLAlchemy asyncio | 2.1.5 | [PyPI](https://pypi.org/project/SQLAlchemy/2.1.5/) |
| asyncpg | 0.32.0 | [PyPI](https://pypi.org/project/asyncpg/0.32.0/) |
| Alembic | 1.20.0 | [PyPI](https://pypi.org/project/alembic/1.20.0/) |
| Redis Python client | 8.1.0 | [PyPI](https://pypi.org/project/redis/8.1.0/) |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 | [pytest](https://pypi.org/project/pytest/9.1.1/), [pytest-asyncio](https://pypi.org/project/pytest-asyncio/1.4.0/) |
| HTTPX | 0.28.1 | [PyPI](https://pypi.org/project/httpx/0.28.1/) |
| Ruff / mypy | 0.17.1 / 2.4.0 | [Ruff](https://pypi.org/project/ruff/0.17.1/), [mypy](https://pypi.org/project/mypy/2.4.0/) |
| Hatchling | 1.32.4 | [PyPI](https://pypi.org/project/hatchling/1.32.4/) |

Implementation references: [FastAPI container deployment](https://fastapi.tiangolo.com/deployment/docker/), [SQLAlchemy async interfaces](https://docs.sqlalchemy.org/en/21/orm/extensions/asyncio.html), [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/), [Alembic async cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic), [HTTPX ASGI transport](https://www.python-httpx.org/advanced/transports/#asgi-transport).

No deprecated LangChain imports are included. Verify and pin AI/worker dependencies when those phases are implemented. Docker uses maintained PostgreSQL 17 and Redis 8 major image lines for development; promotion to production requires deliberately selected immutable image digests.

This workspace has no Git repository at its root; the lockfile is delivered on disk alongside the source. Add `investiq-be/uv.lock` when committing these files to your repository.

## Container dependency installation

`requirements.lock` is a hash-bearing production export of `uv.lock`. The container uses pip's `--require-hashes` mode to install that export, then runs source through `PYTHONPATH=/app/src`. This avoids a uv downloader stall observed in the local Linux container while preserving the same package pins and distribution integrity checks. Local development continues to use uv.

After intentionally changing dependencies, regenerate both artifacts:

```bash
uv lock
uv export --locked --no-dev --no-emit-project --format requirements-txt -o requirements.lock
```

Commit both lock artifacts with `pyproject.toml`. Do not edit the exported requirements by hand.

## Phase 2 additions

Verified published releases: [argon2-cffi 25.1.0](https://pypi.org/project/argon2-cffi/25.1.0/), [email-validator 2.3.0](https://pypi.org/project/email-validator/2.3.0/), [Mailpit v1.31.6](https://github.com/axllent/mailpit/releases/tag/v1.31.6), and [Playwright 1.64.1](https://www.npmjs.com/package/@playwright/test/v/1.64.1). Backend pins and transitive hashes are updated in both lock artifacts; browser dependencies are pinned in the frontend package lock. References: [Argon2 API](https://argon2-cffi.readthedocs.io/en/stable/api.html), [Pydantic email types](https://docs.pydantic.dev/latest/api/networks/#pydantic.networks.EmailStr), [Playwright web servers](https://playwright.dev/docs/test-webserver).

## Phase 3

No new dependency or version change. The existing lockfiles remain authoritative; Python standard-library Decimal/zoneinfo/Protocol/resources support the new code. Fixture JSON and reviewed calendar assets are packaged inside `investiq.data` and copied into the Docker runtime.

## Phase 4

No packages added or upgraded. Contests reuse the pinned FastAPI/Pydantic/SQLAlchemy/PostgreSQL/Redis stack, with the existing HTTPX/pytest and Playwright verification setup. `uv.lock`, hash-verified production requirements and the npm dependency lock remain unchanged. No worker or AI dependency is introduced before its runnable phase.

## Phase 5

No package additions/upgrades. Deterministic portfolio calculations use Python Decimal; database constraints/triggers use the existing PostgreSQL/SQLAlchemy/Alembic stack. Existing lockfiles remain valid. Celery and valuation scheduling are deferred to Phase 6, where they will have a runnable use.

## Phase 6: Celery and stable Redis transport

Verified Celery **5.6.3** as the current stable release using [PyPI](https://pypi.org/project/celery/5.6.3/) and its [stable Redis guide](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html). Pin `celery[redis]==5.6.3`, `kombu==5.6.2`, and `redis==6.4.0`. [Kombu 5.6.2 official metadata](https://pypi.org/pypi/kombu/5.6.2/json) constrains its Redis extra to a client below 6.5; the previous client 8.1.0 caused resolution to a prerelease transport. The selected stable set resolves on Python 3.13 and passes real Redis/Celery and existing identity/portfolio tests. The Redis server image remains version 8.

Scheduling follows [Celery periodic-task documentation](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html); late acknowledgement and retry behavior follow the [task guide](https://docs.celeryq.dev/en/stable/userguide/tasks.html). One Beat scheduler, JSON messages, no result backend, bounded retries/timeouts, durable PostgreSQL reconciliation and immutable transactions address duplicate/lost task delivery. `uv.lock` pins all transitive packages and `requirements.lock` is regenerated with `uv export --locked --no-dev --no-emit-project --format requirements-txt -o requirements.lock`.
