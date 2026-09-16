from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.schemas import ObjectOut
from app.services.errors import NotFoundError, ValidationError
from app.services.label_service import LabelService
from app.services.object_primary_date import object_primary_search_datetime
from app.services.retrieval_constants import MAX_CANDIDATE_POOL, MAX_FINAL_HITS, TIME_SCOPE_ALL
from app.services.retrieval_service import RetrievalService, load_objects_ordered

SEARCH_SORT_RELEVANCE = "relevance"
SEARCH_SORT_NEWEST = "newest"
SEARCH_SORT_OLDEST = "oldest"
SEARCH_SORT_MODES = frozenset(
    {SEARCH_SORT_RELEVANCE, SEARCH_SORT_NEWEST, SEARCH_SORT_OLDEST}
)


class SearchService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._retrieval = RetrievalService(session, user_id)

    def search(
        self,
        query: str,
        kind: str | None = None,
        provider: str | None = None,
        project_id: UUID | None = None,
        limit: int = 20,
        sort: str = SEARCH_SORT_RELEVANCE,
        label_id: UUID | None = None,
    ) -> list[ObjectOut]:
        ui_limit = max(1, min(limit, MAX_FINAL_HITS))
        if sort not in SEARCH_SORT_MODES:
            sort = SEARCH_SORT_RELEVANCE
        resolved_label_id = self._require_search_label(kind=kind, label_id=label_id)

        if sort == SEARCH_SORT_RELEVANCE:
            result = self._retrieval.retrieve(
                query=query,
                kind=kind,
                provider=provider,
                project_id=project_id,
                time_scope=TIME_SCOPE_ALL,
                limit=ui_limit,
                label_id=resolved_label_id,
            )
            objects = load_objects_ordered(self._session, self._user_id, result.hits)
            return [ObjectOut.from_model(obj) for obj in objects]

        result = self._retrieval.retrieve(
            query=query,
            kind=kind,
            provider=provider,
            project_id=project_id,
            time_scope=TIME_SCOPE_ALL,
            limit=MAX_CANDIDATE_POOL,
            hits_cap=MAX_CANDIDATE_POOL,
            label_id=resolved_label_id,
        )
        objects = load_objects_ordered(self._session, self._user_id, result.hits)
        dated: list[tuple[object, datetime]] = []
        undated: list[object] = []
        for obj in objects:
            primary = object_primary_search_datetime(obj)
            if primary is None:
                undated.append(obj)
            else:
                dated.append((obj, primary))
        if sort == SEARCH_SORT_NEWEST:
            dated.sort(key=lambda item: (item[1], str(item[0].id)), reverse=True)
        else:
            dated.sort(key=lambda item: (item[1], str(item[0].id)))
        undated.sort(key=lambda obj: str(obj.id))
        ordered = [item[0] for item in dated] + undated
        return [ObjectOut.from_model(obj) for obj in ordered[:ui_limit]]

    def _require_search_label(
        self, *, kind: str | None, label_id: UUID | None
    ) -> UUID | None:
        if label_id is None:
            return None
        if kind == "label":
            raise ValidationError("label objects cannot be labeled")
        try:
            LabelService(self._session, self._user_id).require_active_labels([label_id])
        except NotFoundError as exc:
            raise ValidationError("label is not active") from exc
        return label_id
