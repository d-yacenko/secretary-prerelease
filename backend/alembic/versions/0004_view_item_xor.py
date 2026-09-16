"""view_items XOR constraint

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-28

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_view_items_object_or_visual", "view_items", type_="check")
    op.create_check_constraint(
        "ck_view_items_object_xor_visual",
        "view_items",
        "(object_id IS NOT NULL AND visual_id IS NULL) "
        "OR (object_id IS NULL AND visual_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_view_items_object_xor_visual", "view_items", type_="check")
    op.create_check_constraint(
        "ck_view_items_object_or_visual",
        "view_items",
        "object_id IS NOT NULL OR visual_id IS NOT NULL",
    )
