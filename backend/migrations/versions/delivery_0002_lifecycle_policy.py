"""add lifecycle policy override

Revision ID: delivery_0002
Revises: delivery_0001
Create Date: 2026-09-10

工作区级的**治理策略覆盖**。没有行 = 用平台默认策略（`domain/lifecycle.DEFAULT_POLICY`）。

策略是数据不是代码：加通道、换检查组合、调阈值、改谁能操作，都改这张表的内容，
不用同时动 domain / application / api / Permission 四个地方。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'delivery_0002'
down_revision = 'delivery_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'delivery_lifecycle_policy',
        sa.Column('workspace_id', sa.String(length=64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('updated_by', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id'),
    )


def downgrade() -> None:
    op.drop_table('delivery_lifecycle_policy')
