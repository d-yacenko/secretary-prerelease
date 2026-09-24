"""Add explainable Person identity evidence.

Revision ID: 0049
Revises: 0048
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVIDENCE_TYPES = (
    "exact_identifier",
    "provider_profile",
    "name_similarity",
    "organization_match",
    "graph_context",
    "llm_suggestion",
    "user_route_choice",
    "user_confirmed",
    "user_rejected",
)


def upgrade() -> None:
    op.create_table(
        "person_identity_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_identity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("identity_type", sa.String(), nullable=False),
        sa.Column("realm", sa.String(), nullable=False, server_default=""),
        sa.Column("canonical_value", sa.String(), nullable=False),
        sa.Column("evidence_type", sa.String(), nullable=False),
        sa.Column("polarity", sa.String(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("provenance_kind", sa.String(), nullable=False),
        sa.Column("provenance_key", sa.String(), nullable=False),
        sa.Column("source_object_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("explanation", sa.String(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "evidence_type in (" + ", ".join(repr(item) for item in _EVIDENCE_TYPES) + ")",
            name="ck_person_identity_evidence_type",
        ),
        sa.CheckConstraint(
            "polarity in ('positive', 'negative')",
            name="ck_person_identity_evidence_polarity",
        ),
        sa.CheckConstraint(
            "state in ('active', 'retracted')",
            name="ck_person_identity_evidence_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["person_object_id"], ["objects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["person_identity_id"],
            ["person_identities.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["source_object_id"], ["objects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["person_identity_evidence.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_person_identity_evidence_user_person",
        "person_identity_evidence",
        ["user_id", "person_object_id"],
    )
    op.create_index(
        "uq_person_identity_evidence_active_source",
        "person_identity_evidence",
        [
            "user_id",
            "person_object_id",
            "provider",
            "identity_type",
            "realm",
            "canonical_value",
            "evidence_type",
            "polarity",
            "provenance_key",
        ],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_person_identity_evidence_active_source",
        table_name="person_identity_evidence",
    )
    op.drop_index(
        "ix_person_identity_evidence_user_person",
        table_name="person_identity_evidence",
    )
    op.drop_table("person_identity_evidence")
