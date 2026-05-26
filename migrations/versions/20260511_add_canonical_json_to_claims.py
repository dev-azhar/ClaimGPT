"""Add canonical_json to claims

Revision ID: 20260511_add_canonical_json_to_claims
Revises: 20260511_add_tokens_to_ocr_results
Create Date: 2026-05-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260511_add_canonical_json_to_claims'
down_revision: Union[str, Sequence[str], None] = '20260511_add_tokens_to_ocr_results'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'claims' not in insp.get_table_names():
        return

    cols = [c['name'] for c in insp.get_columns('claims')]
    if 'canonical_json' in cols:
        return

    op.add_column('claims', sa.Column('canonical_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'claims' not in insp.get_table_names():
        return

    cols = [c['name'] for c in insp.get_columns('claims')]
    if 'canonical_json' not in cols:
        return

    op.drop_column('claims', 'canonical_json')