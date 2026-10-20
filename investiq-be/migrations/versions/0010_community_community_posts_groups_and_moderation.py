"""community posts groups and moderation

Revision ID: 0010_community
Revises: 0009_rewards
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_community"
down_revision = "0009_rewards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(name) BETWEEN 3 AND 80", name=op.f("ck_community_groups_name_length")
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["users.id"],
            name=op.f("fk_community_groups_creator_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_community_groups")),
        sa.UniqueConstraint("name", name=op.f("uq_community_groups_name")),
    )
    op.create_table(
        "community_content",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("body", sa.String(length=4000), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=10), server_default="visible", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'comment') = (parent_id IS NOT NULL)",
            name=op.f("ck_community_content_parent_kind"),
        ),
        sa.CheckConstraint(
            "(kind = 'poll') = (closes_at IS NOT NULL)",
            name=op.f("ck_community_content_poll_close"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(options) = 'array' AND ((kind = 'poll' "
            "AND jsonb_array_length(options) BETWEEN 2 AND 6) OR "
            "(kind <> 'poll' AND jsonb_array_length(options) = 0))",
            name=op.f("ck_community_content_options"),
        ),
        sa.CheckConstraint(
            "kind IN ('discussion','idea','market','poll','comment')",
            name=op.f("ck_community_content_kind"),
        ),
        sa.CheckConstraint(
            "state IN ('visible','deleted','hidden')", name=op.f("ck_community_content_state")
        ),
        sa.CheckConstraint(
            "length(body) BETWEEN 1 AND 4000", name=op.f("ck_community_content_body_length")
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_community_content_author_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["community_groups.id"],
            name=op.f("fk_community_content_group_id_community_groups"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["community_content.id"],
            name=op.f("fk_community_content_parent_id_community_content"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_community_content")),
        sa.UniqueConstraint(
            "author_id", "request_key", name=op.f("uq_community_content_author_id")
        ),
    )
    op.create_index(
        op.f("ix_community_content_author_id"), "community_content", ["author_id"], unique=False
    )
    op.create_index(
        op.f("ix_community_content_created_at"), "community_content", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_community_content_group_id"), "community_content", ["group_id"], unique=False
    )
    op.create_index(
        op.f("ix_community_content_parent_id"), "community_content", ["parent_id"], unique=False
    )
    op.create_table(
        "community_members",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["community_groups.id"],
            name=op.f("fk_community_members_group_id_community_groups"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_community_members_user_id_users")
        ),
        sa.PrimaryKeyConstraint("group_id", "user_id", name=op.f("pk_community_members")),
    )
    op.create_table(
        "community_moderation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_id", sa.Uuid(), nullable=False),
        sa.Column("moderator_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('hide','restore','dismiss')", name=op.f("ck_community_moderation_action")
        ),
        sa.CheckConstraint(
            "length(reason) BETWEEN 5 AND 500", name=op.f("ck_community_moderation_reason")
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["community_content.id"],
            name=op.f("fk_community_moderation_content_id_community_content"),
        ),
        sa.ForeignKeyConstraint(
            ["moderator_id"], ["users.id"], name=op.f("fk_community_moderation_moderator_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_community_moderation")),
    )
    op.create_table(
        "community_reactions",
        sa.Column("content_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["community_content.id"],
            name=op.f("fk_community_reactions_content_id_community_content"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_community_reactions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("content_id", "user_id", name=op.f("pk_community_reactions")),
    )
    op.create_table(
        "community_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_id", sa.Uuid(), nullable=False),
        sa.Column("reporter_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("resolved", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(reason) BETWEEN 5 AND 500", name=op.f("ck_community_reports_reason")
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["community_content.id"],
            name=op.f("fk_community_reports_content_id_community_content"),
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"], ["users.id"], name=op.f("fk_community_reports_reporter_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_community_reports")),
        sa.UniqueConstraint(
            "content_id", "reporter_id", name=op.f("uq_community_reports_content_id")
        ),
    )
    op.create_table(
        "community_saves",
        sa.Column("content_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["community_content.id"],
            name=op.f("fk_community_saves_content_id_community_content"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_community_saves_user_id_users")
        ),
        sa.PrimaryKeyConstraint("content_id", "user_id", name=op.f("pk_community_saves")),
    )
    op.create_table(
        "community_votes",
        sa.Column("content_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("option", sa.Integer(), nullable=False),
        sa.CheckConstraint("option BETWEEN 0 AND 5", name=op.f("ck_community_votes_option")),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["community_content.id"],
            name=op.f("fk_community_votes_content_id_community_content"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_community_votes_user_id_users")
        ),
        sa.PrimaryKeyConstraint("content_id", "user_id", name=op.f("pk_community_votes")),
    )
    op.execute("""
        CREATE FUNCTION community_content_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE root community_content;
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Community evidence uses soft deletion' USING ERRCODE = '23514';
          END IF;
          IF TG_OP = 'UPDATE' THEN
            IF (to_jsonb(NEW) - 'state') IS DISTINCT FROM (to_jsonb(OLD) - 'state')
               OR (OLD.state = 'deleted' AND NEW.state <> 'deleted') THEN
              RAISE EXCEPTION 'Community content is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.parent_id IS NOT NULL THEN
            SELECT * INTO root FROM community_content WHERE id = NEW.parent_id FOR UPDATE;
            IF root.id IS NULL OR root.parent_id IS NOT NULL OR root.state <> 'visible'
               OR NEW.group_id IS DISTINCT FROM root.group_id THEN
              RAISE EXCEPTION 'Invalid reply parent' USING ERRCODE = '23514';
            END IF;
          END IF;
          IF NEW.kind = 'poll' AND (NEW.closes_at <= statement_timestamp()
             OR NEW.closes_at > statement_timestamp() + interval '30 days') THEN
            RAISE EXCEPTION 'Invalid poll closing time' USING ERRCODE = '23514';
          END IF;
          IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.options) o
                     WHERE jsonb_typeof(o) <> 'string'
                     OR length(btrim(o #>> '{}')) NOT BETWEEN 1 AND 120)
             OR (SELECT count(DISTINCT o) FROM jsonb_array_elements(NEW.options) o)
                <> jsonb_array_length(NEW.options) THEN
            RAISE EXCEPTION 'Invalid poll options' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER community_content_guard BEFORE INSERT OR UPDATE OR DELETE
        ON community_content FOR EACH ROW EXECUTE FUNCTION community_content_guard();
    """)
    op.execute("""
        CREATE FUNCTION community_vote_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE poll community_content;
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'Poll votes are final' USING ERRCODE = '23514';
          END IF;
          SELECT * INTO poll FROM community_content WHERE id = NEW.content_id FOR UPDATE;
          IF poll.kind <> 'poll' OR poll.state <> 'visible'
             OR poll.closes_at <= statement_timestamp()
             OR NEW.option < 0 OR NEW.option >= jsonb_array_length(poll.options) THEN
            RAISE EXCEPTION 'Poll unavailable' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER community_vote_guard BEFORE INSERT OR UPDATE OR DELETE
        ON community_votes FOR EACH ROW EXECUTE FUNCTION community_vote_guard();
    """)


def downgrade() -> None:
    op.drop_table("community_votes")
    op.execute("DROP FUNCTION community_vote_guard()")
    op.drop_table("community_saves")
    op.drop_table("community_reports")
    op.drop_table("community_reactions")
    op.drop_table("community_moderation")
    op.drop_table("community_members")
    op.drop_index(op.f("ix_community_content_parent_id"), table_name="community_content")
    op.drop_index(op.f("ix_community_content_group_id"), table_name="community_content")
    op.drop_index(op.f("ix_community_content_created_at"), table_name="community_content")
    op.drop_index(op.f("ix_community_content_author_id"), table_name="community_content")
    op.drop_table("community_content")
    op.execute("DROP FUNCTION community_content_guard()")
    op.drop_table("community_groups")
