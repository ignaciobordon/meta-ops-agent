"""008 — Competitive Intelligence module tables.

ci_competitors, ci_competitor_domains, ci_sources, ci_ingest_runs, ci_canonical_items.

Revision ID: 008
Revises: 007
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    # ── Enums ─────────────────────────────────────────────────────────────

    ci_competitor_status = sa.Enum("active", "paused", "archived", name="cicompetitorstatus")
    ci_competitor_status.create(op.get_bind(), checkfirst=True)

    ci_domain_type = sa.Enum("ad_library", "website", "social", "marketplace", name="cidomaintype")
    ci_domain_type.create(op.get_bind(), checkfirst=True)

    ci_source_type = sa.Enum("meta_ad_library", "manual", "scraper", "api", name="cisourcetype")
    ci_source_type.create(op.get_bind(), checkfirst=True)

    ci_ingest_status = sa.Enum("queued", "running", "succeeded", "partial", "failed", name="ciingeststatus")
    ci_ingest_status.create(op.get_bind(), checkfirst=True)

    ci_item_type = sa.Enum("ad", "landing_page", "post", "offer", name="ciitemtype")
    ci_item_type.create(op.get_bind(), checkfirst=True)

    # ── ci_competitors ────────────────────────────────────────────────────

    op.create_table(
        "ci_competitors",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("website_url", sa.String(512), nullable=True),
        sa.Column("logo_url", sa.String(512), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("status", ci_competitor_status, nullable=False, server_default="active"),
        sa.Column("meta_json", sa.JSON, server_default="{}"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("org_id", "name", name="uq_ci_competitor_org_name"),
    )
    op.create_index("ix_ci_competitor_org", "ci_competitors", ["org_id"])

    # ── ci_competitor_domains ─────────────────────────────────────────────

    op.create_table(
        "ci_competitor_domains",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("competitor_id", UUID(as_uuid=True), sa.ForeignKey("ci_competitors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(512), nullable=False),
        sa.Column("domain_type", ci_domain_type, nullable=False),
        sa.Column("verified", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "competitor_id", "domain", "domain_type", name="uq_ci_domain_unique"),
    )
    op.create_index("ix_ci_domain_org", "ci_competitor_domains", ["org_id"])

    # ── ci_sources ────────────────────────────────────────────────────────

    op.create_table(
        "ci_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", ci_source_type, nullable=False),
        sa.Column("config_json", sa.JSON, server_default="{}"),
        sa.Column("enabled", sa.Integer, server_default="1"),
        sa.Column("last_run_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("org_id", "name", name="uq_ci_source_org_name"),
    )
    op.create_index("ix_ci_source_org", "ci_sources", ["org_id"])

    # ── ci_ingest_runs ────────────────────────────────────────────────────

    op.create_table(
        "ci_ingest_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("ci_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", ci_ingest_status, nullable=False, server_default="queued"),
        sa.Column("items_fetched", sa.Integer, server_default="0"),
        sa.Column("items_upserted", sa.Integer, server_default="0"),
        sa.Column("items_skipped", sa.Integer, server_default="0"),
        sa.Column("error_count", sa.Integer, server_default="0"),
        sa.Column("error_summary_json", sa.JSON, nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ci_ingest_org_status", "ci_ingest_runs", ["org_id", "status"])

    # ── ci_canonical_items ────────────────────────────────────────────────

    op.create_table(
        "ci_canonical_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("competitor_id", UUID(as_uuid=True), sa.ForeignKey("ci_competitors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("ci_sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ingest_run_id", UUID(as_uuid=True), sa.ForeignKey("ci_ingest_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("item_type", ci_item_type, nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("url", sa.String(1024), nullable=True),
        sa.Column("image_urls_json", sa.JSON, server_default="[]"),
        sa.Column("canonical_json", sa.JSON, server_default="{}"),
        sa.Column("raw_json", sa.JSON, server_default="{}"),
        sa.Column("embedding_id", sa.String(255), nullable=True),
        sa.Column("first_seen_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("org_id", "competitor_id", "item_type", "external_id", name="uq_ci_item_unique"),
    )
    op.create_index("ix_ci_item_org_type", "ci_canonical_items", ["org_id", "item_type"])
    op.create_index("ix_ci_item_competitor", "ci_canonical_items", ["competitor_id"])
    op.create_index("ix_ci_item_external", "ci_canonical_items", ["org_id", "external_id"])


def downgrade():
    op.drop_table("ci_canonical_items")
    op.drop_table("ci_ingest_runs")
    op.drop_table("ci_sources")
    op.drop_table("ci_competitor_domains")
    op.drop_table("ci_competitors")
    op.execute("DROP TYPE IF EXISTS ciitemtype")
    op.execute("DROP TYPE IF EXISTS ciingeststatus")
    op.execute("DROP TYPE IF EXISTS cisourcetype")
    op.execute("DROP TYPE IF EXISTS cidomaintype")
    op.execute("DROP TYPE IF EXISTS cicompetitorstatus")
