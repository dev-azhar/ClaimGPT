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
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
