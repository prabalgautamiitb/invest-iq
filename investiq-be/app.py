"""Vercel ASGI entrypoint; deployments initialise data through deploy_cli separately."""

import sys
from pathlib import Path

# Vercel installs third-party dependencies without installing this src-layout project.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from investiq.main import create_app  # noqa: E402

app = create_app()
