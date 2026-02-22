"""009 — CI AutoLoop: ci_runs table for autonomous intelligence loop auditing.

Revision ID: 009
Revises: 008
"""
revision = "009"
down_revision = "008"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "ci_runs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_type", sa.Enum("ingest", "detect", "generate", name="ci_run_type_enum"), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("status", sa.Enum("queued", "running", "succeeded", "failed", "skipped",
                                     name="ci_run_status_enum"), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("items_collected", sa.Integer, server_default="0"),
        sa.Column("opportunities_created", sa.Integer, server_default="0"),
        sa.Column("alerts_created", sa.Integer, server_default="0"),
        sa.Column("job_run_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("job_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True, unique=True),
        sa.Column("error_class", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("metadata_json", sa.JSON, server_default="{}"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index("ix_ci_run_org_type", "ci_runs", ["org_id", "run_type"])
    op.create_index("ix_ci_run_org_status", "ci_runs", ["org_id", "status"])


def downgrade():
    op.drop_index("ix_ci_run_org_status", "ci_runs")
    op.drop_index("ix_ci_run_org_type", "ci_runs")
    op.drop_table("ci_runs")
