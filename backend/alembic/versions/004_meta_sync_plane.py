"""Sprint 6: Meta Real Sync Engine — assets, insights, sync runs, alerts.

Revision ID: 004
Revises: 003
Create Date: 2026-02-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New enums
    insight_level = sa.Enum('campaign', 'adset', 'ad', name='insightlevel')
    insight_level.create(op.get_bind(), checkfirst=True)

    sync_run_status = sa.Enum('success', 'partial', 'failed', name='syncrunstatus')
    sync_run_status.create(op.get_bind(), checkfirst=True)

    alert_severity = sa.Enum('critical', 'high', 'medium', 'low', 'info', name='alertseverity')
    alert_severity.create(op.get_bind(), checkfirst=True)

    # Extend scheduled_jobs with retry + recurring support
    op.add_column('scheduled_jobs', sa.Column('attempts', sa.Integer, server_default='0'))
    op.add_column('scheduled_jobs', sa.Column('max_attempts', sa.Integer, server_default='5'))
    op.add_column('scheduled_jobs', sa.Column('error_message', sa.Text, nullable=True))
    op.add_column('scheduled_jobs', sa.Column('next_run_at', sa.DateTime, nullable=True))

    # 1) meta_ad_accounts
    op.create_table(
        'meta_ad_accounts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('meta_account_id', sa.String(100), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('currency', sa.String(10), server_default='USD'),
        sa.Column('timezone_name', sa.String(100), nullable=True),
        sa.Column('status', sa.String(50), server_default='active'),
        sa.Column('last_synced_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint('org_id', 'meta_account_id', name='uq_meta_ad_account'),
    )

    # 2) meta_campaigns
    op.create_table(
        'meta_campaigns',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ad_account_id', UUID(as_uuid=True), sa.ForeignKey('meta_ad_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('meta_campaign_id', sa.String(100), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('objective', sa.String(100), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('effective_status', sa.String(50), nullable=True),
        sa.Column('daily_budget', sa.Float, nullable=True),
        sa.Column('lifetime_budget', sa.Float, nullable=True),
        sa.Column('bid_strategy', sa.String(100), nullable=True),
        sa.Column('created_time', sa.DateTime, nullable=True),
        sa.Column('updated_time', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint('org_id', 'meta_campaign_id', name='uq_meta_campaign'),
    )

    # 3) meta_adsets
    op.create_table(
        'meta_adsets',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ad_account_id', UUID(as_uuid=True), sa.ForeignKey('meta_ad_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('campaign_id', UUID(as_uuid=True), sa.ForeignKey('meta_campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('meta_adset_id', sa.String(100), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('effective_status', sa.String(50), nullable=True),
        sa.Column('daily_budget', sa.Float, nullable=True),
        sa.Column('lifetime_budget', sa.Float, nullable=True),
        sa.Column('optimization_goal', sa.String(100), nullable=True),
        sa.Column('billing_event', sa.String(100), nullable=True),
        sa.Column('start_time', sa.DateTime, nullable=True),
        sa.Column('end_time', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint('org_id', 'meta_adset_id', name='uq_meta_adset'),
    )

    # 4) meta_ads
    op.create_table(
        'meta_ads',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ad_account_id', UUID(as_uuid=True), sa.ForeignKey('meta_ad_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('adset_id', UUID(as_uuid=True), sa.ForeignKey('meta_adsets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('meta_ad_id', sa.String(100), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('effective_status', sa.String(50), nullable=True),
        sa.Column('creative_id', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint('org_id', 'meta_ad_id', name='uq_meta_ad'),
    )

    # 5) meta_insights_daily
    op.create_table(
        'meta_insights_daily',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ad_account_id', UUID(as_uuid=True), sa.ForeignKey('meta_ad_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('level', sa.Enum('campaign', 'adset', 'ad', name='insightlevel', create_type=False), nullable=False),
        sa.Column('entity_meta_id', sa.String(100), nullable=False),
        sa.Column('date_start', sa.DateTime, nullable=False),
        sa.Column('date_stop', sa.DateTime, nullable=False),
        sa.Column('spend', sa.Float, nullable=True),
        sa.Column('impressions', sa.Integer, nullable=True),
        sa.Column('clicks', sa.Integer, nullable=True),
        sa.Column('ctr', sa.Float, nullable=True),
        sa.Column('cpm', sa.Float, nullable=True),
        sa.Column('cpc', sa.Float, nullable=True),
        sa.Column('frequency', sa.Float, nullable=True),
        sa.Column('conversions', sa.Integer, nullable=True),
        sa.Column('purchase_roas', sa.Float, nullable=True),
        sa.Column('actions_json', sa.JSON, nullable=True),
        sa.Column('conversions_json', sa.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint(
            'org_id', 'ad_account_id', 'level', 'entity_meta_id', 'date_start',
            name='uq_meta_insights_daily',
        ),
    )
    op.create_index('ix_insights_entity', 'meta_insights_daily', ['org_id', 'entity_meta_id', 'date_start'])

    # 6) meta_sync_runs
    op.create_table(
        'meta_sync_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ad_account_id', UUID(as_uuid=True), sa.ForeignKey('meta_ad_accounts.id', ondelete='CASCADE'), nullable=True),
        sa.Column('job_type', sa.String(50), nullable=False),
        sa.Column('status', sa.Enum('success', 'partial', 'failed', name='syncrunstatus', create_type=False), nullable=False),
        sa.Column('started_at', sa.DateTime, nullable=False),
        sa.Column('finished_at', sa.DateTime, nullable=True),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        sa.Column('items_upserted', sa.Integer, server_default='0'),
        sa.Column('error_count', sa.Integer, server_default='0'),
        sa.Column('error_summary_json', sa.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
    )

    # 7) meta_alerts
    op.create_table(
        'meta_alerts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ad_account_id', UUID(as_uuid=True), sa.ForeignKey('meta_ad_accounts.id', ondelete='CASCADE'), nullable=True),
        sa.Column('alert_type', sa.String(100), nullable=False),
        sa.Column('severity', sa.Enum('critical', 'high', 'medium', 'low', 'info', name='alertseverity', create_type=False), nullable=False),
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_meta_id', sa.String(100), nullable=True),
        sa.Column('detected_at', sa.DateTime, nullable=False),
        sa.Column('resolved_at', sa.DateTime, nullable=True),
        sa.Column('payload_json', sa.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
    )
    op.create_index('ix_alert_org_severity', 'meta_alerts', ['org_id', 'severity'])


def downgrade() -> None:
    op.drop_table('meta_alerts')
    op.drop_table('meta_sync_runs')
    op.drop_table('meta_insights_daily')
    op.drop_table('meta_ads')
    op.drop_table('meta_adsets')
    op.drop_table('meta_campaigns')
    op.drop_table('meta_ad_accounts')

    # Remove added columns from scheduled_jobs
    op.drop_column('scheduled_jobs', 'next_run_at')
    op.drop_column('scheduled_jobs', 'error_message')
    op.drop_column('scheduled_jobs', 'max_attempts')
    op.drop_column('scheduled_jobs', 'attempts')

    # Drop new enums
    sa.Enum(name='alertseverity').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='syncrunstatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='insightlevel').drop(op.get_bind(), checkfirst=True)
