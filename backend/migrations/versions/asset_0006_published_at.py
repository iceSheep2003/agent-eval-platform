"""asset_asset 加发布标记

Revision ID: asset_0006
Revises: asset_0005
Create Date: 2026-09-10 19:30:00.000000+00:00

**发布与租户隔离是两个轴**：`tenant_scope` 管「谁能看到数据」，
`published_at` 管「能不能被他人派生」。混用会导致注册即公开——所有资产默认
就是 workspace_shared，公共目录等于全量，形同虚设。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'asset_0006'
down_revision = 'asset_0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'asset_asset',
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('asset_asset', 'published_at')
