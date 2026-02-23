"""
Database models for Meta Ops Agent SaaS platform.
Multi-tenant architecture with RBAC.
"""
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


# ── Enums ─────────────────────────────────────────────────────────────────────


class RoleEnum(str, PyEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    DIRECTOR = "director"
    ADMIN = "admin"


class DecisionState(str, PyEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    READY = "ready"
    BLOCKED = "blocked"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    EXPIRED = "expired"


class ConnectionStatus(str, PyEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class ActionType(str, PyEnum):
    BUDGET_CHANGE = "budget_change"
    ADSET_PAUSE = "adset_pause"
    CREATIVE_SWAP = "creative_swap"
    BID_CHANGE = "bid_change"
    ADSET_DUPLICATE = "adset_duplicate"


class PlanEnum(str, PyEnum):
    TRIAL = "trial"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    WHITE_LABEL = "white_label"


class SubscriptionStatusEnum(str, PyEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"


class OutcomeLabel(str, PyEnum):
    WIN = "win"
    NEUTRAL = "neutral"
    LOSS = "loss"
    UNKNOWN = "unknown"


class FeatureType(str, PyEnum):
    TAG = "tag"
    FRAMEWORK = "framework"
    OFFER = "offer"
    ACTION_TYPE = "action_type"


class InsightLevel(str, PyEnum):
    CAMPAIGN = "campaign"
    ADSET = "adset"
    AD = "ad"


class SyncJobType(str, PyEnum):
    META_SYNC_ASSETS = "meta_sync_assets"
    META_SYNC_INSIGHTS = "meta_sync_insights"
    META_LIVE_MONITOR = "meta_live_monitor"
    META_GENERATE_ALERTS = "meta_generate_alerts"


class SyncRunStatus(str, PyEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class AlertSeverity(str, PyEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class JobRunStatus(str, PyEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"
    CANCELED = "canceled"
    DEAD = "dead"


class ContentPackStatus(str, PyEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OnboardingStatusEnum(str, PyEnum):
    PENDING = "pending"
    CONNECT_META = "connect_meta"
    SELECT_ACCOUNT = "select_account"
    CHOOSE_TEMPLATE = "choose_template"
    CONFIGURE = "configure"
    SYNCING = "syncing"
    COMPLETED = "completed"


class AlertStatusEnum(str, PyEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SNOOZED = "snoozed"


# ── Plan Limits ──────────────────────────────────────────────────────────────

PLAN_LIMITS = {
    PlanEnum.TRIAL: {
        "max_ad_accounts": 1,
        "max_decisions_per_month": 50,
        "max_creatives_per_month": 30,
        "allow_live_execution": False,
    },
    PlanEnum.PRO: {
        "max_ad_accounts": 100,
        "max_decisions_per_month": 1000,
        "max_creatives_per_month": 500,
        "allow_live_execution": True,
    },
    PlanEnum.ENTERPRISE: {
        "max_ad_accounts": 9999,
        "max_decisions_per_month": 999999,
        "max_creatives_per_month": 999999,
        "allow_live_execution": True,
    },
    PlanEnum.WHITE_LABEL: {
        "max_ad_accounts": 9999,
        "max_decisions_per_month": 999999,
        "max_creatives_per_month": 999999,
        "allow_live_execution": True,
    },
}


# ── Models ────────────────────────────────────────────────────────────────────


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    settings = Column(JSON, default=dict)
    operator_armed = Column(Boolean, default=False)  # Workspace-level toggle
    active_ad_account_id = Column(UUID(as_uuid=True), ForeignKey("ad_accounts.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user_roles = relationship("UserOrgRole", back_populates="organization", cascade="all, delete-orphan")
    meta_connections = relationship("MetaConnection", back_populates="organization", cascade="all, delete-orphan")
    active_ad_account = relationship("AdAccount", foreign_keys=[active_ad_account_id])
    subscription = relationship("Subscription", back_populates="organization", uselist=False, cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="organization", cascade="all, delete-orphan")
    branding = relationship("Branding", back_populates="organization", uselist=False, cascade="all, delete-orphan")
    invites = relationship("Invite", back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    avatar_url = Column(String(512))
    password_hash = Column(String(255))  # For email/password auth (optional)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime)

    # Relationships
    org_roles = relationship("UserOrgRole", back_populates="user", cascade="all, delete-orphan")
    created_decisions = relationship("DecisionPack", foreign_keys="DecisionPack.created_by_user_id", back_populates="creator")
    approved_decisions = relationship("DecisionPack", foreign_keys="DecisionPack.approved_by_user_id", back_populates="approver")


class UserOrgRole(Base):
    __tablename__ = "user_org_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    role = Column(Enum(RoleEnum), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_user_org"),)

    # Relationships
    user = relationship("User", back_populates="org_roles")
    organization = relationship("Organization", back_populates="user_roles")


class MetaConnection(Base):
    __tablename__ = "meta_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    connected_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    access_token_encrypted = Column(Text, nullable=False)  # AES-256-GCM encrypted
    refresh_token_encrypted = Column(Text)
    token_expires_at = Column(DateTime)
    scopes = Column(JSON, default=lambda: ["ads_read"])  # ["ads_read", "ads_management"]
    status = Column(Enum(ConnectionStatus), default=ConnectionStatus.ACTIVE)
    meta_user_id = Column(String(100))  # Facebook user ID from /me
    meta_user_name = Column(String(255))  # Facebook user display name
    connected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_synced_at = Column(DateTime)

    # Relationships
    organization = relationship("Organization", back_populates="meta_connections")
    connected_by = relationship("User")
    ad_accounts = relationship("AdAccount", back_populates="connection", cascade="all, delete-orphan")


class AdAccount(Base):
    __tablename__ = "ad_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("meta_connections.id", ondelete="CASCADE"), nullable=False)
    meta_ad_account_id = Column(String(100), unique=True, nullable=False, index=True)  # Meta's ID (e.g., act_123456)
    name = Column(String(255), nullable=False)
    currency = Column(String(10), default="USD")
    spend_cap = Column(Float)  # Daily spend cap (soft limit)
    meta_metadata = Column(JSON, default=dict)  # Store timezone, business_id, etc.
    synced_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    connection = relationship("MetaConnection", back_populates="ad_accounts")
    decision_packs = relationship("DecisionPack", back_populates="ad_account", cascade="all, delete-orphan")
    creatives = relationship("Creative", back_populates="ad_account", cascade="all, delete-orphan")
    audit_entries = relationship("AuditEntry", back_populates="ad_account", cascade="all, delete-orphan")


class DecisionPack(Base):
    __tablename__ = "decision_packs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))

    # State
    state = Column(Enum(DecisionState), default=DecisionState.DRAFT, nullable=False, index=True)
    trace_id = Column(String(100), unique=True, nullable=False, index=True)

    # Action details
    action_type = Column(Enum(ActionType), nullable=False)
    entity_type = Column(String(50))  # "campaign", "adset", "ad"
    entity_id = Column(String(100))  # Meta entity ID
    entity_name = Column(String(255))

    # Data snapshots
    before_snapshot = Column(JSON, default=dict)
    after_proposal = Column(JSON, default=dict)
    action_request = Column(JSON, nullable=False)  # Full ActionRequest from CP5

    # Analysis
    rationale = Column(Text)
    source = Column(String(100))  # "SaturationEngine", "Manual", etc.
    impact_prediction = Column(JSON, default=dict)  # spend_change, cpa_change, confidence
    risk_score = Column(Float, default=0.0)

    # Policy
    policy_result = Column(JSON, default=dict)  # ValidationResult from CP5
    policy_checks = Column(JSON, default=list)  # List of PolicyCheck objects

    # Execution
    execution_result = Column(JSON)  # ActionResult from CP7
    dry_run_result = Column(JSON)  # Result of dry-run test (if performed)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    validated_at = Column(DateTime)
    approved_at = Column(DateTime)
    rejected_at = Column(DateTime)
    executed_at = Column(DateTime)
    expires_at = Column(DateTime)  # Auto-expire after 24h in PENDING_APPROVAL

    # Relationships
    ad_account = relationship("AdAccount", back_populates="decision_packs")
    creator = relationship("User", foreign_keys=[created_by_user_id], back_populates="created_decisions")
    approver = relationship("User", foreign_keys=[approved_by_user_id], back_populates="approved_decisions")


class Creative(Base):
    __tablename__ = "creatives"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False)

    # Meta IDs
    meta_ad_id = Column(String(100), unique=True, index=True)
    meta_adset_id = Column(String(100))
    meta_campaign_id = Column(String(100))

    # Creative data
    name = Column(String(255))
    ad_copy = Column(Text)  # Primary text
    headline = Column(String(255))
    description = Column(String(255))
    thumbnail_url = Column(String(512))

    # Scoring (from CP3)
    evaluation_score = Column(JSON)  # Full EvaluationScore object
    overall_score = Column(Float)  # 0-10
    scored_at = Column(DateTime)

    # Tagging (from CP2)
    tags = Column(JSON, default=list)  # [{ l1, l2, confidence, source }]
    tagged_at = Column(DateTime)

    # Source tracking (flywheel vs manual)
    source = Column(String(50), default="manual")  # "manual" | "flywheel"
    flywheel_metadata = Column(JSON, default=dict)  # {run_id, step, opportunities_used, ...}

    # Performance
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    conversions = Column(Integer, default=0)
    last_performance_sync = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    ad_account = relationship("AdAccount", back_populates="creatives")


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    jti = Column(String(36), unique=True, nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_type = Column(String(10), nullable=False)  # "access" or "refresh"
    revoked_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    reason = Column(String(100))  # "logout", "rotated", "theft_detected", "admin_revoke"
    revoked_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    refresh_token_hash = Column(String(64), nullable=False, index=True)
    device_info = Column(String(255))
    ip_address = Column(String(45))
    user_agent = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, index=True)  # NULL = active


class AuditEntry(Base):
    __tablename__ = "audit_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    trace_id = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Tenant context
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    user_email = Column(String(255))

    # Action
    action_type = Column(String(100), nullable=False)
    entity_type = Column(String(50))
    entity_id = Column(String(100))
    decision_pack_id = Column(UUID(as_uuid=True), ForeignKey("decision_packs.id", ondelete="SET NULL"))

    # State snapshots
    before_state = Column(JSON, default=dict)
    after_state = Column(JSON, default=dict)

    # Result
    execution_result = Column(String(50))  # "success", "failed", "rolled_back"
    error_message = Column(Text)

    # Context
    reasoning_summary = Column(Text)
    audit_metadata = Column(JSON, default=dict)

    # Relationships
    ad_account = relationship("AdAccount", back_populates="audit_entries")


# ── Sprint 4: SaaS Commercial Models ────────────────────────────────────────


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True)
    plan = Column(Enum(PlanEnum), nullable=False, default=PlanEnum.TRIAL)
    status = Column(Enum(SubscriptionStatusEnum), nullable=False, default=SubscriptionStatusEnum.TRIALING)

    # Stripe
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True, unique=True)

    # Billing period
    trial_ends_at = Column(DateTime, nullable=True)
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)

    # Plan limits (denormalized for fast checks)
    max_ad_accounts = Column(Integer, default=1)
    max_decisions_per_month = Column(Integer, default=50)
    max_creatives_per_month = Column(Integer, default=30)
    allow_live_execution = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="subscription")


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(50), nullable=False)  # "decision_create", "creative_generate"
    count = Column(Integer, default=1)
    period_start = Column(DateTime, nullable=False)  # First of month UTC
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "event_type", "period_start", name="uq_usage_org_event_period"),
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(100), nullable=False)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    key_prefix = Column(String(8), nullable=False)  # "moa_xxxx" visible portion
    scopes = Column(JSON, default=lambda: ["read"])
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="api_keys")
    created_by = relationship("User")


class Branding(Base):
    __tablename__ = "brandings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True)
    logo_url = Column(String(512), nullable=True)
    primary_color = Column(String(7), default="#D4845C")  # Terracotta
    accent_color = Column(String(7), default="#8B9D5D")  # Olive
    company_name = Column(String(255), nullable=True)
    custom_domain = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="branding")


