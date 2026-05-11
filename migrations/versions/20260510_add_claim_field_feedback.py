"""add claim_field_feedback table

Revision ID: 20260510_field_feedback
Revises: 47d1df21e271
Create Date: 2026-05-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260510_field_feedback"
down_revision: Union[str, Sequence[str], None] = "47d1df21e271"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "claim_field_feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "claim_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("field_name", sa.Text(), nullable=False),
        # Frozen extracted/parsed value at first user edit. Never overwritten.
        sa.Column("original_value", sa.Text(), nullable=True),
        # Latest user-supplied correction.
        sa.Column("corrected_value", sa.Text(), nullable=True),
        # Caller identity (JWT sub / email). Nullable in dev mode.
        sa.Column("user_sub", sa.Text(), nullable=True),
        sa.Column("user_email", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_claim_field_feedback_claim_id",
        "claim_field_feedback",
        ["claim_id"],
    )
    # One feedback row per (claim, field) when claim-scoped (document_id NULL)
    op.execute(
        "CREATE UNIQUE INDEX ux_field_feedback_claim_field "
        "ON claim_field_feedback (claim_id, field_name) "
        "WHERE document_id IS NULL"
    )
    # One feedback row per (claim, document, field) when document-scoped
    op.execute(
        "CREATE UNIQUE INDEX ux_field_feedback_claim_doc_field "
        "ON claim_field_feedback (claim_id, document_id, field_name) "
        "WHERE document_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_field_feedback_claim_doc_field")
    op.execute("DROP INDEX IF EXISTS ux_field_feedback_claim_field")
    op.drop_index("ix_claim_field_feedback_claim_id", table_name="claim_field_feedback")
    op.drop_table("claim_field_feedback")
