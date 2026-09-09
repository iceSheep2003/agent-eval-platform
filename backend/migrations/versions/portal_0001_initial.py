"""initial

Revision ID: portal_0001
Revises:
Create Date: 2026-09-10 10:30:00.000000+00:00

约定：一个迁移文件只能操作自己模块前缀的表（由 branch_labels 标识）。

展示平台的独立账号体系与项目模型。**不与任何其他模块建 FK**——
`asset_id` / `workspace_id` 都是不透明引用，迁移分支之间不互相牵制。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'portal_0001'
down_revision = None
branch_labels = ('portal',)
depends_on = None


def upgrade() -> None:
    op.create_table('portal_user',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('display_name', sa.String(length=128), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username', name='uq_portal_username')
    )

    op.create_table('portal_session',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('portal_user_id', sa.String(length=64), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    with op.batch_alter_table('portal_session', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_portal_session_portal_user_id'), ['portal_user_id'], unique=False)

    op.create_table('portal_project',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('workspace_id', sa.String(length=64), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.String(length=512), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'slug', name='uq_portal_project_slug')
    )
    with op.batch_alter_table('portal_project', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_portal_project_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('portal_member',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('portal_user_id', sa.String(length=64), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'portal_user_id', name='uq_portal_member')
    )
    with op.batch_alter_table('portal_member', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_portal_member_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_portal_member_portal_user_id'), ['portal_user_id'], unique=False)

    op.create_table('portal_project_agent',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=64), nullable=False),
    sa.Column('asset_id', sa.String(length=64), nullable=False),
    sa.Column('display_name', sa.String(length=128), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'asset_id', name='uq_portal_project_asset')
    )
    with op.batch_alter_table('portal_project_agent', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_portal_project_agent_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_portal_project_agent_asset_id'), ['asset_id'], unique=False)

    op.create_table('portal_agent_channel',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('project_agent_id', sa.String(length=64), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('deployment_credential_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_agent_id', 'channel', name='uq_portal_agent_channel')
    )
    with op.batch_alter_table('portal_agent_channel', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_portal_agent_channel_project_agent_id'), ['project_agent_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('portal_agent_channel', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_portal_agent_channel_project_agent_id'))

    op.drop_table('portal_agent_channel')
    with op.batch_alter_table('portal_project_agent', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_portal_project_agent_asset_id'))
        batch_op.drop_index(batch_op.f('ix_portal_project_agent_project_id'))

    op.drop_table('portal_project_agent')
    with op.batch_alter_table('portal_member', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_portal_member_portal_user_id'))
        batch_op.drop_index(batch_op.f('ix_portal_member_project_id'))

    op.drop_table('portal_member')
    with op.batch_alter_table('portal_project', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_portal_project_workspace_id'))

    op.drop_table('portal_project')
    with op.batch_alter_table('portal_session', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_portal_session_portal_user_id'))

    op.drop_table('portal_session')
    op.drop_table('portal_user')
