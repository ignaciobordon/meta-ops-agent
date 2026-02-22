"""010 — Flywheel & Data Room: flywheel_runs, flywheel_steps, data_exports tables.

Revision ID: 010
Revises: 009
"""
revision = "010"
down_revision = "009"

from alembic import op
import sqlalchemy as sa


def upgrade():
    # ── flywheel_runs ────────────────────────────────────────────────────────
    op.create_table(
        "flywheel_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ad_account_id", sa.String(36),
                  sa.ForeignKey("meta_ad_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("config_json", sa.JSON, server_default="{}"),
        sa.Column("outputs_json", sa.JSON, server_default="{}"),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index("ix_flywheel_run_org", "flywheel_runs", ["org_id"])
    op.create_index("ix_flywheel_run_status", "flywheel_runs", ["org_id", "status"])

    # ── flywheel_steps ───────────────────────────────────────────────────────
    op.create_table(
        "flywheel_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("flywheel_run_id", sa.String(36),
                  sa.ForeignKey("flywheel_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_name", sa.String(100), nullable=False),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("job_run_id", sa.String(36),
                  sa.ForeignKey("job_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("artifacts_json", sa.JSON, server_default="{}"),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index("ix_flywheel_step_run", "flywheel_steps", ["flywheel_run_id"])

    # ── data_exports ─────────────────────────────────────────────────────────
    op.create_table(
        "data_exports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("requested_by_user_id", sa.String(36),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("params_json", sa.JSON, server_default="{}"),
        sa.Column("file_path", sa.String(512), nullable=True),
        sa.Column("rows_exported", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("trace_id", sa.String(100), nullable=True),
        sa.Column("job_run_id", sa.String(36),
                  sa.ForeignKey("job_runs.id", ondelete="SET NULL"), nullable=True),
    )

    op.create_index("ix_data_export_org", "data_exports", ["org_id"])
    op.create_index("ix_data_export_status", "data_exports", ["org_id", "status"])


def downgrade():
    op.drop_index("ix_data_export_status", "data_exports")
    op.drop_index("ix_data_export_org", "data_exports")
    op.drop_table("data_exports")

    op.drop_index("ix_flywheel_step_run", "flywheel_steps")
    op.drop_table("flywheel_steps")

    op.drop_index("ix_flywheel_run_status", "flywheel_runs")
    op.drop_index("ix_flywheel_run_org", "flywheel_runs")
    op.drop_table("flywheel_runs")
