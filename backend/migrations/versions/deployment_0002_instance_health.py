"""add instance health columns

Revision ID: deployment_0002
Revises: deployment_0001
Create Date: 2026-09-10

探活要记两件事：连续失败次数（成功一次即清零）与最近一次失败原因。
没有它们就只能「一失败就判死」，单次网络抖动会把健康实例摘掉。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'deployment_0002'
down_revision = 'deployment_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('deployment_instance', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(sa.Column('last_health_error', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('deployment_instance', schema=None) as batch_op:
        batch_op.drop_column('last_health_error')
        batch_op.drop_column('consecutive_failures')
