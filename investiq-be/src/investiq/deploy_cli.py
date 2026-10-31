"""Validate hosted configuration and initialise an empty educational deployment."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

from psycopg import Connection
from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from investiq.ai.workflow import setup_checkpoints
from investiq.core.config import Settings
from investiq.db.session import connection_options, make_engine, postgres_url
from investiq.services.learning_seed import seed_curriculum
from investiq.services.market_ingestion import MarketIngestionService
from investiq.services.rewards_seed import seed_rewards


def validate_deployment(settings: Settings) -> None:
    if settings.environment != "production":
        raise ValueError("Set INVESTIQ_ENVIRONMENT=production for a hosted release")
    if not settings.hosted_simulation_enabled:
        raise ValueError("Enable INVESTIQ_HOSTED_SIMULATION_ENABLED for the educational deployment")
    url = make_url(settings.database_url.get_secret_value())
    if url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
        raise ValueError("Use a direct PostgreSQL URL with sslmode=verify-full (or require)")
    connection_options(settings)
    redis_urls = [
        ("REDIS_URL", settings.redis_url),
    ]
    if settings.deployment_mode == "worker":
        redis_urls.append(("CELERY_BROKER_URL", settings.celery_broker_url))
    for name, raw in redis_urls:
        parsed = urlsplit(raw.get_secret_value())
        if parsed.scheme != "rediss":
            raise ValueError(f"INVESTIQ_{name} must use Redis TCP over TLS (rediss://)")
        if name == "CELERY_BROKER_URL" and parse_qs(parsed.query).get("ssl_cert_reqs") != [
            "required"
        ]:
            raise ValueError("Append ssl_cert_reqs=required to the Celery TLS broker URL")
    front = urlsplit(settings.frontend_url)
    origin = f"{front.scheme}://{front.netloc}"
    if front.scheme != "https" or origin not in settings.cors_origins:
        raise ValueError("Use an HTTPS FRONTEND_URL included in CORS_ORIGINS")
    if any(urlsplit(origin).scheme != "https" for origin in settings.cors_origins):
        raise ValueError("Hosted CORS_ORIGINS must contain explicit HTTPS origins")
    if settings.smtp_host in {"localhost", "127.0.0.1", "mailpit"} or not settings.smtp_starttls:
        raise ValueError("Configure a hosted SMTP provider with STARTTLS for verification emails")
    if not settings.smtp_username or not settings.smtp_password.get_secret_value():
        raise ValueError("Configure SMTP_USERNAME and SMTP_PASSWORD")
    if "investiq.local" in settings.mail_from:
        raise ValueError("Set MAIL_FROM to a sender verified with your email provider")
    if settings.ai_provider != "disabled" and (
        settings.ai_provider != "gemini"
        or not settings.gemini_model
        or not settings.gemini_api_key.get_secret_value()
    ):
        raise ValueError("Configure Gemini model/key, or explicitly set AI_PROVIDER=disabled")
    if settings.market_data_mode != "yahoo":
        raise ValueError("Set MARKET_DATA_MODE=yahoo for the hosted market catalogue")
    if settings.public_contest_fixtures_enabled:
        raise ValueError("Leave automatic development contest fixtures disabled in hosted releases")


async def bootstrap(settings: Settings) -> None:
    """Only definitions: no users, fake learner activity, submissions or synthetic prices."""
    engine = make_engine(settings)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        await MarketIngestionService(factory, settings).seed_yahoo_catalogue()
        await seed_curriculum(factory, settings)
        await seed_rewards(factory, settings)
        await setup_checkpoints(settings)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "initialize"])
    args = parser.parse_args()
    try:
        settings = Settings()
        validate_deployment(settings)
        if args.action == "initialize":
            # Direct (non-transaction-pooler) connection serializes all release jobs.
            with Connection.connect(
                postgres_url(settings), autocommit=True, connect_timeout=10
            ) as conn:
                acquired = conn.execute("SELECT pg_try_advisory_lock(742019)").fetchone()
                if not acquired or not acquired[0]:
                    raise ValueError("Another release is running; retry after it completes")
                subprocess.run(
                    [sys.executable, "-m", "alembic", "upgrade", "head"],
                    check=True,
                    env={
                        **os.environ,
                        "INVESTIQ_DATABASE_URL": settings.database_url.get_secret_value(),
                    },
                )
                asyncio.run(bootstrap(settings))
        print(
            json.dumps(
                {
                    "status": "ok",
                    "action": args.action,
                    "simulation": True,
                    "ai_enabled": settings.ai_provider != "disabled",
                }
            )
        )
    except ValidationError as exc:
        fields = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
        raise SystemExit("Invalid configuration fields: " + ", ".join(fields)) from None
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    except Exception:
        raise SystemExit("deployment_failed: check infrastructure and release logs") from None


if __name__ == "__main__":
    main()
