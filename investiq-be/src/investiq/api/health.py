import asyncio
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from investiq.db.session import SCHEMA_REVISION
from investiq.schemas.health import LiveResponse, ReadyResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse()


async def check_database(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        revision = await conn.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != SCHEMA_REVISION:
            raise RuntimeError("Schema revision mismatch")


async def check_redis(redis: Redis) -> None:
    if not await redis.ping():
        raise RuntimeError("Redis ping failed")


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(request: Request) -> JSONResponse:
    timeout = request.app.state.settings.dependency_timeout_seconds
    results = await asyncio.gather(
        asyncio.wait_for(check_database(request.app.state.engine), timeout),
        asyncio.wait_for(check_redis(request.app.state.redis), timeout),
        return_exceptions=True,
    )
    checks: dict[str, Literal["ok", "unavailable"]] = {
        name: "unavailable" if isinstance(result, BaseException) else "ok"
        for name, result in zip(("postgresql", "redis"), results, strict=True)
    }
    healthy = all(value == "ok" for value in checks.values())
    body = ReadyResponse(status="ready" if healthy else "unavailable", checks=checks)
    return JSONResponse(status_code=200 if healthy else 503, content=body.model_dump())
