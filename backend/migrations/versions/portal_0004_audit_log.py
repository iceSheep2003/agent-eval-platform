"""审计日志表

Revision ID: portal_0004
Revises: portal_0003
Create Date: 2026-09-10 12:00:00.000000+00:00

谁在什么时候对什么做了什么。**只追加**——仓储不提供 update/delete。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'portal_0004'
down_revision = 'portal_0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('portal_audit_log',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('workspace_id', sa.String(length=64), nullable=True),
    sa.Column('actor_kind', sa.String(length=16), nullable=False),
    sa.Column('actor_id', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('target_kind', sa.String(length=32), nullable=True),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('portal_audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_portal_audit_log_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_portal_audit_log_actor_id'), ['actor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_portal_audit_log_target_id'), ['target_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_portal_audit_log_workspace_id'), ['workspace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('portal_audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_portal_audit_log_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_portal_audit_log_target_id'))
        batch_op.drop_index(batch_op.f('ix_portal_audit_log_actor_id'))
        batch_op.drop_index(batch_op.f('ix_portal_audit_log_action'))

    op.drop_table('portal_audit_log')
