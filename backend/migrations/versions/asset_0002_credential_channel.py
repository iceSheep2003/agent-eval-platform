"""asset_credential 加通道限定列

Revision ID: asset_0002
Revises: asset_0001
Create Date: 2026-09-10 12:30:00.000000+00:00

部署密钥（`evl_`）按 Agent×通道签发，需要一列记住它限定哪个通道。
SDK 上报密钥（`evk_`）不限定通道，该列为 NULL。

**这一列此前只存在于 ORM 模型里、没有迁移**——开发态 `create_all()` 会建出来，
所以测试全绿，但生产走 `alembic upgrade` 建不出来，签发带通道的密钥会直接失败。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'asset_0002'
down_revision = 'asset_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'asset_credential',
        sa.Column('channel', sa.String(length=16), nullable=True),
    )
    with op.batch_alter_table('asset_credential', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_asset_credential_channel'), ['channel'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('asset_credential', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_asset_credential_channel'))

    op.drop_column('asset_credential', 'channel')