class Invite(Base):
    __tablename__ = "invites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    invited_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False)
    role = Column(Enum(RoleEnum), default=RoleEnum.VIEWER)
    token = Column(String(64), unique=True, nullable=False, index=True)
    accepted_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="invites")
    invited_by = relationship("User")


# ── Sprint 5: Learning + Outcome Models ──────────────────────────────────────


class DecisionOutcome(Base):
    __tablename__ = "decision_outcomes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    decision_id = Column(UUID(as_uuid=True), ForeignKey("decision_packs.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(100), nullable=False)
    action_type = Column(Enum(ActionType), nullable=False)
    executed_at = Column(DateTime, nullable=False)
    dry_run = Column(Boolean, default=False)
    horizon_minutes = Column(Integer, nullable=False)  # 60, 1440, 4320

    # Metrics snapshots
    before_metrics_json = Column(JSON, default=dict)
    after_metrics_json = Column(JSON, default=dict)
    delta_metrics_json = Column(JSON, default=dict)

    # Labeling
    outcome_label = Column(Enum(OutcomeLabel), default=OutcomeLabel.UNKNOWN)
    confidence = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_outcome_org_id", "org_id"),
        Index("ix_outcome_decision_id", "decision_id"),
        Index("ix_outcome_entity_id", "entity_id"),
    )


