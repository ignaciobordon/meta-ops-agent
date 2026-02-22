"""
CI Module — SQLAlchemy models.

Tables: ci_competitors, ci_competitor_domains, ci_sources, ci_ingest_runs, ci_canonical_items.
All multi-tenant via org_id → organizations.id CASCADE.
"""
from datetime import datetime
from enum import Enum as PyEnum
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.src.database.models import Base


# ── Enums ─────────────────────────────────────────────────────────────────────


class CICompetitorStatus(str, PyEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class CIDomainType(str, PyEnum):
    AD_LIBRARY = "ad_library"
    WEBSITE = "website"
    SOCIAL = "social"
    MARKETPLACE = "marketplace"


class CISourceType(str, PyEnum):
    META_AD_LIBRARY = "meta_ad_library"
    MANUAL = "manual"
    SCRAPER = "scraper"
    API = "api"


class CIIngestStatus(str, PyEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class CIItemType(str, PyEnum):
    AD = "ad"
    LANDING_PAGE = "landing_page"
    POST = "post"
    OFFER = "offer"


# ── Models ────────────────────────────────────────────────────────────────────


class CICompetitor(Base):
    __tablename__ = "ci_competitors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    website_url = Column(String(512), nullable=True)
    logo_url = Column(String(512), nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(
        Enum(CICompetitorStatus),
        nullable=False,
        default=CICompetitorStatus.ACTIVE,
    )
    meta_json = Column(JSON, default=dict)  # Flexible metadata (industry, size, etc.)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    domains = relationship(
        "CICompetitorDomain",
        back_populates="competitor",
        cascade="all, delete-orphan",
    )
    canonical_items = relationship(
        "CICanonicalItem",
        back_populates="competitor",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_ci_competitor_org", "org_id"),
        UniqueConstraint("org_id", "name", name="uq_ci_competitor_org_name"),
    )


class CICompetitorDomain(Base):
    __tablename__ = "ci_competitor_domains"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    competitor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ci_competitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    domain = Column(String(512), nullable=False)
    domain_type = Column(Enum(CIDomainType), nullable=False)
    verified = Column(Integer, default=0)  # 0=unverified, 1=verified
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    competitor = relationship("CICompetitor", back_populates="domains")

    __table_args__ = (
        Index("ix_ci_domain_org", "org_id"),
        UniqueConstraint(
            "org_id", "competitor_id", "domain", "domain_type",
            name="uq_ci_domain_unique",
        ),
    )


class CISource(Base):
    __tablename__ = "ci_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    source_type = Column(Enum(CISourceType), nullable=False)
    config_json = Column(JSON, default=dict)  # Source-specific configuration
    enabled = Column(Integer, default=1)  # 0=disabled, 1=enabled
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ingest_runs = relationship(
        "CIIngestRun",
        back_populates="source",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_ci_source_org", "org_id"),
        UniqueConstraint("org_id", "name", name="uq_ci_source_org_name"),
    )


class CIIngestRun(Base):
    __tablename__ = "ci_ingest_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ci_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(
        Enum(CIIngestStatus),
        nullable=False,
        default=CIIngestStatus.QUEUED,
    )
    items_fetched = Column(Integer, default=0)
    items_upserted = Column(Integer, default=0)
    items_skipped = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    error_summary_json = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    source = relationship("CISource", back_populates="ingest_runs")

    __table_args__ = (
        Index("ix_ci_ingest_org_status", "org_id", "status"),
    )


class CICanonicalItem(Base):
    __tablename__ = "ci_canonical_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    competitor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ci_competitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ci_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    ingest_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ci_ingest_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    item_type = Column(Enum(CIItemType), nullable=False)
    external_id = Column(String(255), nullable=True)  # Source-specific ID (e.g., Meta ad ID)
    title = Column(String(512), nullable=True)
    body_text = Column(Text, nullable=True)
    url = Column(String(1024), nullable=True)
    image_urls_json = Column(JSON, default=list)
    canonical_json = Column(JSON, default=dict)  # Normalized structured data
    raw_json = Column(JSON, default=dict)  # Original raw data from source
    analysis_json = Column(JSON, nullable=True)  # LLM-generated strategic analysis
    embedding_id = Column(String(255), nullable=True)  # ChromaDB document ID
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    competitor = relationship("CICompetitor", back_populates="canonical_items")

    __table_args__ = (
        Index("ix_ci_item_org_type", "org_id", "item_type"),
        Index("ix_ci_item_competitor", "competitor_id"),
        Index("ix_ci_item_external", "org_id", "external_id"),
        UniqueConstraint(
            "org_id", "competitor_id", "item_type", "external_id",
            name="uq_ci_item_unique",
        ),
    )


# ── CI AutoLoop Run Ledger ──────────────────────────────────────────────────


class CIRunType(str, PyEnum):
    INGEST = "ingest"
    DETECT = "detect"
    GENERATE = "generate"  # Reserved for P1


class CIRunStatus(str, PyEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class CIRun(Base):
    """Auditable ledger of every CI AutoLoop run (ingest or detect)."""
    __tablename__ = "ci_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_type = Column(Enum(CIRunType), nullable=False)
    source = Column(String(50), nullable=True)  # "web", "meta_ads", "google_ads", "tiktok"
    status = Column(Enum(CIRunStatus), nullable=False, default=CIRunStatus.QUEUED)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    items_collected = Column(Integer, default=0)
    opportunities_created = Column(Integer, default=0)
    alerts_created = Column(Integer, default=0)
    job_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("job_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key = Column(String(255), nullable=True, unique=True)
    error_class = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict)  # durations, config snapshot, skip reason
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_ci_run_org_type", "org_id", "run_type"),
        Index("ix_ci_run_org_status", "org_id", "status"),
    )
