"""限流计数表

Revision ID: portal_0003
Revises: portal_0002
Create Date: 2026-09-10 11:30:00.000000+00:00

对话是对 RuntimePort 的无界扇出，没有频率上限时单个用户就能打满执行面。
计数落库而不是放内存：多进程、重启都不失效。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'portal_0003'
down_revision = 'portal_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('portal_rate_limit',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('scope', sa.String(length=32), nullable=False),
    sa.Column('subject_id', sa.String(length=64), nullable=False),
    sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scope', 'subject_id', name='uq_portal_rate_limit')
    )
    with op.batch_alter_table('portal_rate_limit', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_portal_rate_limit_scope'), ['scope'], unique=False)
        batch_op.create_index(batch_op.f('ix_portal_rate_limit_subject_id'), ['subject_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('portal_rate_limit', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_portal_rate_limit_subject_id'))
        batch_op.drop_index(batch_op.f('ix_portal_rate_limit_scope'))

    op.drop_table('portal_rate_limit')
