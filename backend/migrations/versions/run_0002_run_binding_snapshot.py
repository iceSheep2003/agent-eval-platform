"""add run binding snapshot

Revision ID: run_0002
Revises: run_0001
Create Date: 2026-09-10

约定：一个迁移文件只能操作自己模块前缀的表（由 branch_labels 标识）。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'run_0002'
down_revision = 'run_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('run_run', schema=None) as batch_op:
        # 存量 Run 没有引用快照，用空对象兜底（= 没有引用任何能力资产）。
        batch_op.add_column(
            sa.Column('binding_snapshot', sa.JSON(), nullable=False, server_default='{}')
        )
        batch_op.add_column(
            sa.Column('binding_overrides', sa.JSON(), nullable=False, server_default='{}')
        )


def downgrade() -> None:
    with op.batch_alter_table('run_run', schema=None) as batch_op:
        batch_op.drop_column('binding_overrides')
        batch_op.drop_column('binding_snapshot')
