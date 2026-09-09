"""portal_user 加登录锁定字段

Revision ID: portal_0002
Revises: portal_0001
Create Date: 2026-09-10 11:00:00.000000+00:00

连续失败 5 次锁定 15 分钟，抵挡密码暴力破解。字段带默认值，既有行不受影响。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'portal_0002'
down_revision = 'portal_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'portal_user',
        sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'portal_user',
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('portal_user', 'locked_until')
    op.drop_column('portal_user', 'failed_attempts')
