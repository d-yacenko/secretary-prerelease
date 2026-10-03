"""Add emergent per-user Person role terms and assignments.

Revision ID: 0053
Revises: 0052
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "person_role_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_text", sa.String(length=120), nullable=False),
        sa.Column("normalized_key", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(display_text) BETWEEN 1 AND 120",
            name="ck_person_role_terms_display_text",
        ),
        sa.CheckConstraint(
            "char_length(normalized_key) BETWEEN 1 AND 120",
            name="ck_person_role_terms_normalized_key",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("user_id", "normalized_key", name="uq_person_role_terms_user_key"),
    )
    op.create_index("ix_person_role_terms_user_id", "person_role_terms", ["user_id"])
    op.create_table(
        "person_role_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_term_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_text", sa.String(length=200), nullable=True),
        sa.Column("context_key", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("provenance_kind", sa.String(length=64), nullable=False),
        sa.Column("provenance_key", sa.String(length=128), nullable=False),
        sa.Column("source_object_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('active', 'retracted')",
            name="ck_person_role_assignments_state",
        ),
        sa.CheckConstraint(
            "char_length(origin) BETWEEN 1 AND 32",
            name="ck_person_role_assignments_origin",
        ),
        sa.CheckConstraint(
            "char_length(provenance_kind) BETWEEN 1 AND 64 "
            "AND char_length(provenance_key) BETWEEN 1 AND 128",
            name="ck_person_role_assignments_provenance",
        ),
        sa.CheckConstraint(
            "context_text IS NULL OR char_length(context_text) BETWEEN 1 AND 200",
            name="ck_person_role_assignments_context_text",
        ),
        sa.CheckConstraint(
            "char_length(context_key) <= 200",
            name="ck_person_role_assignments_context_key",
        ),
        sa.CheckConstraint(
            "(context_text IS NULL AND context_key = '') "
            "OR (context_text IS NOT NULL AND context_key <> '')",
            name="ck_person_role_assignments_context_pair",
        ),
        sa.CheckConstraint(
            "(state = 'retracted' AND retracted_at IS NOT NULL) "
            "OR (state = 'active' AND retracted_at IS NULL)",
            name="ck_person_role_assignments_retracted_at",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["person_object_id"], ["objects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_term_id"], ["person_role_terms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_object_id"], ["objects.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "uq_person_role_assignments_active",
        "person_role_assignments",
        ["user_id", "person_object_id", "role_term_id", "context_key"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_index(
        "ix_person_role_assignments_person",
        "person_role_assignments",
        ["user_id", "person_object_id", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_person_role_assignments_person", table_name="person_role_assignments")
    op.drop_index("uq_person_role_assignments_active", table_name="person_role_assignments")
    op.drop_table("person_role_assignments")
    op.drop_index("ix_person_role_terms_user_id", table_name="person_role_terms")
    op.drop_table("person_role_terms")