class EntityMemory(Base):
    __tablename__ = "entity_memory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(100), nullable=False)

    # EMA baselines
    baseline_ema_json = Column(JSON, default=dict)  # {spend: X, ctr: Y, ...}
    volatility_json = Column(JSON, default=dict)  # {spend: X, ctr: Y, ...}

    # Trust
    trust_score = Column(Float, default=50.0)  # 0-100
    last_outcome_label = Column(Enum(OutcomeLabel), nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("org_id", "entity_type", "entity_id", name="uq_entity_memory"),
    )


class FeatureMemory(Base):
    __tablename__ = "feature_memory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    feature_type = Column(Enum(FeatureType), nullable=False)
    feature_key = Column(String(255), nullable=False)

    # Aggregated stats
    win_rate = Column(Float, default=0.0)  # 0-1
    avg_delta_json = Column(JSON, default=dict)  # {spend: X, ctr: Y, ...}
    samples = Column(Integer, default=0)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("org_id", "feature_type", "feature_key", name="uq_feature_memory"),
    )


class DecisionRanking(Base):
    __tablename__ = "decision_rankings"

    decision_id = Column(UUID(as_uuid=True), ForeignKey("decision_packs.id", ondelete="CASCADE"), primary_key=True)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)

    # Scores
    score_total = Column(Float, default=0.0)
    score_impact = Column(Float, default=0.0)
    score_risk = Column(Float, default=0.0)
    score_confidence = Column(Float, default=0.0)
    score_freshness = Column(Float, default=1.0)

    rank_version = Column(Integer, default=1)
    explanation_json = Column(JSON, default=dict)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    job_type = Column(String(50), nullable=False)  # "outcome_capture"
    reference_id = Column(UUID(as_uuid=True), nullable=False)  # Points to DecisionOutcome.id
    scheduled_for = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Sprint 6: retry support for meta sync jobs
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=5)
    error_message = Column(Text, nullable=True)
    next_run_at = Column(DateTime, nullable=True)  # For recurring jobs

    __table_args__ = (
        Index("ix_scheduled_job_pending", "scheduled_for", "job_type"),
    )


