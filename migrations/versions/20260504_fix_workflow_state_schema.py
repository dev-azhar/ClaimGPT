"""Fix workflow_state schema and clean legacy duplicates

Revision ID: 20260504_fix_workflow_state_schema
Revises: 58a282f6e92e
Create Date: 2026-05-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260504_fix_workflow_state_schema'
down_revision: Union[str, Sequence[str], None] = '58a282f6e92e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    if 'workflow_state' not in insp.get_table_names():
        op.create_table(
            'workflow_state',
            sa.Column('claim_id', sa.UUID(), nullable=False),
            sa.Column('current_step', sa.Text(), nullable=True),
            sa.Column('status', sa.Text(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.PrimaryKeyConstraint('claim_id'),
            sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], ondelete='CASCADE'),
        )
        return

    op.execute(
        sa.text(
            """
            DELETE FROM workflow_state a
            USING workflow_state b
            WHERE a.claim_id = b.claim_id
              AND a.ctid < b.ctid
            """
        )
    )

    pk = insp.get_pk_constraint('workflow_state') or {}
    if not pk.get('constrained_columns'):
        op.create_primary_key('workflow_state_pkey', 'workflow_state', ['claim_id'])

    cols = {col['name']: col for col in insp.get_columns('workflow_state')}
    if 'status' in cols and cols['status'].get('nullable', True):
        op.alter_column('workflow_state', 'status', existing_type=sa.Text(), nullable=False)


def downgrade() -> None:
    op.drop_table('workflow_state')