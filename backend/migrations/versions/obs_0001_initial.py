"""initial

Revision ID: obs_0001
Revises:
Create Date: 2026-09-10 10:00:00.000000+00:00

约定：一个迁移文件只能操作自己模块前缀的表（由 branch_labels 标识）。

补历史欠账：`obs_trace` / `obs_span` 此前只在开发环境由 `create_all()` 建表，
生产升级路径（`python -m backend.runtime.migrate`）建不出它们，写 Trace 会失败。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'obs_0001'
down_revision = None
branch_labels = ('obs',)
depends_on = None


def upgrade() -> None:
    op.create_table('obs_trace',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('workspace_id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=True),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('asset_id', sa.String(length=64), nullable=False),
    sa.Column('asset_version_id', sa.String(length=64), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=True),
    sa.Column('run_id', sa.String(length=64), nullable=True),
    sa.Column('trial_id', sa.String(length=64), nullable=True),
    sa.Column('external_trace_id', sa.String(length=128), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('input', sa.JSON(), nullable=True),
    sa.Column('output', sa.JSON(), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=18, scale=8), nullable=False),
    sa.Column('span_count', sa.Integer(), nullable=False),
    sa.Column('ingested_via', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('asset_id', 'external_trace_id', name='uq_trace_external')
    )
    with op.batch_alter_table('obs_trace', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_obs_trace_asset_id'), ['asset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_obs_trace_run_id'), ['run_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_obs_trace_started_at'), ['started_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_obs_trace_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_obs_trace_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_obs_trace_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('obs_span',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('external_span_id', sa.String(length=128), nullable=False),
    sa.Column('trace_id', sa.String(length=64), nullable=False),
    sa.Column('workspace_id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=True),
    sa.Column('parent_span_id', sa.String(length=128), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('input', sa.JSON(), nullable=True),
    sa.Column('output', sa.JSON(), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=18, scale=8), nullable=False),
    sa.Column('attributes', sa.JSON(), nullable=False),
    sa.Column('error_type', sa.String(length=128), nullable=True),
    sa.Column('error_message', sa.String(length=1024), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['trace_id'], ['obs_trace.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('trace_id', 'external_span_id', name='uq_span_external')
    )
    with op.batch_alter_table('obs_span', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_obs_span_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_obs_span_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_obs_span_trace_id'), ['trace_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_obs_span_workspace_id'), ['workspace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('obs_span', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_obs_span_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_obs_span_trace_id'))
        batch_op.drop_index(batch_op.f('ix_obs_span_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_obs_span_kind'))

    op.drop_table('obs_span')
    with op.batch_alter_table('obs_trace', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_obs_trace_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_obs_trace_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_obs_trace_status'))
        batch_op.drop_index(batch_op.f('ix_obs_trace_started_at'))
        batch_op.drop_index(batch_op.f('ix_obs_trace_run_id'))
        batch_op.drop_index(batch_op.f('ix_obs_trace_asset_id'))

    op.drop_table('obs_trace')
