"""Widen canonical Person role keys for Unicode case-fold expansion.

Revision ID: 0054
Revises: 0053
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_person_role_terms_normalized_key",
        "person_role_terms",
        type_="check",
    )
    op.alter_column(
        "person_role_terms",
        "normalized_key",
        existing_type=sa.String(length=120),
        type_=sa.String(length=360),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_person_role_terms_normalized_key",
        "person_role_terms",
        "char_length(normalized_key) BETWEEN 1 AND 360",
    )
    op.drop_constraint(
        "ck_person_role_assignments_context_key",
        "person_role_assignments",
        type_="check",
    )
    op.alter_column(
        "person_role_assignments",
        "context_key",
        existing_type=sa.String(length=200),
        type_=sa.String(length=600),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_person_role_assignments_context_key",
        "person_role_assignments",
        "char_length(context_key) <= 600",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_person_role_assignments_context_key",
        "person_role_assignments",
        type_="check",
    )
    op.alter_column(
        "person_role_assignments",
        "context_key",
        existing_type=sa.String(length=600),
        type_=sa.String(length=200),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_person_role_assignments_context_key",
        "person_role_assignments",
        "char_length(context_key) <= 200",
    )
    op.drop_constraint(
        "ck_person_role_terms_normalized_key",
        "person_role_terms",
        type_="check",
    )
    op.alter_column(
        "person_role_terms",
        "normalized_key",
        existing_type=sa.String(length=360),
        type_=sa.String(length=120),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_person_role_terms_normalized_key",
        "person_role_terms",
        "char_length(normalized_key) BETWEEN 1 AND 120",
    )