# ── Sprint 7: Job Runs Ledger ─────────────────────────────────────────────


class JobRun(Base):
    __tablename__ = "job_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    scheduled_job_id = Column(UUID(as_uuid=True), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    job_type = Column(String(100), nullable=False)
    status = Column(Enum(JobRunStatus), nullable=False, default=JobRunStatus.QUEUED)
    payload_json = Column(JSON, default=dict)
    idempotency_key = Column(String(255), nullable=True)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=5)
    scheduled_for = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    last_error_code = Column(String(100), nullable=True)
    last_error_message = Column(Text, nullable=True)
    trace_id = Column(String(100), nullable=True)
    request_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "job_type", "idempotency_key", name="uq_job_run_idempotency"),
        Index("ix_job_run_org_status", "org_id", "status"),
        Index("ix_job_run_type_status", "job_type", "status"),
    )


# ── Sprint 6: Meta Real Sync Engine ─────────────────────────────────────────


class MetaAdAccount(Base):
    __tablename__ = "meta_ad_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    meta_account_id = Column(String(100), nullable=False)  # act_123
    name = Column(String(255), nullable=True)
    currency = Column(String(10), default="USD")
    timezone_name = Column(String(100), nullable=True)
    status = Column(String(50), default="active")
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("org_id", "meta_account_id", name="uq_meta_ad_account"),
    )

    # Relationships
    campaigns = relationship("MetaCampaign", back_populates="ad_account", cascade="all, delete-orphan")
    adsets = relationship("MetaAdset", back_populates="ad_account", cascade="all, delete-orphan")
    ads = relationship("MetaAd", back_populates="ad_account", cascade="all, delete-orphan")


