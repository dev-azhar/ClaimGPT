"""Add set_hash to parse_jobs

Revision ID: 8fe150a7b951
Revises: 0ebfebc471f7
Create Date: 2026-04-29 12:02:12.671780

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8fe150a7b951'
down_revision: Union[str, Sequence[str], None] = '0ebfebc471f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
