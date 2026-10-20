import json
from datetime import UTC, date, datetime, time
from importlib.resources import files
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from investiq.core.errors import AppError
from investiq.schemas.market import ProviderBatch

EXCHANGE_TZ = ZoneInfo("Asia/Kolkata")


def fixture_document() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(
        files("investiq.data").joinpath("market_fixture_v1.json").read_text()
    )
    return result


class MarketDataProvider(Protocol):
    provider: str
    dataset_version: str

    async def fetch_eod(self, session_date: date) -> ProviderBatch: ...


FIXTURE_DATASETS = ("fixture-v1", "public-fixture-v1")


def public_fixture_document() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(
        files("investiq.data").joinpath("market_public_fixture_v1.json").read_text()
    )
    return result


class FixtureMarketProvider:
    provider = "investiq-synthetic"
    dataset_version = "fixture-v1"

    def document(self) -> dict[str, Any]:
        return fixture_document()

    async def fetch_eod(self, session_date: date) -> ProviderBatch:
        document = self.document()
        points = document["prices"].get(session_date.isoformat())
        if points is None:
            raise AppError(
                422, "fixture_session_unavailable", "No fixture prices exist for this session"
            )
        return ProviderBatch.model_validate(
            {
                "provider": self.provider,
                "dataset_version": self.dataset_version,
                "data_kind": "fixture",
                "session_date": session_date,
                "observed_at": datetime.combine(session_date, time(15, 30), EXCHANGE_TZ).astimezone(
                    UTC
                ),
                "source_published_at": datetime.combine(
                    session_date, time(18), EXCHANGE_TZ
                ).astimezone(UTC),
                "points": points,
            }
        )


class PublicContestFixtureProvider(FixtureMarketProvider):
    dataset_version = "public-fixture-v1"

    def document(self) -> dict[str, Any]:
        return public_fixture_document()
