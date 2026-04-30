"""Add page_image_path to ocr_results

Revision ID: 107913cda0ac
Revises: 47d1df21e271
Create Date: 2026-04-29 11:28:52.958382

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '107913cda0ac'
down_revision: Union[str, Sequence[str], None] = '47d1df21e271'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
