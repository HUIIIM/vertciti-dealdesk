"""Google 登录：users.email 与 user_sessions

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23 02:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('email', sa.String(length=254), nullable=True))
        b.create_unique_constraint(op.f('uq_users_email'), ['email'])
    op.create_table('user_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_sha256', sa.String(length=64), nullable=False),
    sa.Column('username', sa.String(length=80), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=80), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_sessions')),
    sa.UniqueConstraint('token_sha256', name=op.f('uq_user_sessions_token_sha256'))
    )
    op.create_index(op.f('ix_user_sessions_username'), 'user_sessions', ['username'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_user_sessions_username'), table_name='user_sessions')
    op.drop_table('user_sessions')
    with op.batch_alter_table('users') as b:
        b.drop_constraint(op.f('uq_users_email'), type_='unique')
        b.drop_column('email')
