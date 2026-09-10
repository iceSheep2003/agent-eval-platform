"""提案表

Revision ID: improvement_0001
Revises:
Create Date: 2026-09-10 19:00:00.000000+00:00

提案是只追加的证据链：状态可推进，已写下的证据与理由不改。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'improvement_0001'
down_revision = None
branch_labels = ('improvement',)
depends_on = None


def upgrade() -> None:
    op.create_table('improvement_proposal',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('workspace_id', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('target_asset_id', sa.String(length=64), nullable=False),
    sa.Column('base_version_id', sa.String(length=64), nullable=True),
    sa.Column('proposed_spec', sa.JSON(), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('applied_version_id', sa.String(length=64), nullable=True),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('reviewed_by', sa.String(length=64), nullable=True),
    sa.Column('review_note', sa.Text(), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('improvement_proposal', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_improvement_proposal_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_improvement_proposal_target_asset_id'), ['target_asset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_improvement_proposal_workspace_id'), ['workspace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('improvement_proposal', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_improvement_proposal_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_improvement_proposal_target_asset_id'))
        batch_op.drop_index(batch_op.f('ix_improvement_proposal_status'))

    op.drop_table('improvement_proposal')
