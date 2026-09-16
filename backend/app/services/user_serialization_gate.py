"""Per-user serialization sentinel for semantic/taxonomy writers.

PostgreSQL ``FOR NO KEY UPDATE`` on ``users`` (SQLAlchemy
``with_for_update(key_share=True)``) so competing writers serialize while
AI-audit FK inserts can still take ``KEY SHARE``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User


def lock_user_serialization_row(session: Session, user_id: UUID) -> User | None:
    return session.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
