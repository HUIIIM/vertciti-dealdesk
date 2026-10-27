"""web sessions for Google sign-in (browser cookie sessions, revocable)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('web_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_sha256', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=80), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_web_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_web_sessions')),
    sa.UniqueConstraint('token_sha256', name=op.f('uq_web_sessions_token_sha256'))
    )
    op.create_index('ix_web_sessions_user', 'web_sessions', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_web_sessions_user', table_name='web_sessions')
    op.drop_table('web_sessions')
