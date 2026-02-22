"""Initial schema — captures all existing tables.

Revision ID: 001
Revises: None
Create Date: 2026-02-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Organizations
    op.create_table(
        'organizations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), unique=True, nullable=False, index=True),
        sa.Column('settings', sa.JSON, server_default='{}'),
        sa.Column('operator_armed', sa.Boolean, server_default='false'),
        sa.Column('active_ad_account_id', UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
    )

    # Users
    op.create_table(
        'users',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('avatar_url', sa.String(512), nullable=True),
        sa.Column('password_hash', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('last_login', sa.DateTime, nullable=True),
    )

    # User Org Roles
    op.create_table(
        'user_org_roles',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.Enum('viewer', 'operator', 'director', 'admin', name='roleenum'), nullable=False),
        sa.Column('assigned_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('user_id', 'org_id', name='uq_user_org'),
    )

    # Meta Connections
    op.create_table(
        'meta_connections',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('connected_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('access_token_encrypted', sa.Text, nullable=False),
        sa.Column('refresh_token_encrypted', sa.Text, nullable=True),
        sa.Column('token_expires_at', sa.DateTime, nullable=True),
        sa.Column('scopes', sa.JSON, nullable=True),
        sa.Column('status', sa.Enum('active', 'expired', 'revoked', 'error', name='connectionstatus'), server_default='active'),
        sa.Column('meta_user_id', sa.String(100), nullable=True),
        sa.Column('meta_user_name', sa.String(255), nullable=True),
        sa.Column('connected_at', sa.DateTime, nullable=False),
        sa.Column('last_synced_at', sa.DateTime, nullable=True),
    )

    # Ad Accounts
    op.create_table(
        'ad_accounts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('connection_id', UUID(as_uuid=True), sa.ForeignKey('meta_connections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('meta_ad_account_id', sa.String(100), unique=True, nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('currency', sa.String(10), server_default='USD'),
        sa.Column('spend_cap', sa.Float, nullable=True),
        sa.Column('meta_metadata', sa.JSON, nullable=True),
        sa.Column('synced_at', sa.DateTime, nullable=True),
    )

    # Add FK from organizations to ad_accounts (circular reference)
    op.create_foreign_key(
        'fk_org_active_ad_account',
        'organizations', 'ad_accounts',
        ['active_ad_account_id'], ['id'],
        ondelete='SET NULL',
    )

    # Decision Packs
    op.create_table(
        'decision_packs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('ad_account_id', UUID(as_uuid=True), sa.ForeignKey('ad_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('state', sa.Enum('draft', 'validating', 'ready', 'blocked', 'pending_approval', 'approved', 'rejected', 'executing', 'executed', 'failed', 'rolled_back', 'expired', name='decisionstate'), nullable=False, index=True),
        sa.Column('trace_id', sa.String(100), unique=True, nullable=False, index=True),
        sa.Column('action_type', sa.Enum('budget_change', 'adset_pause', 'creative_swap', 'bid_change', 'adset_duplicate', name='actiontype'), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', sa.String(100), nullable=True),
        sa.Column('entity_name', sa.String(255), nullable=True),
        sa.Column('before_snapshot', sa.JSON, nullable=True),
        sa.Column('after_proposal', sa.JSON, nullable=True),
        sa.Column('action_request', sa.JSON, nullable=False),
        sa.Column('rationale', sa.Text, nullable=True),
        sa.Column('source', sa.String(100), nullable=True),
        sa.Column('impact_prediction', sa.JSON, nullable=True),
        sa.Column('risk_score', sa.Float, server_default='0.0'),
        sa.Column('policy_result', sa.JSON, nullable=True),
        sa.Column('policy_checks', sa.JSON, nullable=True),
        sa.Column('execution_result', sa.JSON, nullable=True),
        sa.Column('dry_run_result', sa.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, index=True),
        sa.Column('validated_at', sa.DateTime, nullable=True),
        sa.Column('approved_at', sa.DateTime, nullable=True),
        sa.Column('rejected_at', sa.DateTime, nullable=True),
        sa.Column('executed_at', sa.DateTime, nullable=True),
        sa.Column('expires_at', sa.DateTime, nullable=True),
    )

    # Creatives
    op.create_table(
        'creatives',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('ad_account_id', UUID(as_uuid=True), sa.ForeignKey('ad_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('meta_ad_id', sa.String(100), unique=True, nullable=True, index=True),
        sa.Column('meta_adset_id', sa.String(100), nullable=True),
        sa.Column('meta_campaign_id', sa.String(100), nullable=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('ad_copy', sa.Text, nullable=True),
        sa.Column('headline', sa.String(255), nullable=True),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('thumbnail_url', sa.String(512), nullable=True),
        sa.Column('evaluation_score', sa.JSON, nullable=True),
        sa.Column('overall_score', sa.Float, nullable=True),
        sa.Column('scored_at', sa.DateTime, nullable=True),
        sa.Column('tags', sa.JSON, nullable=True),
        sa.Column('tagged_at', sa.DateTime, nullable=True),
        sa.Column('impressions', sa.Integer, server_default='0'),
        sa.Column('clicks', sa.Integer, server_default='0'),
        sa.Column('spend', sa.Float, server_default='0.0'),
        sa.Column('conversions', sa.Integer, server_default='0'),
        sa.Column('last_performance_sync', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
    )

    # Revoked Tokens
    op.create_table(
        'revoked_tokens',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('jti', sa.String(36), unique=True, nullable=False, index=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_type', sa.String(10), nullable=False),
        sa.Column('revoked_at', sa.DateTime, nullable=False, index=True),
        sa.Column('reason', sa.String(100), nullable=True),
        sa.Column('revoked_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )

    # User Sessions
    op.create_table(
        'user_sessions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('refresh_token_hash', sa.String(64), nullable=False, index=True),
        sa.Column('device_info', sa.String(255), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('last_used_at', sa.DateTime, nullable=True),
        sa.Column('revoked_at', sa.DateTime, nullable=True, index=True),
    )

    # Audit Entries
    op.create_table(
        'audit_entries',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('trace_id', sa.String(100), nullable=False, index=True),
        sa.Column('timestamp', sa.DateTime, nullable=False, index=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ad_account_id', UUID(as_uuid=True), sa.ForeignKey('ad_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('user_email', sa.String(255), nullable=True),
        sa.Column('action_type', sa.String(100), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', sa.String(100), nullable=True),
        sa.Column('decision_pack_id', UUID(as_uuid=True), sa.ForeignKey('decision_packs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('before_state', sa.JSON, nullable=True),
        sa.Column('after_state', sa.JSON, nullable=True),
        sa.Column('execution_result', sa.String(50), nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('reasoning_summary', sa.Text, nullable=True),
        sa.Column('audit_metadata', sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_table('audit_entries')
    op.drop_table('user_sessions')
    op.drop_table('revoked_tokens')
    op.drop_table('creatives')
    op.drop_table('decision_packs')
    op.drop_constraint('fk_org_active_ad_account', 'organizations', type_='foreignkey')
    op.drop_table('ad_accounts')
    op.drop_table('meta_connections')
    op.drop_table('user_org_roles')
    op.drop_table('users')
    op.drop_table('organizations')
