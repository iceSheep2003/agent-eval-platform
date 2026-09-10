"""asset_asset 加软删除标记

Revision ID: asset_0005
Revises: asset_0004
Create Date: 2026-09-10 18:00:00.000000+00:00

归档不删数据：历史 Run / Trace / 评分全部保留。硬删等于把「当时为什么这么判」
的证据一起删掉，而评测平台的价值一半在那。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'asset_0005'
down_revision = 'asset_0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'asset_asset',
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('asset_asset', 'deleted_at')
