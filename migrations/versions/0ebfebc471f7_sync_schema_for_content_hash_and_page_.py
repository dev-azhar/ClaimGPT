"""Sync schema for content_hash and page_image_path

Revision ID: 0ebfebc471f7
Revises: 107913cda0ac
Create Date: 2026-04-29 11:56:29.539701

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0ebfebc471f7'
down_revision: Union[str, Sequence[str], None] = '107913cda0ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
