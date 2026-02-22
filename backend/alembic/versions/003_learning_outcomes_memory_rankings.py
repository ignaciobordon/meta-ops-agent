"""Sprint 5: Learning Loop — outcomes, entity memory, feature memory, rankings, jobs.

Revision ID: 003
Revises: 002
Create Date: 2026-02-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New enums
    outcome_label = sa.Enum('win', 'neutral', 'loss', 'unknown', name='outcomelabel')
    outcome_label.create(op.get_bind(), checkfirst=True)

    feature_type = sa.Enum('tag', 'framework', 'offer', 'action_type', name='featuretype')
    feature_type.create(op.get_bind(), checkfirst=True)

    # Decision Outcomes
    op.create_table(
        'decision_outcomes',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('decision_id', UUID(as_uuid=True), sa.ForeignKey('decision_packs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', sa.String(100), nullable=False),
        sa.Column('action_type', sa.Enum('budget_change', 'adset_pause', 'creative_swap', 'bid_change', 'adset_duplicate', name='actiontype', create_type=False), nullable=False),
        sa.Column('executed_at', sa.DateTime, nullable=False),
        sa.Column('dry_run', sa.Boolean, server_default='false'),
        sa.Column('horizon_minutes', sa.Integer, nullable=False),
        sa.Column('before_metrics_json', sa.JSON, nullable=True),
        sa.Column('after_metrics_json', sa.JSON, nullable=True),
        sa.Column('delta_metrics_json', sa.JSON, nullable=True),
        sa.Column('outcome_label', sa.Enum('win', 'neutral', 'loss', 'unknown', name='outcomelabel', create_type=False), server_default='unknown'),
        sa.Column('confidence', sa.Float, server_default='0.0'),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
    )
    op.create_index('ix_outcome_org_id', 'decision_outcomes', ['org_id'])
    op.create_index('ix_outcome_decision_id', 'decision_outcomes', ['decision_id'])
    op.create_index('ix_outcome_entity_id', 'decision_outcomes', ['entity_id'])

    # Entity Memory
    op.create_table(
        'entity_memory',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', sa.String(100), nullable=False),
        sa.Column('baseline_ema_json', sa.JSON, nullable=True),
        sa.Column('volatility_json', sa.JSON, nullable=True),
        sa.Column('trust_score', sa.Float, server_default='50.0'),
        sa.Column('last_outcome_label', sa.Enum('win', 'neutral', 'loss', 'unknown', name='outcomelabel', create_type=False), nullable=True),
        sa.Column('last_seen_at', sa.DateTime, nullable=True),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint('org_id', 'entity_type', 'entity_id', name='uq_entity_memory'),
    )

    # Feature Memory
    op.create_table(
        'feature_memory',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('feature_type', sa.Enum('tag', 'framework', 'offer', 'action_type', name='featuretype', create_type=False), nullable=False),
        sa.Column('feature_key', sa.String(255), nullable=False),
        sa.Column('win_rate', sa.Float, server_default='0.0'),
        sa.Column('avg_delta_json', sa.JSON, nullable=True),
        sa.Column('samples', sa.Integer, server_default='0'),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint('org_id', 'feature_type', 'feature_key', name='uq_feature_memory'),
    )

    # Decision Rankings
    op.create_table(
        'decision_rankings',
        sa.Column('decision_id', UUID(as_uuid=True), sa.ForeignKey('decision_packs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('score_total', sa.Float, server_default='0.0'),
        sa.Column('score_impact', sa.Float, server_default='0.0'),
        sa.Column('score_risk', sa.Float, server_default='0.0'),
        sa.Column('score_confidence', sa.Float, server_default='0.0'),
        sa.Column('score_freshness', sa.Float, server_default='1.0'),
        sa.Column('rank_version', sa.Integer, server_default='1'),
        sa.Column('explanation_json', sa.JSON, nullable=True),
        sa.Column('updated_at', sa.DateTime, nullable=True),
    )

    # Scheduled Jobs
    op.create_table(
        'scheduled_jobs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('job_type', sa.String(50), nullable=False),
        sa.Column('reference_id', UUID(as_uuid=True), nullable=False),
        sa.Column('scheduled_for', sa.DateTime, nullable=False),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
    )
    op.create_index('ix_scheduled_job_pending', 'scheduled_jobs', ['scheduled_for', 'job_type'])


def downgrade() -> None:
    op.drop_table('scheduled_jobs')
    op.drop_table('decision_rankings')
    op.drop_table('feature_memory')
    op.drop_table('entity_memory')
    op.drop_table('decision_outcomes')
    # Drop new enums
    sa.Enum(name='featuretype').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='outcomelabel').drop(op.get_bind(), checkfirst=True)
