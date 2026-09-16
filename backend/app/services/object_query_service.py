"""Deterministic structured object queries (no embeddings / LLM)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, nulls_last, or_, select
from sqlalchemy.orm import Session

from app.db.models import Edge, Object
from app.domain.labels import (
    EDGE_TYPE_LABELED_WITH,
    KIND_LABEL,
    LABEL_MATCH_ALL,
    LABEL_MATCH_ANY,
    QUERY_LABEL_IDS_MAX,
)
from app.domain.object_visibility import object_is_active
from app.domain.task_lifecycle import (
    LEGACY_TASK_STATUS_COMPLETED,
    TASK_STATUS_DONE,
    TASK_STATUS_OPEN,
)
from app.services.errors import ValidationError
from app.services.provenance import REJECTED_STATE
from app.tools.datetime_utils import normalize_tool_datetime

MAX_QUERY_OBJECTS_LIMIT = 50
DEFAULT_QUERY_OBJECTS_LIMIT = 20

ALLOWED_SORT_FIELDS = frozenset(
    {"due_at", "start_at", "occurred_at", "created_at", "updated_at", "title"}
)


def _task_status_filter(statuses: list[str]) -> object | None:
    parts: list[object] = []
    exact: list[str] = []
    for status in statuses:
        if status == TASK_STATUS_OPEN:
            parts.append(
                or_(Object.status == TASK_STATUS_OPEN, Object.status.is_(None))
            )
        elif status == TASK_STATUS_DONE:
            parts.append(
                or_(
                    Object.status == TASK_STATUS_DONE,
                    Object.status == LEGACY_TASK_STATUS_COMPLETED,
                )
            )
        else:
            exact.append(status)
    if exact:
        parts.append(Object.status.in_(exact))
    if not parts:
        return None
    return or_(*parts)


class ObjectQueryService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def query(
        self,
        *,
        kinds: list[str] | None = None,
        providers: list[str] | None = None,
        statuses: list[str] | None = None,
        states: list[str] | None = None,
        due_from: datetime | None = None,
        due_to: datetime | None = None,
        start_from: datetime | None = None,
        start_to: datetime | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        label_ids: list[UUID] | None = None,
        label_match: str = LABEL_MATCH_ALL,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        limit: int = DEFAULT_QUERY_OBJECTS_LIMIT,
    ) -> list[Object]:
        if sort_by not in ALLOWED_SORT_FIELDS:
            raise ValidationError(f"invalid sort_by: {sort_by}")
        if sort_order not in {"asc", "desc"}:
            raise ValidationError("sort_order must be asc or desc")

        row_limit = max(1, min(limit, MAX_QUERY_OBJECTS_LIMIT))

        stmt = select(Object).where(
            Object.user_id == self._user_id,
            Object.state != REJECTED_STATE,
            object_is_active(),
        )

        if kinds:
            stmt = stmt.where(Object.kind.in_(kinds))
        else:
            stmt = stmt.where(Object.kind != KIND_LABEL)
        if providers:
            stmt = stmt.where(Object.provider.in_(providers))
        if statuses:
            status_clause = _task_status_filter(statuses)
            if status_clause is not None:
                stmt = stmt.where(status_clause)
        if states:
            stmt = stmt.where(Object.state.in_(states))

        if due_from is not None:
            stmt = stmt.where(Object.due_at >= normalize_tool_datetime(due_from))
        if due_to is not None:
            stmt = stmt.where(Object.due_at <= normalize_tool_datetime(due_to))
        if start_from is not None:
            stmt = stmt.where(Object.start_at >= normalize_tool_datetime(start_from))
        if start_to is not None:
            stmt = stmt.where(Object.start_at <= normalize_tool_datetime(start_to))
        if occurred_from is not None:
            stmt = stmt.where(
                Object.occurred_at >= normalize_tool_datetime(occurred_from)
            )
        if occurred_to is not None:
            stmt = stmt.where(
                Object.occurred_at <= normalize_tool_datetime(occurred_to)
            )

        requested_label_ids = list(label_ids or [])
        if len(requested_label_ids) > QUERY_LABEL_IDS_MAX:
            raise ValidationError(f"label_ids must contain at most {QUERY_LABEL_IDS_MAX} ids")
        if requested_label_ids:
            if label_match not in {LABEL_MATCH_ALL, LABEL_MATCH_ANY}:
                raise ValidationError("label_match must be all or any")
            from app.services.errors import NotFoundError
            from app.services.label_service import LabelService

            try:
                LabelService(self._session, self._user_id).require_active_labels(requested_label_ids)
            except NotFoundError as exc:
                raise ValidationError("label is not active") from exc
            unique_ids: list[UUID] = []
            seen: set[UUID] = set()
            for label_id in requested_label_ids:
                if label_id in seen:
                    continue
                seen.add(label_id)
                unique_ids.append(label_id)
            clauses = [
                exists(
                    select(Edge.id).where(
                        Edge.user_id == self._user_id,
                        Edge.source_id == Object.id,
                        Edge.target_id == label_id,
                        Edge.type == EDGE_TYPE_LABELED_WITH,
                        Edge.state != REJECTED_STATE,
                    )
                )
                for label_id in unique_ids
            ]
            combined = clauses[0]
            for clause in clauses[1:]:
                combined = combined | clause if label_match == LABEL_MATCH_ANY else combined & clause
            stmt = stmt.where(combined)

        sort_column = {
            "due_at": Object.due_at,
            "start_at": Object.start_at,
            "occurred_at": Object.occurred_at,
            "created_at": Object.created_at,
            "updated_at": Object.updated_at,
            "title": Object.title,
        }[sort_by]

        if sort_order == "asc":
            primary = nulls_last(sort_column.asc())
        else:
            primary = nulls_last(sort_column.desc())

        stmt = stmt.order_by(primary, Object.created_at.asc(), Object.id.asc())
        stmt = stmt.limit(row_limit)

        return list(self._session.scalars(stmt).all())
