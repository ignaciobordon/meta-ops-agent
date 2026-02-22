"""Sprint 4: SaaS Commercial — subscriptions, usage, api_keys, branding, invites.

Revision ID: 002
Revises: 001
Create Date: 2026-02-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Subscriptions
    op.create_table(
        'subscriptions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('plan', sa.Enum('trial', 'pro', 'enterprise', 'white_label', name='planenum'), nullable=False),
        sa.Column('status', sa.Enum('trialing', 'active', 'past_due', 'canceled', 'incomplete', name='subscriptionstatusenum'), nullable=False),
        sa.Column('stripe_customer_id', sa.String(255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(255), nullable=True, unique=True),
        sa.Column('trial_ends_at', sa.DateTime, nullable=True),
        sa.Column('current_period_start', sa.DateTime, nullable=True),
        sa.Column('current_period_end', sa.DateTime, nullable=True),
        sa.Column('max_ad_accounts', sa.Integer, server_default='1'),
        sa.Column('max_decisions_per_month', sa.Integer, server_default='50'),
        sa.Column('max_creatives_per_month', sa.Integer, server_default='30'),
        sa.Column('allow_live_execution', sa.Boolean, server_default='false'),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
    )

    # Usage Events
    op.create_table(
        'usage_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('count', sa.Integer, server_default='1'),
        sa.Column('period_start', sa.DateTime, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('org_id', 'event_type', 'period_start', name='uq_usage_org_event_period'),
    )

    # API Keys
    op.create_table(
        'api_keys',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('key_hash', sa.String(64), unique=True, nullable=False, index=True),
        sa.Column('key_prefix', sa.String(8), nullable=False),
        sa.Column('scopes', sa.JSON, nullable=True),
        sa.Column('last_used_at', sa.DateTime, nullable=True),
        sa.Column('expires_at', sa.DateTime, nullable=True),
        sa.Column('revoked_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
    )

    # Brandings
    op.create_table(
        'brandings',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('logo_url', sa.String(512), nullable=True),
        sa.Column('primary_color', sa.String(7), server_default='#D4845C'),
        sa.Column('accent_color', sa.String(7), server_default='#8B9D5D'),
        sa.Column('company_name', sa.String(255), nullable=True),
        sa.Column('custom_domain', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
    )

    # Invites
    op.create_table(
        'invites',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('invited_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('role', sa.Enum('viewer', 'operator', 'director', 'admin', name='roleenum', create_type=False), nullable=True),
        sa.Column('token', sa.String(64), unique=True, nullable=False, index=True),
        sa.Column('accepted_at', sa.DateTime, nullable=True),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table('invites')
    op.drop_table('brandings')
    op.drop_table('api_keys')
    op.drop_table('usage_events')
    op.drop_table('subscriptions')
    # Drop new enums
    sa.Enum(name='subscriptionstatusenum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='planenum').drop(op.get_bind(), checkfirst=True)
