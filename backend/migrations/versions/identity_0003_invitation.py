"""add organization invitation

Revision ID: identity_0003
Revises: identity_0002
Create Date: 2026-09-10

按邮箱邀请加入组织。账号已存在时立即加入；否则留 pending，
对方首次登录时由 `IdentityService.accept_pending_invitations` 自动接受
（平台不开放自助注册，账号由自建 IdP 提供）。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'identity_0003'
down_revision = 'identity_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'identity_invitation',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('organization_id', sa.String(length=64), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('invited_by', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['identity_organization.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'email', name='uq_invitation_email'),
    )
    op.create_index(
        'ix_identity_invitation_organization_id', 'identity_invitation', ['organization_id']
    )
    op.create_index('ix_identity_invitation_email', 'identity_invitation', ['email'])


def downgrade() -> None:
    op.drop_index('ix_identity_invitation_email', 'identity_invitation')
    op.drop_index('ix_identity_invitation_organization_id', 'identity_invitation')
    op.drop_table('identity_invitation')
