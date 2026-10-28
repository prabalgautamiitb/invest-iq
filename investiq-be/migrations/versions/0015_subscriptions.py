"""Account subscription activation without billing.

Revision ID: 0015_subscriptions
Revises: 0014_profile_photos
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_subscriptions"
down_revision = "0014_profile_photos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("subscription_plan", sa.String(12), nullable=True))
    op.add_column("users", sa.Column("subscription_starts_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("subscription_ends_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "subscription",
        "users",
        "(subscription_plan IS NULL AND subscription_starts_at IS NULL "
        "AND subscription_ends_at IS NULL) OR "
        "(subscription_plan IS NOT NULL AND subscription_plan IN ('student', 'standard') "
        "AND subscription_starts_at IS NOT NULL AND subscription_ends_at IS NOT NULL "
        "AND subscription_ends_at > subscription_starts_at)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_subscription", "users", type_="check")
    op.drop_column("users", "subscription_ends_at")
    op.drop_column("users", "subscription_starts_at")
    op.drop_column("users", "subscription_plan")
