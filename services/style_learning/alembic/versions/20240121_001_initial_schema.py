"""Initial schema for style learning

Revision ID: 001
Revises:
Create Date: 2024-01-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create user_style_profiles table
    op.create_table(
        'user_style_profiles',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=128), nullable=False),
        sa.Column('style_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('style_summary', sa.Text(), nullable=True),
        sa.Column('samples_count', sa.Integer(), server_default='0', nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index('idx_style_profiles_user_id', 'user_style_profiles', ['user_id'], unique=True)

    # Create style_samples table
    op.create_table(
        'style_samples',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=128), nullable=False),
        sa.Column('message_hash', sa.String(length=64), nullable=False),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('analysis_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_user_message_hash', 'style_samples', ['user_id', 'message_hash'], unique=True)
    op.create_index('idx_style_samples_user_id', 'style_samples', ['user_id'], unique=False)

    # Create style_history table
    op.create_table(
        'style_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=128), nullable=False),
        sa.Column('style_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_user_snapshot_date', 'style_history', ['user_id', 'snapshot_date'], unique=True)
    op.create_index('idx_style_history_user_id', 'style_history', ['user_id'], unique=False)

    # Create trigger function for auto-updating updated_at
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create trigger on user_style_profiles
    op.execute("""
        CREATE TRIGGER trigger_style_profiles_updated
            BEFORE UPDATE ON user_style_profiles
            FOR EACH ROW EXECUTE FUNCTION update_updated_at();
    """)


def downgrade() -> None:
    # Drop trigger
    op.execute("DROP TRIGGER IF EXISTS trigger_style_profiles_updated ON user_style_profiles;")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at();")

    # Drop tables
    op.drop_index('idx_style_history_user_id', table_name='style_history')
    op.drop_index('idx_user_snapshot_date', table_name='style_history')
    op.drop_table('style_history')

    op.drop_index('idx_style_samples_user_id', table_name='style_samples')
    op.drop_index('idx_user_message_hash', table_name='style_samples')
    op.drop_table('style_samples')

    op.drop_index('idx_style_profiles_user_id', table_name='user_style_profiles')
    op.drop_table('user_style_profiles')
