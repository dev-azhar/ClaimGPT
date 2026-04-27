"""merge heads

Revision ID: 6f583037f8d0
Revises: 037e9d57e356, 20260423_add_content_hash
Create Date: 2026-04-23 09:59:56.129494

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f583037f8d0'
down_revision: Union[str, Sequence[str], None] = ('037e9d57e356', '20260423_add_content_hash')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
