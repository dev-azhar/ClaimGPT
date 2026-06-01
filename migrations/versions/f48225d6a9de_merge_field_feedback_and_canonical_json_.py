"""merge field feedback and canonical json heads

Revision ID: f48225d6a9de
Revises: 20260510_field_feedback, 20260511_add_canonical_json_to_claims
Create Date: 2026-05-26 10:31:05.133781

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f48225d6a9de'
down_revision: Union[str, Sequence[str], None] = ('20260510_field_feedback', '20260511_add_canonical_json_to_claims')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
