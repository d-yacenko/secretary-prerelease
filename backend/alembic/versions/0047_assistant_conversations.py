"""Add persistent Assistant conversations and messages.

Revision ID: 0047
Revises: 0046
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_assistant_conversations_user_id",
        "assistant_conversations",
        ["user_id"],
    )
    op.create_index(
        "ix_assistant_conversations_user_last_message",
        "assistant_conversations",
        ["user_id", "last_message_at"],
    )
    op.create_index(
        "uq_assistant_conversations_one_current",
        "assistant_conversations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "assistant_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("client_turn_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("presentation", postgresql.JSONB(), nullable=True),
        sa.Column(
            "pending_action_plan_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("resume_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["assistant_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["pending_action_plan_id"],
            ["pending_action_plans.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resume_plan_id"],
            ["pending_action_plans.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_assistant_messages_role",
        ),
    )
    op.create_index(
        "ix_assistant_messages_conversation_id",
        "assistant_messages",
        ["conversation_id"],
    )
    op.create_index(
        "ix_assistant_messages_conversation_created",
        "assistant_messages",
        ["conversation_id", "created_at", "id"],
    )
    op.create_index(
        "uq_assistant_messages_user_turn",
        "assistant_messages",
        ["conversation_id", "client_turn_id"],
        unique=True,
        postgresql_where=sa.text("role = 'user' AND client_turn_id IS NOT NULL"),
    )
    op.create_index(
        "uq_assistant_messages_resume_plan",
        "assistant_messages",
        ["resume_plan_id"],
        unique=True,
        postgresql_where=sa.text("resume_plan_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_assistant_messages_resume_plan", table_name="assistant_messages")
    op.drop_index("uq_assistant_messages_user_turn", table_name="assistant_messages")
    op.drop_index(
        "ix_assistant_messages_conversation_created",
        table_name="assistant_messages",
    )
    op.drop_index("ix_assistant_messages_conversation_id", table_name="assistant_messages")
    op.drop_table("assistant_messages")
    op.drop_index(
        "uq_assistant_conversations_one_current",
        table_name="assistant_conversations",
    )
    op.drop_index(
        "ix_assistant_conversations_user_last_message",
        table_name="assistant_conversations",
    )
    op.drop_index("ix_assistant_conversations_user_id", table_name="assistant_conversations")
    op.drop_table("assistant_conversations")
