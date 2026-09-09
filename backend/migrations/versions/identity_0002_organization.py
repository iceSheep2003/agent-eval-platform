"""add organization layer

Revision ID: identity_0002
Revises: identity_0001
Create Date: 2026-09-10

对齐 Langfuse 的 Organization → Project(工作区) → Membership 三层。

数据迁移：已有工作区没有组织归属，这里建一个默认组织把它们挂上去，
并把现有的工作区成员补成组织成员（owner 保持 owner，其余为 member），
否则升级后老用户会看不到任何组织。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'identity_0002'
down_revision = 'identity_0001'
branch_labels = None
depends_on = None

DEFAULT_ORG_ID = 'org_default'
DEFAULT_ORG_SLUG = 'default'


def upgrade() -> None:
    op.create_table(
        'identity_organization',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_table(
        'identity_organization_membership',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('organization_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['identity_organization.id']),
        sa.ForeignKeyConstraint(['user_id'], ['identity_user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'user_id', name='uq_org_membership'),
    )
    op.create_index(
        'ix_identity_organization_membership_organization_id',
        'identity_organization_membership',
        ['organization_id'],
    )
    op.create_index(
        'ix_identity_organization_membership_user_id',
        'identity_organization_membership',
        ['user_id'],
    )

    # 默认组织：把存量工作区挂上去
    op.execute(
        f"INSERT INTO identity_organization (id, slug, name, created_at, updated_at) "
        f"VALUES ('{DEFAULT_ORG_ID}', '{DEFAULT_ORG_SLUG}', 'Default', "
        f"CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    with op.batch_alter_table('identity_workspace', schema=None) as batch_op:
        batch_op.add_column(sa.Column('organization_id', sa.String(length=64), nullable=True))
    op.execute(
        f"UPDATE identity_workspace SET organization_id = '{DEFAULT_ORG_ID}' "
        f"WHERE organization_id IS NULL"
    )
    with op.batch_alter_table('identity_workspace', schema=None) as batch_op:
        batch_op.alter_column('organization_id', existing_type=sa.String(length=64), nullable=False)
        batch_op.create_foreign_key(
            'fk_workspace_organization', 'identity_organization', ['organization_id'], ['id']
        )
        batch_op.create_index(
            'ix_identity_workspace_organization_id', ['organization_id']
        )

    # 存量工作区成员补成组织成员
    op.execute(
        "INSERT INTO identity_organization_membership "
        "(id, organization_id, user_id, role, created_at, updated_at) "
        "SELECT "
        f"'{DEFAULT_ORG_ID}:' || m.user_id, '{DEFAULT_ORG_ID}', m.user_id, "
        "CASE WHEN m.role = 'owner' THEN 'owner' ELSE 'member' END, "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
        "FROM identity_membership m "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM identity_organization_membership o "
        f" WHERE o.organization_id = '{DEFAULT_ORG_ID}' AND o.user_id = m.user_id"
        ")"
    )


def downgrade() -> None:
    op.execute("DELETE FROM identity_organization_membership")
    with op.batch_alter_table('identity_workspace', schema=None) as batch_op:
        batch_op.drop_index('ix_identity_workspace_organization_id')
        batch_op.drop_constraint('fk_workspace_organization', type_='foreignkey')
        batch_op.drop_column('organization_id')
    op.drop_index('ix_identity_organization_membership_user_id', 'identity_organization_membership')
    op.drop_index('ix_identity_organization_membership_organization_id', 'identity_organization_membership')
    op.drop_table('identity_organization_membership')
    op.drop_table('identity_organization')
