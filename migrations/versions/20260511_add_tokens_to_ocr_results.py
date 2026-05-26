"""Add tokens JSONB to ocr_results

Revision ID: 20260511_add_tokens_to_ocr_results
Revises: 20260504_fix_workflow_state_schema
Create Date: 2026-05-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260511_add_tokens_to_ocr_results'
down_revision: Union[str, Sequence[str], None] = '20260504_fix_workflow_state_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'ocr_results' not in insp.get_table_names():
        # If the table doesn't exist yet, nothing to do here.
        return

    cols = [c['name'] for c in insp.get_columns('ocr_results')]
    if 'tokens' in cols:
        return

    op.add_column(
        'ocr_results',
        sa.Column('tokens', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'ocr_results' not in insp.get_table_names():
        return
    cols = [c['name'] for c in insp.get_columns('ocr_results')]
    if 'tokens' not in cols:
        return
    op.drop_column('ocr_results', 'tokens')