class MetaCampaign(Base):
    __tablename__ = "meta_campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id", ondelete="CASCADE"), nullable=False)
    meta_campaign_id = Column(String(100), nullable=False)
    name = Column(String(255), nullable=True)
    objective = Column(String(100), nullable=True)
    status = Column(String(50), nullable=True)
    effective_status = Column(String(50), nullable=True)
    daily_budget = Column(Float, nullable=True)
    lifetime_budget = Column(Float, nullable=True)
    bid_strategy = Column(String(100), nullable=True)
    created_time = Column(DateTime, nullable=True)
    updated_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("org_id", "meta_campaign_id", name="uq_meta_campaign"),
    )

    ad_account = relationship("MetaAdAccount", back_populates="campaigns")
    adsets = relationship("MetaAdset", back_populates="campaign", cascade="all, delete-orphan")


class MetaAdset(Base):
    __tablename__ = "meta_adsets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id", ondelete="CASCADE"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("meta_campaigns.id", ondelete="CASCADE"), nullable=False)
    meta_adset_id = Column(String(100), nullable=False)
    name = Column(String(255), nullable=True)
    status = Column(String(50), nullable=True)
    effective_status = Column(String(50), nullable=True)
    daily_budget = Column(Float, nullable=True)
    lifetime_budget = Column(Float, nullable=True)
    optimization_goal = Column(String(100), nullable=True)
    billing_event = Column(String(100), nullable=True)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("org_id", "meta_adset_id", name="uq_meta_adset"),
    )

    ad_account = relationship("MetaAdAccount", back_populates="adsets")
    campaign = relationship("MetaCampaign", back_populates="adsets")
    ads = relationship("MetaAd", back_populates="adset", cascade="all, delete-orphan")


class MetaAd(Base):
    __tablename__ = "meta_ads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id", ondelete="CASCADE"), nullable=False)
    adset_id = Column(UUID(as_uuid=True), ForeignKey("meta_adsets.id", ondelete="CASCADE"), nullable=False)
    meta_ad_id = Column(String(100), nullable=False)
    name = Column(String(255), nullable=True)
    status = Column(String(50), nullable=True)
    effective_status = Column(String(50), nullable=True)
    creative_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("org_id", "meta_ad_id", name="uq_meta_ad"),
    )

    ad_account = relationship("MetaAdAccount", back_populates="ads")
    adset = relationship("MetaAdset", back_populates="ads")


class MetaInsightsDaily(Base):
    __tablename__ = "meta_insights_daily"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id", ondelete="CASCADE"), nullable=False)
    level = Column(Enum(InsightLevel), nullable=False)
    entity_meta_id = Column(String(100), nullable=False)
    date_start = Column(DateTime, nullable=False)
    date_stop = Column(DateTime, nullable=False)

    # Metric columns (all nullable for partial data)
    spend = Column(Float, nullable=True)
    impressions = Column(Integer, nullable=True)
    clicks = Column(Integer, nullable=True)
    ctr = Column(Float, nullable=True)
    cpm = Column(Float, nullable=True)
    cpc = Column(Float, nullable=True)
    frequency = Column(Float, nullable=True)
    conversions = Column(Integer, nullable=True)
    purchase_roas = Column(Float, nullable=True)

    # Flexible JSON for actions/conversions breakdown
    actions_json = Column(JSON, nullable=True)
    conversions_json = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "org_id", "ad_account_id", "level", "entity_meta_id", "date_start",
            name="uq_meta_insights_daily",
        ),
        Index("ix_insights_entity", "org_id", "entity_meta_id", "date_start"),
    )


