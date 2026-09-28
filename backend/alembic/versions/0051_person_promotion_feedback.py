"""Store reversible suppression of an unresolved Person promotion identity.

Revision ID: 0051
Revises: 0050
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "person_promotion_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("identity_type", sa.String(), nullable=False),
        sa.Column("realm", sa.String(), nullable=False, server_default=""),
        sa.Column("canonical_value", sa.String(), nullable=False),
        sa.Column("display_value", sa.String(), nullable=True),
        sa.Column("feedback_kind", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("provenance_key", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "feedback_kind = 'suppression'",
            name="ck_person_promotion_feedback_kind",
        ),
        sa.CheckConstraint(
            "state in ('active', 'retracted')",
            name="ck_person_promotion_feedback_state",
        ),
        sa.CheckConstraint(
            "origin = 'user'",
            name="ck_person_promotion_feedback_origin",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_person_promotion_feedback_user",
        "person_promotion_feedback",
        ["user_id", "state"],
    )
    op.create_index(
        "uq_person_promotion_feedback_active_identity",
        "person_promotion_feedback",
        ["user_id", "provider", "identity_type", "realm", "canonical_value"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_person_promotion_feedback_active_identity",
        table_name="person_promotion_feedback",
    )
    op.drop_index("ix_person_promotion_feedback_user", table_name="person_promotion_feedback")
    op.drop_table("person_promotion_feedback")
