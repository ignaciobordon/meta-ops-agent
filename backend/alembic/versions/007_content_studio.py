"""007 — Content Studio tables.

content_packs, content_variants, content_channel_locks, content_exports.

Revision ID: 007
Revises: 006
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    # ContentPack status enum
    content_pack_status = sa.Enum("queued", "running", "succeeded", "failed", name="contentpackstatus")
    content_pack_status.create(op.get_bind(), checkfirst=True)

    # content_packs
    op.create_table(
        "content_packs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("creative_id", UUID(as_uuid=True), sa.ForeignKey("creatives.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", content_pack_status, nullable=False, server_default="queued"),
        sa.Column("goal", sa.String(50), nullable=True),
        sa.Column("language", sa.String(10), server_default="es-AR"),
        sa.Column("channels_json", sa.JSON, server_default="[]"),
        sa.Column("input_json", sa.JSON, server_default="{}"),
        sa.Column("job_run_id", UUID(as_uuid=True), sa.ForeignKey("job_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        sa.Column("last_error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_content_pack_org", "content_packs", ["org_id"])
    op.create_index("ix_content_pack_status", "content_packs", ["status"])

    # content_variants
    op.create_table(
        "content_variants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("content_pack_id", UUID(as_uuid=True), sa.ForeignKey("content_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("format", sa.String(50), nullable=True),
        sa.Column("variant_index", sa.Integer, nullable=False),
        sa.Column("output_json", sa.JSON, server_default="{}"),
        sa.Column("score", sa.Float, server_default="0"),
        sa.Column("score_breakdown_json", sa.JSON, server_default="{}"),
        sa.Column("rationale_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_variant_pack_channel", "content_variants", ["content_pack_id", "channel"])

    # content_channel_locks
    op.create_table(
        "content_channel_locks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("content_pack_id", UUID(as_uuid=True), sa.ForeignKey("content_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("locked_variant_id", UUID(as_uuid=True), sa.ForeignKey("content_variants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("locked_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("locked_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("content_pack_id", "channel", name="uq_channel_lock_pack_channel"),
    )

    # content_exports
    op.create_table(
        "content_exports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("content_pack_id", UUID(as_uuid=True), sa.ForeignKey("content_packs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_ref", sa.String(512), nullable=True),
        sa.Column("size_bytes", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("content_exports")
    op.drop_table("content_channel_locks")
    op.drop_table("content_variants")
    op.drop_table("content_packs")
    op.execute("DROP TYPE IF EXISTS contentpackstatus")
