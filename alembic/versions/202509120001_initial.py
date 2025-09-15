"""initial

Revision ID: 202509120001
Revises: 
Create Date: 2025-09-12 00:01:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '202509120001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table('call',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('call_id', sa.String(32), nullable=False, unique=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('agent_id', sa.String(16)),
        sa.Column('customer_id', sa.String(32)),
        sa.Column('skill', sa.String(64)),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    op.create_table('audio_asset',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('call_id', sa.String(32), sa.ForeignKey('call.call_id', ondelete='CASCADE')),
        sa.Column('s3_key', sa.Text(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('codec', sa.String(16)),
        sa.Column('sample_rate', sa.Integer()),
        sa.Column('duration_seconds', sa.Numeric(10,2)),
        sa.Column('size_bytes', sa.BigInteger()),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    op.create_table('scoring_result',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('call_id', sa.String(32), sa.ForeignKey('call.call_id', ondelete='CASCADE')),
        sa.Column('score', sa.Numeric(5,2), nullable=False),
        sa.Column('model_version', sa.String(32)),
        sa.Column('details', sa.JSON()),
        sa.Column('latency_ms', sa.Integer()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    op.create_table('ingestion_checkpoint',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('last_polled_from', sa.DateTime(), nullable=False),
        sa.Column('last_polled_to', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    op.create_table('agent',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('agent_id', sa.String(16), unique=True, nullable=False),
        sa.Column('full_name', sa.Text()),
        sa.Column('team', sa.String(64)),
        sa.Column('hire_date', sa.DateTime()),
        sa.Column('active', sa.Boolean(), server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )

    op.create_index('idx_call_status', 'call', ['status'])
    op.create_index('idx_scoring_result_created', 'scoring_result', ['created_at'])
    op.create_unique_constraint('uq_audio_asset_call', 'audio_asset', ['call_id'])

def downgrade() -> None:
    op.drop_constraint('uq_audio_asset_call', 'audio_asset', type_='unique')
    op.drop_index('idx_scoring_result_created', table_name='scoring_result')
    op.drop_index('idx_call_status', table_name='call')
    op.drop_table('agent')
    op.drop_table('ingestion_checkpoint')
    op.drop_table('scoring_result')
    op.drop_table('audio_asset')
    op.drop_table('call')
