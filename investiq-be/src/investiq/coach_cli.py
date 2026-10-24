import argparse
import asyncio

from investiq.ai.workflow import setup_checkpoints, sweep
from investiq.core.config import Settings
from investiq.main import create_app


async def run(action: str) -> None:
    settings = Settings()
    if action == "setup":
        await setup_checkpoints(settings)
        print("AI checkpoint schema initialized")
        return
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        result = await sweep(application.state.coach)
        print(f"Coach jobs processed: {result['processed']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize AI checkpoints or process one due coach job"
    )
    parser.add_argument("action", choices=["setup", "work"])
    asyncio.run(run(parser.parse_args().action))


if __name__ == "__main__":
    main()
