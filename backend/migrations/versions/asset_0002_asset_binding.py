"""add asset binding

Revision ID: asset_0002
Revises: asset_0001
Create Date: 2026-09-10

约定：一个迁移文件只能操作自己模块前缀的表（由 branch_labels 标识）。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'asset_0002'
down_revision = 'asset_0001'
branch_labels = ('asset',)
depends_on = None


def upgrade() -> None:
    op.create_table(
        'asset_binding',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('workspace_id', sa.String(length=64), nullable=False),
        sa.Column('consumer_asset_id', sa.String(length=64), nullable=False),
        sa.Column('consumer_version_id', sa.String(length=64), nullable=True),
        sa.Column('provider_asset_id', sa.String(length=64), nullable=False),
        sa.Column('provider_kind', sa.String(length=24), nullable=False),
        sa.Column('resolve_mode', sa.String(length=16), nullable=False),
        sa.Column('provider_channel', sa.String(length=16), nullable=True),
        sa.Column('provider_version_id', sa.String(length=64), nullable=True),
        sa.Column('tenant_scope', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'consumer_asset_id',
            'provider_asset_id',
            'consumer_version_id',
            name='uq_binding_consumer_provider_version',
        ),
    )
    with op.batch_alter_table('asset_binding', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_asset_binding_workspace_id'), ['workspace_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_asset_binding_consumer_asset_id'), ['consumer_asset_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_asset_binding_consumer_version_id'), ['consumer_version_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_asset_binding_provider_asset_id'), ['provider_asset_id'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('asset_binding', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_asset_binding_provider_asset_id'))
        batch_op.drop_index(batch_op.f('ix_asset_binding_consumer_version_id'))
        batch_op.drop_index(batch_op.f('ix_asset_binding_consumer_asset_id'))
        batch_op.drop_index(batch_op.f('ix_asset_binding_workspace_id'))
    op.drop_table('asset_binding')
