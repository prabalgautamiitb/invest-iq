"""Store private normalized profile photos.

Revision ID: 0014_profile_photos
Revises: 0013_yahoo_eod
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_profile_photos"
down_revision = "0013_yahoo_eod"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profile_photos",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("image", sa.LargeBinary(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("octet_length(image) BETWEEN 1 AND 262144", name="image_size"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("profile_photos")
