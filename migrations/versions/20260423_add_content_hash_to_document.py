"""
add content_hash to Document

Revision ID: 20260423_add_content_hash
Revises: 31ee0b3eb6f2
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260423_add_content_hash'
down_revision = '31ee0b3eb6f2'
branch_labels = None
depends_on = None

"""
Alembic migration for adding content_hash to Document model.
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('documents', sa.Column('content_hash', sa.Text(), nullable=False, server_default=''))
    op.create_index('ix_documents_content_hash', 'documents', ['content_hash'])
    op.alter_column('documents', 'content_hash', server_default=None)

def downgrade():
    op.drop_index('ix_documents_content_hash', table_name='documents')
    op.drop_column('documents', 'content_hash')