class MetaSyncRun(Base):
    __tablename__ = "meta_sync_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id", ondelete="CASCADE"), nullable=True)
    job_type = Column(String(50), nullable=False)  # assets|insights|monitor|insights_engine
    status = Column(Enum(SyncRunStatus), nullable=False, default=SyncRunStatus.SUCCESS)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    items_upserted = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    error_summary_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MetaAlert(Base):
    __tablename__ = "meta_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id", ondelete="CASCADE"), nullable=True)
    alert_type = Column(String(100), nullable=False)  # ctr_low, cpa_high, frequency_decay, spend_spike, drift_*
    severity = Column(Enum(AlertSeverity), nullable=False, default=AlertSeverity.MEDIUM)
    message = Column(Text, nullable=False)
    entity_type = Column(String(50), nullable=True)
    entity_meta_id = Column(String(100), nullable=True)
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    payload_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Sprint 8: Alert Center extensions
    status = Column(String(20), default="active", nullable=False)
    acknowledged_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_alert_org_severity", "org_id", "severity"),
        Index("ix_alert_org_status", "org_id", "status"),
    )


# ── Sprint 8: Growth + Product Models ─────────────────────────────────────────


class OnboardingState(Base):
    __tablename__ = "onboarding_states"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    current_step = Column(Enum(OnboardingStatusEnum), default=OnboardingStatusEnum.PENDING, nullable=False)
    meta_connected = Column(Boolean, default=False)
    account_selected = Column(Boolean, default=False)
    template_chosen = Column(Boolean, default=False)
    selected_template_id = Column(UUID(as_uuid=True), ForeignKey("org_templates.id", ondelete="SET NULL"), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OrgTemplate(Base):
    __tablename__ = "org_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    vertical = Column(String(100), nullable=False)
    default_config_json = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OrgConfig(Base):
    __tablename__ = "org_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True)
    template_id = Column(UUID(as_uuid=True), ForeignKey("org_templates.id", ondelete="SET NULL"), nullable=True)
    config_json = Column(JSON, default=dict)
    feature_flags_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OrgBenchmark(Base):
    __tablename__ = "org_benchmarks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id", ondelete="CASCADE"), nullable=False)
    metric_name = Column(String(50), nullable=False)
    baseline_value = Column(Float, nullable=False, default=0.0)
    current_value = Column(Float, nullable=False, default=0.0)
    delta_pct = Column(Float, nullable=False, default=0.0)
    period_days = Column(Integer, default=30)
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "ad_account_id", "metric_name", name="uq_org_benchmark"),
    )


class ProductEvent(Base):
    __tablename__ = "product_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event_name = Column(String(100), nullable=False)
    properties_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_product_event_org_name", "org_id", "event_name"),
    )


# ── Sprint 13: Content Studio ─────────────────────────────────────────────


class ContentPack(Base):
    __tablename__ = "content_packs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    creative_id = Column(UUID(as_uuid=True), ForeignKey("creatives.id", ondelete="SET NULL"), nullable=True)
    status = Column(Enum(ContentPackStatus), nullable=False, default=ContentPackStatus.QUEUED)
    goal = Column(String(50), nullable=True)  # awareness / leads / sales / retention
    language = Column(String(10), default="es-AR")
    channels_json = Column(JSON, default=list)  # [{channel, format}]
    input_json = Column(JSON, default=dict)  # tone_tags, curator_prompt, framework, hook_style, audience, etc.
    job_run_id = Column(UUID(as_uuid=True), ForeignKey("job_runs.id", ondelete="SET NULL"), nullable=True)
    last_error_code = Column(String(100), nullable=True)
    last_error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    variants = relationship("ContentVariant", back_populates="content_pack", cascade="all, delete-orphan")
    channel_locks = relationship("ContentChannelLock", back_populates="content_pack", cascade="all, delete-orphan")
    exports = relationship("ContentExport", back_populates="content_pack", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_content_pack_org", "org_id"),
        Index("ix_content_pack_status", "status"),
    )


