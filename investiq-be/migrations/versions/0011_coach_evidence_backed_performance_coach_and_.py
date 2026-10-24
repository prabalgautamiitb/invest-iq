"""evidence backed performance coach and private reflections

Revision ID: 0011_coach
Revises: 0010_community
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_coach"
down_revision = "0010_community"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coach_reflections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("contest_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        sa.Column("body", sa.String(length=2000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(body) BETWEEN 1 AND 2000", name=op.f("ck_coach_reflections_body_length")
        ),
        sa.ForeignKeyConstraint(
            ["contest_id"], ["contests.id"], name=op.f("fk_coach_reflections_contest_id_contests")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_coach_reflections_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coach_reflections")),
        sa.UniqueConstraint("user_id", "request_key", name=op.f("uq_coach_reflections_user_id")),
    )
    op.create_index(
        op.f("ix_coach_reflections_contest_id"), "coach_reflections", ["contest_id"], unique=False
    )
    op.create_index(
        op.f("ix_coach_reflections_user_id"), "coach_reflections", ["user_id"], unique=False
    )
    op.create_table(
        "coach_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("contest_id", sa.Uuid(), nullable=False),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("generation > 0", name=op.f("ck_coach_jobs_generation")),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'running') = (lease_token IS NOT NULL AND leased_until IS NOT NULL)",
            name=op.f("ck_coach_jobs_lease"),
        ),
        sa.CheckConstraint("provider IN ('ollama','gemini')", name=op.f("ck_coach_jobs_provider")),
        sa.CheckConstraint(
            "status IN ('queued','running','retry','succeeded','failed')",
            name=op.f("ck_coach_jobs_status"),
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3", name=op.f("ck_coach_jobs_attempts")),
        sa.ForeignKeyConstraint(
            ["contest_id"], ["contests.id"], name=op.f("fk_coach_jobs_contest_id_contests")
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["valuation_records.id"],
            name=op.f("fk_coach_jobs_record_id_valuation_records"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_coach_jobs_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coach_jobs")),
        sa.UniqueConstraint("id", "user_id", name=op.f("uq_coach_jobs_id")),
        sa.UniqueConstraint(
            "user_id",
            "record_id",
            "provider",
            "model",
            "prompt_version",
            "generation",
            name="uq_coach_source_policy",
        ),
    )
    op.create_index(op.f("ix_coach_jobs_contest_id"), "coach_jobs", ["contest_id"], unique=False)
    op.create_index(
        op.f("ix_coach_jobs_next_attempt_at"), "coach_jobs", ["next_attempt_at"], unique=False
    )
    op.create_index(op.f("ix_coach_jobs_status"), "coach_jobs", ["status"], unique=False)
    op.create_index(op.f("ix_coach_jobs_user_id"), "coach_jobs", ["user_id"], unique=False)
    op.create_table(
        "coach_attempts",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "estimated_cost_usd IS NULL OR estimated_cost_usd >= 0",
            name=op.f("ck_coach_attempts_cost"),
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name=op.f("ck_coach_attempts_input_tokens")
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name=op.f("ck_coach_attempts_latency_ms")
        ),
        sa.CheckConstraint("number BETWEEN 1 AND 3", name=op.f("ck_coach_attempts_number")),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name=op.f("ck_coach_attempts_output_tokens"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["coach_jobs.id"], name=op.f("fk_coach_attempts_job_id_coach_jobs")
        ),
        sa.PrimaryKeyConstraint("job_id", "number", name=op.f("pk_coach_attempts")),
    )
    op.create_table(
        "coach_reports",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["coach_jobs.id", "coach_jobs.user_id"],
            name=op.f("fk_coach_reports_job_id_coach_jobs"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_coach_reports_user_id_users")
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_coach_reports")),
    )
    op.create_index(op.f("ix_coach_reports_user_id"), "coach_reports", ["user_id"], unique=False)
    op.create_table(
        "coach_requests",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["coach_jobs.id", "coach_jobs.user_id"],
            name=op.f("fk_coach_requests_job_id_coach_jobs"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_coach_requests_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", "key", name=op.f("pk_coach_requests")),
    )

    op.execute("CREATE SCHEMA investiq_ai")
    op.execute("""
      CREATE FUNCTION coach_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE source record;
      BEGIN
        IF TG_OP = 'DELETE' THEN
          RAISE EXCEPTION 'Coach evidence is retained' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' THEN
          IF (to_jsonb(NEW) - ARRAY['status','attempts','error_code','lease_token',
                'leased_until','next_attempt_at','updated_at']) IS DISTINCT FROM
             (to_jsonb(OLD) - ARRAY['status','attempts','error_code','lease_token',
                'leased_until','next_attempt_at','updated_at'])
             OR OLD.status IN ('succeeded','failed')
             OR NEW.attempts < OLD.attempts OR NEW.attempts > OLD.attempts + 1 THEN
            RAISE EXCEPTION 'Coach source is immutable' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END IF;
        SELECT r.run_id, r.submission_id, m.user_id, m.contest_id INTO source
          FROM valuation_records r JOIN contest_memberships m ON m.id = r.membership_id
          JOIN valuation_runs v ON v.id = r.run_id
          WHERE r.id = NEW.record_id AND v.status = 'succeeded';
        IF NOT FOUND OR source.user_id IS DISTINCT FROM NEW.user_id
          OR source.contest_id IS DISTINCT FROM NEW.contest_id
          OR (NEW.evidence->>'record_id') IS DISTINCT FROM NEW.record_id::text
          OR (NEW.evidence->>'contest_id') IS DISTINCT FROM NEW.contest_id::text
          OR (NEW.evidence->>'run_id') IS DISTINCT FROM source.run_id::text
          OR (NEW.evidence->>'submission_id') IS DISTINCT FROM source.submission_id::text THEN
          RAISE EXCEPTION 'Invalid coach source ownership' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
      END $$
    """)
    op.execute("""CREATE TRIGGER coach_job_guard BEFORE INSERT OR UPDATE OR DELETE
        ON coach_jobs FOR EACH ROW EXECUTE FUNCTION coach_job_guard()""")
    op.execute("""
      CREATE FUNCTION coach_evidence_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        RAISE EXCEPTION 'Coach evidence is immutable' USING ERRCODE = '23514';
      END $$
    """)
    for table in ["coach_reports", "coach_requests", "coach_reflections"]:
        op.execute(
            f"CREATE TRIGGER coach_evidence_immutable BEFORE UPDATE OR DELETE "
            f"ON {table} FOR EACH ROW EXECUTE FUNCTION coach_evidence_immutable()"
        )
    op.execute("""
      CREATE FUNCTION coach_report_complete() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE identifier uuid; state text; has_report boolean;
      BEGIN
        IF TG_TABLE_NAME = 'coach_jobs' THEN
          identifier := NEW.id;
        ELSE
          identifier := NEW.job_id;
        END IF;
        SELECT status INTO state FROM coach_jobs WHERE id = identifier;
        SELECT EXISTS(SELECT 1 FROM coach_reports WHERE job_id = identifier) INTO has_report;
        IF (state = 'succeeded') IS DISTINCT FROM has_report THEN
          RAISE EXCEPTION 'Report and job completion must agree' USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
      END $$
    """)
    op.execute("""CREATE CONSTRAINT TRIGGER coach_report_complete AFTER INSERT OR UPDATE
        ON coach_jobs DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION coach_report_complete()""")
    op.execute("""CREATE CONSTRAINT TRIGGER coach_report_complete AFTER INSERT
        ON coach_reports DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION coach_report_complete()""")


def downgrade() -> None:
    op.drop_table("coach_requests")
    op.drop_index(op.f("ix_coach_reports_user_id"), table_name="coach_reports")
    op.drop_table("coach_reports")
    op.drop_table("coach_attempts")
    op.drop_index(op.f("ix_coach_jobs_user_id"), table_name="coach_jobs")
    op.drop_index(op.f("ix_coach_jobs_status"), table_name="coach_jobs")
    op.drop_index(op.f("ix_coach_jobs_next_attempt_at"), table_name="coach_jobs")
    op.drop_index(op.f("ix_coach_jobs_contest_id"), table_name="coach_jobs")
    op.drop_table("coach_jobs")
    op.drop_index(op.f("ix_coach_reflections_user_id"), table_name="coach_reflections")
    op.drop_index(op.f("ix_coach_reflections_contest_id"), table_name="coach_reflections")
    op.drop_table("coach_reflections")
    op.execute("DROP FUNCTION coach_job_guard()")
    op.execute("DROP FUNCTION coach_evidence_immutable()")
    op.execute("DROP FUNCTION coach_report_complete()")
    op.execute("DROP SCHEMA investiq_ai CASCADE")
