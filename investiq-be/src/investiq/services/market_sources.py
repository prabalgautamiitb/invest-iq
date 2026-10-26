"""One source policy for quotes, submission pricing and valuation."""

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from investiq.models.market import IngestionRun, PriceSnapshot
from investiq.schemas.market import MarketDataKind

YAHOO_PROVIDER = "yahoo-finance"
YAHOO_DATASET = "yahoo-eod-v2"
YAHOO_DATASETS = ("yahoo-eod-v1", YAHOO_DATASET)


def price_source(kind: MarketDataKind, as_of: datetime | None = None) -> ColumnElement[bool]:
    # Lazy import avoids mixing the catalogue/provider with persistence policies.
    from investiq.adapters.market import FIXTURE_DATASETS

    base = and_(
        IngestionRun.data_kind == kind,
        IngestionRun.provider == (YAHOO_PROVIDER if kind == "yahoo" else "investiq-synthetic"),
        IngestionRun.dataset_version.in_(YAHOO_DATASETS if kind == "yahoo" else FIXTURE_DATASETS),
    )
    if kind != "yahoo":
        return base
    candidate, price = aliased(IngestionRun), aliased(PriceSnapshot)
    preferred = (
        select(candidate.id)
        .join(price, price.run_id == candidate.id)
        .where(
            candidate.provider == YAHOO_PROVIDER,
            candidate.dataset_version.in_(YAHOO_DATASETS),
            candidate.status == "succeeded",
            candidate.session_date == IngestionRun.session_date,
        )
    )
    if as_of is not None:
        preferred = preferred.where(price.source_published_at <= as_of)
    # Prefer a complete newer universe as a whole, rather than mixing individual
    # prices from overlapping batches. Earlier cutoffs still read the original batch.
    selected = preferred.order_by(candidate.dataset_version.desc()).limit(1).correlate(IngestionRun)
    return and_(
        base,
        or_(IngestionRun.status != "succeeded", IngestionRun.id == selected.scalar_subquery()),
    )
