"""Full schema sync including workflow_state

Revision ID: 58a282f6e92e
Revises: 8fe150a7b951
Create Date: 2026-04-29 12:04:00.843826

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '58a282f6e92e'
down_revision: Union[str, Sequence[str], None] = '8fe150a7b951'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # Create workflow_state table only if it does not already exist.
    if 'workflow_state' not in insp.get_table_names():
        op.create_table(
            'workflow_state',
            sa.Column('claim_id', sa.UUID(), nullable=False),
            sa.Column('current_step', sa.Text(), nullable=True),
            sa.Column('status', sa.Text(), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.PrimaryKeyConstraint('claim_id'),
            sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], ondelete='CASCADE'),
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('workflow_state')
