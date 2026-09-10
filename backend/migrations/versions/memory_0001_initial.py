"""记忆表

Revision ID: memory_0001
Revises:
Create Date: 2026-09-10 17:00:00.000000+00:00

记忆放平台侧而不是 Agent 里：沙箱无状态，放 Agent 的模块级变量上不是丢就是串。
分区键 (agent_version_id, tenant_id, thread_id, scope) 少一维都会读到别人的记忆。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'memory_0001'
down_revision = None
branch_labels = ('memory',)
depends_on = None


def upgrade() -> None:
    op.create_table('memory_entry',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('workspace_id', sa.String(length=64), nullable=False),
    sa.Column('agent_version_id', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=True),
    sa.Column('thread_id', sa.String(length=64), nullable=True),
    sa.Column('scope', sa.String(length=16), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=True),
    sa.Column('content', sa.String(length=8192), nullable=False),
    sa.Column('fact_key', sa.String(length=128), nullable=True),
    sa.Column('terms', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint(
        'agent_version_id', 'tenant_id', 'thread_id', 'scope', 'kind', 'seq',
        name='uq_memory_entry',
    )
    )
    with op.batch_alter_table('memory_entry', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_memory_entry_agent_version_id'), ['agent_version_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_memory_entry_fact_key'), ['fact_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_memory_entry_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_memory_entry_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_memory_entry_thread_id'), ['thread_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_memory_entry_workspace_id'), ['workspace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('memory_entry', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_memory_entry_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_memory_entry_thread_id'))
        batch_op.drop_index(batch_op.f('ix_memory_entry_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_memory_entry_kind'))
        batch_op.drop_index(batch_op.f('ix_memory_entry_fact_key'))
        batch_op.drop_index(batch_op.f('ix_memory_entry_agent_version_id'))

    op.drop_table('memory_entry')