class ContentVariant(Base):
    __tablename__ = "content_variants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    content_pack_id = Column(UUID(as_uuid=True), ForeignKey("content_packs.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(50), nullable=False)  # ig_reel, ig_post, tiktok_short, etc.
    format = Column(String(50), nullable=True)  # 9x16_30s, 1x1, carousel_10, etc.
    variant_index = Column(Integer, nullable=False)  # 1..6
    output_json = Column(JSON, default=dict)  # Full structured output per ChannelSpec
    score = Column(Float, default=0.0)  # 0-100
    score_breakdown_json = Column(JSON, default=dict)
    rationale_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    content_pack = relationship("ContentPack", back_populates="variants")

    __table_args__ = (
        Index("ix_variant_pack_channel", "content_pack_id", "channel"),
    )


class ContentChannelLock(Base):
    __tablename__ = "content_channel_locks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    content_pack_id = Column(UUID(as_uuid=True), ForeignKey("content_packs.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(50), nullable=False)
    locked_variant_id = Column(UUID(as_uuid=True), ForeignKey("content_variants.id", ondelete="CASCADE"), nullable=False)
    locked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    locked_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    content_pack = relationship("ContentPack", back_populates="channel_locks")
    locked_variant = relationship("ContentVariant")

    __table_args__ = (
        UniqueConstraint("content_pack_id", "channel", name="uq_channel_lock_pack_channel"),
    )


class ContentExport(Base):
    __tablename__ = "content_exports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    content_pack_id = Column(UUID(as_uuid=True), ForeignKey("content_packs.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(10), nullable=False)  # "pdf" or "xlsx"
    filename = Column(String(255), nullable=False)
    storage_ref = Column(String(512), nullable=True)  # File path or S3 ref
    size_bytes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    content_pack = relationship("ContentPack", back_populates="exports")


# ── BrandMap Profiles ──────────────────────────────────────────────────────


class BrandMapProfile(Base):
    __tablename__ = "brand_map_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    raw_text = Column(Text, nullable=False)
    structured_json = Column(JSON, nullable=True)  # 9-layer BrandMap from LLM analysis
    status = Column(String(30), default="pending_analysis", nullable=False)  # pending_analysis | analyzing | ready | error
    last_analyzed_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_brand_map_profile_org", "org_id"),
    )


# ── Sprint 13: Flywheel & Data Room ────────────────────────────────────────


class FlywheelRun(Base):
    __tablename__ = "flywheel_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    ad_account_id = Column(UUID(as_uuid=True), ForeignKey("meta_ad_accounts.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(30), nullable=False, default="queued")  # queued/running/succeeded/failed
    trigger = Column(String(20), nullable=False, default="manual")  # manual/scheduled
    config_json = Column(JSON, default=dict)
    outputs_json = Column(JSON, default=dict)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    steps = relationship("FlywheelStep", back_populates="flywheel_run", cascade="all, delete-orphan")


class FlywheelStep(Base):
    __tablename__ = "flywheel_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    flywheel_run_id = Column(UUID(as_uuid=True), ForeignKey("flywheel_runs.id", ondelete="CASCADE"), nullable=False)
    step_name = Column(String(100), nullable=False)
    step_order = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default="pending")  # pending/running/succeeded/failed/skipped
    job_run_id = Column(UUID(as_uuid=True), ForeignKey("job_runs.id", ondelete="SET NULL"), nullable=True)
    artifacts_json = Column(JSON, default=dict)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    flywheel_run = relationship("FlywheelRun", back_populates="steps")


class DataExport(Base):
    __tablename__ = "data_exports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(30), nullable=False, default="queued")
    requested_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    params_json = Column(JSON, default=dict)
    file_path = Column(String(512), nullable=True)
    rows_exported = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    trace_id = Column(String(100), nullable=True)
    job_run_id = Column(UUID(as_uuid=True), ForeignKey("job_runs.id", ondelete="SET NULL"), nullable=True)
