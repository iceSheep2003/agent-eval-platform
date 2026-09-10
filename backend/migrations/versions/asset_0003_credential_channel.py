"""add credential channel

Revision ID: asset_0003
Revises: asset_0002
Create Date: 2026-09-10

`Credential.channel` 是部署凭证限定的通道（`evl_` 用），SDK 上报密钥为 NULL。
模型早就加了这一列，但一直没补迁移——开发库靠 `create_all()` 侥幸建出来，
生产升级路径（`python -m backend.runtime.migrate`）会漏掉，写凭证时直接报
`no such column: asset_credential.channel`。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'asset_0003'
down_revision = 'asset_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('asset_credential', schema=None) as batch_op:
        batch_op.add_column(sa.Column('channel', sa.String(length=16), nullable=True))
        batch_op.create_index('ix_asset_credential_channel', ['channel'])


def downgrade() -> None:
    with op.batch_alter_table('asset_credential', schema=None) as batch_op:
        batch_op.drop_index('ix_asset_credential_channel')
        batch_op.drop_column('channel')
