"""Shared virtual capital for new contest entries; preserve pre-wallet memberships.

Revision ID: 0016_virtual_wallet
Revises: 0015_subscriptions
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_virtual_wallet"
down_revision = "0015_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "virtual_wallets",
        sa.Column(
            "user_id",
            postgresql.UUID(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("available", sa.Numeric(20, 4), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("available >= 0 AND available <> 'NaN'::numeric", name="available"),
    )
    op.create_table(
        "wallet_positions",
        sa.Column(
            "membership_id",
            postgresql.UUID(),
            sa.ForeignKey("contest_memberships.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(),
            sa.ForeignKey("virtual_wallets.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("capital", sa.Numeric(20, 4), nullable=False),
        sa.Column("current_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column(
            "run_id", postgresql.UUID(), sa.ForeignKey("valuation_runs.id", ondelete="RESTRICT")
        ),
        sa.Column("session_date", sa.Date()),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("capital > 0 AND capital <> 'NaN'::numeric", name="capital"),
        sa.CheckConstraint("current_value >= 0 AND current_value <> 'NaN'::numeric", name="value"),
        sa.CheckConstraint("status IN ('active','settled','refunded')", name="status"),
        sa.CheckConstraint(
            "(status = 'active' AND released_at IS NULL) OR "
            "(status <> 'active' AND released_at IS NOT NULL)",
            name="release",
        ),
    )
    op.create_index("ix_wallet_positions_user_id", "wallet_positions", ["user_id"])
    op.create_table(
        "wallet_entries",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(),
            sa.ForeignKey("virtual_wallets.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "membership_id",
            postgresql.UUID(),
            sa.ForeignKey("contest_memberships.id", ondelete="RESTRICT"),
        ),
        sa.Column("event_key", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("available_after", sa.Numeric(20, 4), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "event_key"),
        sa.CheckConstraint(
            "kind IN ('opening','reservation','settlement','cancellation','no_submission')",
            name="kind",
        ),
        sa.CheckConstraint(
            "available_after >= 0 AND available_after <> 'NaN'::numeric", name="balance"
        ),
        sa.CheckConstraint("amount <> 'NaN'::numeric", name="amount"),
    )
    op.create_index("ix_wallet_entries_user_id", "wallet_entries", ["user_id"])
    op.execute("INSERT INTO virtual_wallets (user_id, available) SELECT id, 1000000 FROM users")
    op.execute(
        "INSERT INTO wallet_entries (id, user_id, event_key, kind, amount, available_after) "
        "SELECT gen_random_uuid(), user_id, 'opening', 'opening', 1000000, 1000000 "
        "FROM virtual_wallets"
    )
    op.execute("""
        CREATE FUNCTION wallet_evidence_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'wallet ledger evidence is immutable' USING ERRCODE = '23514';
        END $$
    """)
    op.execute(
        "CREATE TRIGGER wallet_entries_immutable BEFORE UPDATE OR DELETE ON wallet_entries "
        "FOR EACH ROW EXECUTE FUNCTION wallet_evidence_immutable()"
    )
    op.execute("""
        CREATE FUNCTION wallet_position_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' OR OLD.status <> 'active' OR
               NEW.membership_id IS DISTINCT FROM OLD.membership_id OR
               NEW.user_id IS DISTINCT FROM OLD.user_id OR
               NEW.capital IS DISTINCT FROM OLD.capital THEN
                RAISE EXCEPTION 'wallet funding evidence is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER wallet_position_guard BEFORE UPDATE OR DELETE ON wallet_positions "
        "FOR EACH ROW EXECUTE FUNCTION wallet_position_guard()"
    )


def downgrade() -> None:
    # Reversing a used wallet would discard committed virtual funds and their provenance.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM wallet_positions) THEN
                RAISE EXCEPTION 'Cannot downgrade a wallet with contest funding history';
            END IF;
        END $$
    """)
    op.drop_table("wallet_entries")
    op.drop_table("wallet_positions")
    op.drop_table("virtual_wallets")
    op.execute("DROP FUNCTION wallet_position_guard()")
    op.execute("DROP FUNCTION wallet_evidence_immutable()")
