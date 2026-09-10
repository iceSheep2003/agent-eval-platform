"""资源密钥与通道绑定

Revision ID: asset_0004
Revises: asset_0003
Create Date: 2026-09-10 16:00:00.000000+00:00

Agent 版本 spec 里只写密钥**名字**（`secrets[].name`）；真正的值放这里，
按「版本 × 通道」绑指针。值可轮换、指针可回滚，spec 保持不可变。

与 `asset_credential` 的分工：那张表是平台发给外部的凭证（只存哈希、不可还原），
这张表是 Agent 运行时要注入的密钥（必须可还原，故加密）。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'asset_0004'
down_revision = 'asset_0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('asset_resource_secret',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('workspace_id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('ciphertext', sa.String(length=1024), nullable=False),
    sa.Column('fingerprint', sa.String(length=16), nullable=False),
    sa.Column('description', sa.String(length=512), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('asset_resource_secret', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_asset_resource_secret_name'), ['name'], unique=False)
        batch_op.create_index(batch_op.f('ix_asset_resource_secret_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('asset_secret_binding',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('workspace_id', sa.String(length=64), nullable=False),
    sa.Column('asset_version_id', sa.String(length=64), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('secret_name', sa.String(length=128), nullable=False),
    sa.Column('resource_secret_id', sa.String(length=64), nullable=False),
    sa.Column('bound_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint(
        'asset_version_id', 'channel', 'secret_name', name='uq_secret_binding'
    )
    )
    with op.batch_alter_table('asset_secret_binding', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_asset_secret_binding_asset_version_id'), ['asset_version_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_asset_secret_binding_workspace_id'), ['workspace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('asset_secret_binding', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_asset_secret_binding_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_asset_secret_binding_asset_version_id'))

    op.drop_table('asset_secret_binding')
    with op.batch_alter_table('asset_resource_secret', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_asset_resource_secret_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_asset_resource_secret_name'))

    op.drop_table('asset_resource_secret')
