"""device grants (agents signing in, D-028)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25 12:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('device_grants',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_code_hash', sa.String(length=64), nullable=False),
    sa.Column('user_code', sa.String(length=16), nullable=False),
    sa.Column('client_name', sa.String(length=60), nullable=False),
    sa.Column('scopes', sa.String(length=100), nullable=False),
    sa.Column('client_ip', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('granted_scopes', sa.String(length=100), nullable=True),
    sa.Column('token_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('last_polled_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['token_id'], ['api_tokens.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('device_code_hash'),
    sa.UniqueConstraint('user_code')
    )


def downgrade():
    op.drop_table('device_grants')
