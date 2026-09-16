"""graph schema: objects and edges

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("canonical_uri", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("embedding", Vector(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_objects_kind", "objects", ["kind"], unique=False)
    op.create_index("ix_objects_status", "objects", ["status"], unique=False)
    op.create_index("ix_objects_due_at", "objects", ["due_at"], unique=False)
    op.create_index(
        "uq_objects_provider_kind_external_id",
        "objects",
        ["provider", "kind", "external_id"],
        unique=True,
        postgresql_where=sa.text("provider IS NOT NULL AND external_id IS NOT NULL"),
    )

    op.create_table(
        "edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["source_id"], ["objects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_id"], ["objects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_edges_source_id", "edges", ["source_id"], unique=False)
    op.create_index("ix_edges_target_id", "edges", ["target_id"], unique=False)
    op.create_index("ix_edges_type", "edges", ["type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_edges_type", table_name="edges")
    op.drop_index("ix_edges_target_id", table_name="edges")
    op.drop_index("ix_edges_source_id", table_name="edges")
    op.drop_table("edges")
    op.drop_index(
        "uq_objects_provider_kind_external_id",
        table_name="objects",
        postgresql_where=sa.text("provider IS NOT NULL AND external_id IS NOT NULL"),
    )
    op.drop_index("ix_objects_due_at", table_name="objects")
    op.drop_index("ix_objects_status", table_name="objects")
    op.drop_index("ix_objects_kind", table_name="objects")
    op.drop_table("objects")
