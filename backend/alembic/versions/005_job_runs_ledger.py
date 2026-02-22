"""Sprint 7: Job Runs Ledger.

Revision ID: 005
Revises: 004
Create Date: 2026-02-17
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    # Create jobrunstatus enum
    job_run_status = sa.Enum(
        'queued', 'running', 'succeeded', 'failed',
        'retry_scheduled', 'canceled', 'dead',
        name='jobrunstatus',
    )
    job_run_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'job_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scheduled_job_id', UUID(as_uuid=True),
                  sa.ForeignKey('scheduled_jobs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('job_type', sa.String(100), nullable=False),
        sa.Column('status', sa.Enum(
            'queued', 'running', 'succeeded', 'failed',
            'retry_scheduled', 'canceled', 'dead',
            name='jobrunstatus', create_type=False,
        ), nullable=False, server_default='queued'),
        sa.Column('payload_json', sa.JSON, nullable=True),
        sa.Column('idempotency_key', sa.String(255), nullable=True),
        sa.Column('attempts', sa.Integer, server_default='0'),
        sa.Column('max_attempts', sa.Integer, server_default='5'),
        sa.Column('scheduled_for', sa.DateTime, nullable=True),
        sa.Column('started_at', sa.DateTime, nullable=True),
        sa.Column('finished_at', sa.DateTime, nullable=True),
        sa.Column('last_error_code', sa.String(100), nullable=True),
        sa.Column('last_error_message', sa.Text, nullable=True),
        sa.Column('trace_id', sa.String(100), nullable=True),
        sa.Column('request_id', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint('org_id', 'job_type', 'idempotency_key',
                           name='uq_job_run_idempotency'),
    )

    op.create_index('ix_job_run_org_status', 'job_runs', ['org_id', 'status'])
    op.create_index('ix_job_run_type_status', 'job_runs', ['job_type', 'status'])


def downgrade():
    op.drop_index('ix_job_run_type_status', table_name='job_runs')
    op.drop_index('ix_job_run_org_status', table_name='job_runs')
    op.drop_table('job_runs')
    sa.Enum(name='jobrunstatus').drop(op.get_bind(), checkfirst=True)
