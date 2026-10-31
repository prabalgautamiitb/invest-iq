"""Vercel ASGI entrypoint; deployments initialise data through deploy_cli separately."""

from investiq.main import create_app

app = create_app()
