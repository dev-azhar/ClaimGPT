"""add content_hash to Document

Revision ID: 20260423_add_content_hash
Revises: 31ee0b3eb6f2
Create Date: 2026-04-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260423_add_content_hash'
down_revision: Union[str, Sequence[str], None] = '31ee0b3eb6f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'documents' not in insp.get_table_names():
        return
    cols = [c['name'] for c in insp.get_columns('documents')]
    if 'content_hash' not in cols:
        op.add_column('documents', sa.Column('content_hash', sa.Text(), nullable=False, server_default=''))
        # create index if not present
        existing_idx = [i['name'] for i in insp.get_indexes('documents')]
        if 'ix_documents_content_hash' not in existing_idx:
            op.create_index('ix_documents_content_hash', 'documents', ['content_hash'])
        # remove the server default after populate
        op.alter_column('documents', 'content_hash', server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'documents' not in insp.get_table_names():
        return
    cols = [c['name'] for c in insp.get_columns('documents')]
    if 'content_hash' in cols:
        # drop index if exists
        existing_idx = [i['name'] for i in insp.get_indexes('documents')]
        if 'ix_documents_content_hash' in existing_idx:
            op.drop_index('ix_documents_content_hash', table_name='documents')
        op.drop_column('documents', 'content_hash')
