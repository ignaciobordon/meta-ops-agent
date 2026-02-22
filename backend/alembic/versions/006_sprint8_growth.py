"""Sprint 8: Growth + Product — Onboarding, Templates, Alert Center, Analytics, Benchmarks, Events.

Revision ID: 006
Revises: 005
Create Date: 2026-02-17
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    # ── Enums ────────────────────────────────────────────────────────
    onboarding_status = sa.Enum(
        'pending', 'connect_meta', 'select_account', 'choose_template',
        'configure', 'syncing', 'completed',
        name='onboardingstatusenum',
    )
    onboarding_status.create(op.get_bind(), checkfirst=True)

    # ── org_templates (must be created before onboarding_states FK) ──
    op.create_table(
        'org_templates',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('slug', sa.String(100), unique=True, nullable=False, index=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('vertical', sa.String(100), nullable=False),
        sa.Column('default_config_json', sa.JSON, server_default='{}'),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )

    # ── onboarding_states ────────────────────────────────────────────
    op.create_table(
        'onboarding_states',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('current_step', onboarding_status, server_default='pending', nullable=False),
        sa.Column('meta_connected', sa.Boolean, server_default='false'),
        sa.Column('account_selected', sa.Boolean, server_default='false'),
        sa.Column('template_chosen', sa.Boolean, server_default='false'),
        sa.Column('selected_template_id', UUID(as_uuid=True), sa.ForeignKey('org_templates.id', ondelete='SET NULL'), nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )

    # ── org_configs ──────────────────────────────────────────────────
    op.create_table(
        'org_configs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('template_id', UUID(as_uuid=True), sa.ForeignKey('org_templates.id', ondelete='SET NULL'), nullable=True),
        sa.Column('config_json', sa.JSON, server_default='{}'),
        sa.Column('feature_flags_json', sa.JSON, server_default='{}'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )

    # ── org_benchmarks ───────────────────────────────────────────────
    op.create_table(
        'org_benchmarks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ad_account_id', UUID(as_uuid=True), sa.ForeignKey('meta_ad_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('metric_name', sa.String(50), nullable=False),
        sa.Column('baseline_value', sa.Float, nullable=False, server_default='0'),
        sa.Column('current_value', sa.Float, nullable=False, server_default='0'),
        sa.Column('delta_pct', sa.Float, nullable=False, server_default='0'),
        sa.Column('period_days', sa.Integer, server_default='30'),
        sa.Column('computed_at', sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint('org_id', 'ad_account_id', 'metric_name', name='uq_org_benchmark'),
    )

    # ── product_events ───────────────────────────────────────────────
    op.create_table(
        'product_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('event_name', sa.String(100), nullable=False),
        sa.Column('properties_json', sa.JSON, server_default='{}'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_product_event_org_name', 'product_events', ['org_id', 'event_name'])

    # ── MetaAlert extensions ─────────────────────────────────────────
    op.add_column('meta_alerts', sa.Column('status', sa.String(20), server_default='active', nullable=False))
    op.add_column('meta_alerts', sa.Column('acknowledged_by_user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    op.add_column('meta_alerts', sa.Column('acknowledged_at', sa.DateTime, nullable=True))
    op.create_index('ix_alert_org_status', 'meta_alerts', ['org_id', 'status'])

    # ── Seed 7 templates ─────────────────────────────────────────────
    templates = sa.table(
        'org_templates',
        sa.column('id', UUID(as_uuid=True)),
        sa.column('slug', sa.String),
        sa.column('name', sa.String),
        sa.column('description', sa.Text),
        sa.column('vertical', sa.String),
        sa.column('default_config_json', sa.JSON),
        sa.column('is_active', sa.Boolean),
    )

    import uuid
    seed_data = [
        {
            'id': str(uuid.UUID('a0000000-0000-0000-0000-000000000001')),
            'slug': 'gym_fitness',
            'name': 'Gym / Fitness Center',
            'description': 'Optimized for local gym and fitness studio campaigns. Focus on lead generation, class signups, and membership trials.',
            'vertical': 'fitness',
            'default_config_json': {
                'sync_interval_minutes': 15,
                'alert_thresholds': {'ctr_low': 0.8, 'cpa_high': 50, 'roas_low': 1.5, 'frequency_high': 4.0},
                'budget_guardrail_pct': 20,
                'enabled_alert_types': ['ctr_low', 'cpa_high', 'frequency_decay', 'spend_spike_no_conv', 'anomaly_spend'],
            },
            'is_active': True,
        },
        {
            'id': str(uuid.UUID('a0000000-0000-0000-0000-000000000002')),
            'slug': 'ecommerce_general',
            'name': 'E-commerce General',
            'description': 'For online stores selling physical or digital products. Focus on ROAS, conversions, and catalog sales.',
            'vertical': 'ecommerce',
            'default_config_json': {
                'sync_interval_minutes': 10,
                'alert_thresholds': {'ctr_low': 1.0, 'cpa_high': 30, 'roas_low': 2.0, 'frequency_high': 3.0},
                'budget_guardrail_pct': 15,
                'enabled_alert_types': ['ctr_low', 'cpa_high', 'roas_low', 'frequency_decay', 'anomaly_spend', 'anomaly_ctr'],
            },
            'is_active': True,
        },
        {
            'id': str(uuid.UUID('a0000000-0000-0000-0000-000000000003')),
            'slug': 'restaurant_local',
            'name': 'Restaurant / Local Food',
            'description': 'For restaurants and food delivery businesses. Focus on local reach, reservations, and order volume.',
            'vertical': 'food',
            'default_config_json': {
                'sync_interval_minutes': 15,
                'alert_thresholds': {'ctr_low': 0.7, 'cpa_high': 25, 'roas_low': 1.0, 'frequency_high': 5.0},
                'budget_guardrail_pct': 25,
                'enabled_alert_types': ['ctr_low', 'cpa_high', 'frequency_decay', 'anomaly_spend'],
            },
            'is_active': True,
        },
        {
            'id': str(uuid.UUID('a0000000-0000-0000-0000-000000000004')),
            'slug': 'saas_b2b',
            'name': 'SaaS B2B',
            'description': 'For B2B software companies. Focus on lead quality, demo signups, and cost per qualified lead.',
            'vertical': 'saas',
            'default_config_json': {
                'sync_interval_minutes': 30,
                'alert_thresholds': {'ctr_low': 0.5, 'cpa_high': 150, 'roas_low': 1.0, 'frequency_high': 3.0},
                'budget_guardrail_pct': 10,
                'enabled_alert_types': ['ctr_low', 'cpa_high', 'roas_low', 'spend_spike_no_conv', 'anomaly_spend', 'anomaly_cpc'],
            },
            'is_active': True,
        },
        {
            'id': str(uuid.UUID('a0000000-0000-0000-0000-000000000005')),
            'slug': 'real_estate',
            'name': 'Real Estate',
            'description': 'For real estate agents and property companies. Focus on lead generation and property views.',
            'vertical': 'real_estate',
            'default_config_json': {
                'sync_interval_minutes': 30,
                'alert_thresholds': {'ctr_low': 0.6, 'cpa_high': 100, 'roas_low': 1.0, 'frequency_high': 4.0},
                'budget_guardrail_pct': 15,
                'enabled_alert_types': ['ctr_low', 'cpa_high', 'frequency_decay', 'anomaly_spend'],
            },
            'is_active': True,
        },
        {
            'id': str(uuid.UUID('a0000000-0000-0000-0000-000000000006')),
            'slug': 'education_courses',
            'name': 'Education / Online Courses',
            'description': 'For online education platforms and course creators. Focus on enrollment, cost per enrollment, and engagement.',
            'vertical': 'education',
            'default_config_json': {
                'sync_interval_minutes': 15,
                'alert_thresholds': {'ctr_low': 0.8, 'cpa_high': 40, 'roas_low': 2.0, 'frequency_high': 3.5},
                'budget_guardrail_pct': 20,
                'enabled_alert_types': ['ctr_low', 'cpa_high', 'roas_low', 'frequency_decay', 'anomaly_spend'],
            },
            'is_active': True,
        },
        {
            'id': str(uuid.UUID('a0000000-0000-0000-0000-000000000007')),
            'slug': 'agency_generic',
            'name': 'Agency / Generic',
            'description': 'General-purpose template for agencies managing multiple verticals. Balanced thresholds and all alert types enabled.',
            'vertical': 'agency',
            'default_config_json': {
                'sync_interval_minutes': 10,
                'alert_thresholds': {'ctr_low': 0.8, 'cpa_high': 50, 'roas_low': 1.5, 'frequency_high': 4.0},
                'budget_guardrail_pct': 15,
                'enabled_alert_types': ['ctr_low', 'cpa_high', 'roas_low', 'frequency_decay', 'spend_spike_no_conv', 'anomaly_spend', 'anomaly_ctr', 'anomaly_cpc', 'anomaly_cpm'],
            },
            'is_active': True,
        },
    ]

    op.bulk_insert(templates, seed_data)


def downgrade():
    op.drop_index('ix_alert_org_status', table_name='meta_alerts')
    op.drop_column('meta_alerts', 'acknowledged_at')
    op.drop_column('meta_alerts', 'acknowledged_by_user_id')
    op.drop_column('meta_alerts', 'status')

    op.drop_index('ix_product_event_org_name', table_name='product_events')
    op.drop_table('product_events')
    op.drop_table('org_benchmarks')
    op.drop_table('org_configs')
    op.drop_table('onboarding_states')
    op.drop_table('org_templates')

    sa.Enum(name='onboardingstatusenum').drop(op.get_bind(), checkfirst=True)
