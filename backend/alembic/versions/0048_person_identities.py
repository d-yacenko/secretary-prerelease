"""Add canonical Person provider identities.

Revision ID: 0048
Revises: 0047
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "person_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identity_type", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("realm", sa.String(), nullable=False, server_default=""),
        sa.Column("canonical_value", sa.String(), nullable=False),
        sa.Column("display_value", sa.String(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["person_object_id"], ["objects.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_person_identities_user_person",
        "person_identities",
        ["user_id", "person_object_id"],
    )
    op.create_index(
        "uq_person_identities_active_exact",
        "person_identities",
        ["user_id", "provider", "identity_type", "realm", "canonical_value"],
        unique=True,
        postgresql_where=sa.text("state <> 'rejected'"),
    )


def downgrade() -> None:
    op.drop_index("uq_person_identities_active_exact", table_name="person_identities")
    op.drop_index("ix_person_identities_user_person", table_name="person_identities")
    op.drop_table("person_identities")
