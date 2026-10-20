"""Establish migration history; domain tables start in Phase 2.

Alembic creates alembic_version itself. No demo users or financial records are seeded.
"""

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
