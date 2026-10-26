"""Isolate Yahoo instruments and preserve daily opening prices.

Revision ID: 0013_yahoo_eod
Revises: 0012_martin
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_yahoo_eod"
down_revision = "0012_martin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_instruments_exchange", "instruments", type_="unique")
    op.create_unique_constraint(
        "uq_instruments_exchange", "instruments", ["exchange", "symbol", "data_kind"]
    )
    op.create_check_constraint(
        "ck_instruments_data_kind", "instruments", "data_kind IN ('fixture', 'yahoo')"
    )
    op.add_column("price_snapshots", sa.Column("open", sa.Numeric(20, 4), nullable=True))
    op.create_check_constraint(
        "ck_price_snapshots_positive_open",
        "price_snapshots",
        "open IS NULL OR (open > 0 AND open <> 'NaN'::numeric)",
    )


def downgrade() -> None:
    # Intentionally fails if both sources still contain the same symbol; do not delete history.
    op.drop_constraint("ck_price_snapshots_positive_open", "price_snapshots", type_="check")
    op.drop_column("price_snapshots", "open")
    op.drop_constraint("ck_instruments_data_kind", "instruments", type_="check")
    op.drop_constraint("uq_instruments_exchange", "instruments", type_="unique")
    op.create_unique_constraint("uq_instruments_exchange", "instruments", ["exchange", "symbol"])
