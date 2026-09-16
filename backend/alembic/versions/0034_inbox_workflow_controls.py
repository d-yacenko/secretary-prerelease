"""inbox review markers and object bookmarks

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "inbox_review_markers",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("anchor_feed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("anchor_object_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "object_bookmarks",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "color IN ('red', 'orange', 'yellow', 'green', 'blue', 'violet', 'gray')",
            name="ck_object_bookmarks_color",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["object_id"], ["objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "object_id", name="pk_object_bookmarks"),
        sa.UniqueConstraint("user_id", "object_id", name="uq_object_bookmarks_user_id_object_id"),
    )
    op.create_index("ix_object_bookmarks_user_id", "object_bookmarks", ["user_id"])
    op.create_index("ix_object_bookmarks_object_id", "object_bookmarks", ["object_id"])


def downgrade() -> None:
    op.drop_index("ix_object_bookmarks_object_id", table_name="object_bookmarks")
    op.drop_index("ix_object_bookmarks_user_id", table_name="object_bookmarks")
    op.drop_table("object_bookmarks")
    op.drop_table("inbox_review_markers")
