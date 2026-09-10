"""obs_trace 加 metadata

Revision ID: obs_0003
Revises: obs_0002
Create Date: 2026-09-10 18:30:00.000000+00:00

存这条 Trace 的补充事实——用了哪把密钥的**指纹**、记忆片的分区。
只存指纹不存值：「用的哪一把」可追溯，「钥匙是什么」不外扩。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'obs_0003'
down_revision = 'obs_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'obs_trace',
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('obs_trace', 'metadata')
