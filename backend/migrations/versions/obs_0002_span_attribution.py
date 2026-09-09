"""add span resource attribution

Revision ID: obs_0002
Revises: obs_0001
Create Date: 2026-09-10

约定：一个迁移文件只能操作自己模块前缀的表（由 branch_labels 标识）。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'obs_0002'
down_revision = 'obs_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('obs_span', schema=None) as batch_op:
        batch_op.add_column(sa.Column('resource_asset_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('resource_version_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('resource_attribution', sa.String(length=16), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_obs_span_resource_asset_id'), ['resource_asset_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_obs_span_resource_version_id'), ['resource_version_id'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('obs_span', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_obs_span_resource_version_id'))
        batch_op.drop_index(batch_op.f('ix_obs_span_resource_asset_id'))
        batch_op.drop_column('resource_attribution')
        batch_op.drop_column('resource_version_id')
        batch_op.drop_column('resource_asset_id')
