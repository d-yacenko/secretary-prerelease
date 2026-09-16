from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.llm.embedding_service import EmbeddingService

JobHandler = Callable[[Session, EmbeddingService | None, dict[str, Any], UUID], None]
