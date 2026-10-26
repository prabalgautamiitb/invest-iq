import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.adapters.coach import CoachProvider
from investiq.adapters.mail import Mailer, SmtpMailer
from investiq.adapters.martin import MartinProvider
from investiq.api.coach import router as coach_router
from investiq.api.community import router as community_router
from investiq.api.contest import router as contest_router
from investiq.api.health import router as health_router
from investiq.api.identity import router as identity_router
from investiq.api.learning import router as learning_router
from investiq.api.market import router as market_router
from investiq.api.martin import router as martin_router
from investiq.api.news import router as news_router
from investiq.api.portfolio import router as portfolio_router
from investiq.api.rewards import router as rewards_router
from investiq.api.valuation import router as valuation_router
from investiq.core.config import Settings
from investiq.core.errors import error_response, install_error_handlers
from investiq.core.logging import configure_logging
from investiq.db.session import make_engine
from investiq.services.coach import CoachService
from investiq.services.community import CommunityService
from investiq.services.contest import ContestService
from investiq.services.identity import IdentityService
from investiq.services.learning import LearningService
from investiq.services.market import MarketService
from investiq.services.martin import MartinService
from investiq.services.news import MarketNewsService
from investiq.services.portfolio import PortfolioService
from investiq.services.rewards import RewardsService
from investiq.services.valuation import ValuationService

logger = logging.getLogger("investiq.http")


def create_app(
    settings: Settings | None = None,
    mailer: Mailer | None = None,
    market_clock: Callable[[], datetime] | None = None,
    contest_clock: Callable[[], datetime] | None = None,
    learning_clock: Callable[[], datetime] | None = None,
    coach_provider: CoachProvider | None = None,
    martin_provider: MartinProvider | None = None,
) -> FastAPI:
    config = settings or Settings()
    configure_logging(config.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(config)
        redis = Redis.from_url(
            config.redis_url.get_secret_value(),
            socket_connect_timeout=config.dependency_timeout_seconds,
            socket_timeout=config.dependency_timeout_seconds,
            decode_responses=True,
        )
        app.state.engine = engine
        app.state.redis = redis
        app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
        app.state.identity = IdentityService(
            app.state.sessions, redis, config, mailer or SmtpMailer(config)
        )
        app.state.community = CommunityService(app.state.identity)
        app.state.rewards = RewardsService(app.state.identity)
        app.state.learning = LearningService(app.state.identity, learning_clock)
        app.state.market = MarketService(app.state.sessions, config, market_clock)
        app.state.market_news = MarketNewsService(redis, config)
        app.state.contests = ContestService(app.state.sessions, app.state.identity, contest_clock)
        app.state.portfolios = PortfolioService(app.state.contests)
        app.state.valuations = ValuationService(app.state.contests)
        app.state.coach = CoachService(app.state.valuations, coach_provider)
        app.state.martin = MartinService(app.state.coach, martin_provider)
        try:
            yield
        finally:
            await redis.aclose()
            await engine.dispose()

    app = FastAPI(
        title="InvestIQ API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if config.environment != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.environment != "production" else None,
    )
    app.state.settings = config
    install_error_handlers(app)

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = str(uuid4())
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request_failed",
                extra={
                    "request_id": request.state.request_id,
                    "exception_type": type(exc).__name__,
                },
            )
            response = error_response(request, 500, "internal_error", "Internal server error")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not request.url.path.startswith("/api/v1/health"):
            response.headers["Cache-Control"] = "no-store"
        logger.info(
            "request_completed",
            extra={
                "request_id": request.state.request_id,
                "method": request.method,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            },
        )
        return response

    # Added last so even generated error responses receive CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
    )
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(identity_router, prefix="/api/v1")
    app.include_router(learning_router, prefix="/api/v1")
    app.include_router(market_router, prefix="/api/v1")
    app.include_router(news_router, prefix="/api/v1")
    app.include_router(contest_router, prefix="/api/v1")
    app.include_router(portfolio_router, prefix="/api/v1")
    app.include_router(martin_router, prefix="/api/v1")
    app.include_router(coach_router, prefix="/api/v1")
    app.include_router(community_router, prefix="/api/v1")
    app.include_router(rewards_router, prefix="/api/v1")
    app.include_router(valuation_router, prefix="/api/v1")
    return app
