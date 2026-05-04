"""Add set_hash to ParseJob

Revision ID: 47d1df21e271
Revises: 6f583037f8d0
Create Date: 2026-04-23 12:10:53.065423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '47d1df21e271'
down_revision: Union[str, Sequence[str], None] = '6f583037f8d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [col['name'] for col in insp.get_columns('parse_jobs')]
    indexes = [idx['name'] for idx in insp.get_indexes('parse_jobs')]
    if 'set_hash' not in columns:
        op.add_column('parse_jobs', sa.Column('set_hash', sa.Text(), nullable=True))
    if op.f('ix_parse_jobs_set_hash') not in indexes:
        op.create_index(op.f('ix_parse_jobs_set_hash'), 'parse_jobs', ['set_hash'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_parse_jobs_set_hash'), table_name='parse_jobs')
    op.drop_column('parse_jobs', 'set_hash')
