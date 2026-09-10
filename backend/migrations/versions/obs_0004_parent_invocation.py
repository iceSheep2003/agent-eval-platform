"""obs_trace 加父调用

Revision ID: obs_0004
Revises: obs_0003
Create Date: 2026-09-10 20:00:00.000000+00:00

编排（多 Agent）的调用树靠这一列连通。没有它，编排去调子 Agent 时两次调用
在 Trace 里是两棵互不相干的树——拿不到「整个系统这次花了多少」、
归因不到「子 Agent 失败是编排的问题还是它自己的」。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'obs_0004'
down_revision = 'obs_0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'obs_trace',
        sa.Column('parent_invocation_id', sa.String(length=64), nullable=True),
    )
    with op.batch_alter_table('obs_trace', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_obs_trace_parent_invocation_id'),
            ['parent_invocation_id'],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('obs_trace', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_obs_trace_parent_invocation_id'))

    op.drop_column('obs_trace', 'parent_invocation_id')
