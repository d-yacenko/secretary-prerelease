import logging
import math
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ContextBuildResult, ContextItem
from app.content_extraction.content_gating import filter_current_representations
from app.db.models import Edge, Object, Representation
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.llm.embedding_service import EmbeddingService
from app.services.capture_service import PINNED_ADDED_BY, PINNED_CONTEXT_ROLE
from app.services.correlation_constants import (
    EDGE_TYPE_CONTAINS,
    FOLDER_KIND,
    SEMANTIC_SUMMARY_METADATA_KEY,
)
from app.services.evidence_snippet import (
    CONTEXT_EVIDENCE_MAX_CHARS,
    build_query_centered_snippet,
    lexical_match_score,
)
from app.services.graph_service import GraphService
from app.services.representation_service import (
    KIND_CHUNK,
    KIND_FULL,
    KIND_SAMPLE,
    KIND_SCHEMA,
    KIND_STATISTICS,
    KIND_SUMMARY,
    RepresentationService,
)
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 8000
MAX_NEIGHBORS = 10
MAX_SEMANTIC_CANDIDATES = 10
MAX_CHUNKS = 8
MAX_FOLDER_CONTAINED = 12
PINNED_BODY_EXCERPT_MAX = 1800

USEFUL_REPRESENTATION_KINDS = frozenset(
    {
        KIND_FULL,
        KIND_SUMMARY,
        KIND_CHUNK,
        KIND_SCHEMA,
        KIND_STATISTICS,
        KIND_SAMPLE,
    }
)

STRUCTURAL_EDGE_TYPES = frozenset(
    {
        "parent_of",
        "child_of",
        "blocked_by",
        "blocks",
        "depends_on",
        "dependency_of",
        "part_of",
    }
)

EDGE_TYPE_PRIORITY = {
    "parent_of": 0,
    "child_of": 1,
    "blocked_by": 2,
    "blocks": 3,
    "depends_on": 4,
    "dependency_of": 5,
    "part_of": 6,
}

_TRIM_SEMANTIC = 400
_TRIM_NEIGHBOR = 300
_TRIM_CHUNK = 200
_TRIM_REPR_DETAIL = 100


@dataclass
class _Slot:
    item: ContextItem
    sort_key: tuple
    trim_order: int = 0
    protected: bool = False


class ContextService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._embedding_service = embedding_service
        self._graph = GraphService(session, user_id, embedding_service)
        self._search = SearchService(session, user_id)
        self._representations = RepresentationService(session, user_id, embedding_service)

    def build_context(
        self,
        object_id: UUID | None = None,
        query: str | None = None,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> ContextBuildResult:
        max_chars = max(1, max_chars)
        if object_id is None and query is None:
            return ContextBuildResult(items=[], total_chars=0, truncated=False)

        slots: list[_Slot] = []
        included_object_ids: set[UUID] = set()
        representation_object_ids: set[UUID] = set()
        is_folder_scope = False

        if object_id is not None:
            target = self._graph.get_object(object_id)
            included_object_ids.add(target.id)
            representation_object_ids.add(target.id)
            slots.append(
                _Slot(
                    sort_key=(0, str(target.id), "", -1),
                    trim_order=0,
                    protected=True,
                    item=self._object_item(
                        target,
                        content=self._target_reference_content(target),
                        why_included="target object",
                    ),
                )
            )

            pinned_edges = self._session.scalars(
                select(Edge).where(
                    Edge.user_id == self._user_id,
                    Edge.source_id == object_id,
                    Edge.type == "references",
                    Edge.state != "rejected",
                )
            ).all()
            for edge in sorted(pinned_edges, key=lambda row: str(row.target_id)):
                meta = edge.metadata_ or {}
                if meta.get("context_role") != PINNED_CONTEXT_ROLE:
                    continue
                if meta.get("added_by") != PINNED_ADDED_BY:
                    continue
                neighbor = self._session.scalar(
                    select(Object).where(
                        Object.id == edge.target_id,
                        Object.user_id == self._user_id,
                    )
                )
                if neighbor is None or neighbor.state == "rejected":
                    continue
                included_object_ids.add(neighbor.id)
                representation_object_ids.add(neighbor.id)
                slots.append(
                    _Slot(
                        sort_key=(0, "pinned", str(neighbor.id), 0),
                        trim_order=0,
                        protected=True,
                        item=self._object_item(
                            neighbor,
                            content=self._pinned_context_content(neighbor),
                            edge=edge,
                            why_included="user-pinned context",
                        ),
                    )
                )

            if target.kind == FOLDER_KIND:
                if query:
                    is_folder_scope = True
                slots.extend(
                    self._folder_contained_slots(
                        folder=target,
                        query=query,
                        included_object_ids=included_object_ids,
                        representation_object_ids=representation_object_ids,
                    )
                )

            neighbor_rows = self._graph.get_neighbors(object_id, limit=MAX_NEIGHBORS)
            neighbor_rows = sorted(
                neighbor_rows,
                key=lambda row: (
                    EDGE_TYPE_PRIORITY.get(row[1].type, 50),
                    row[1].type,
                    str(row[0].id),
                ),
            )

            for neighbor, edge, _direction in neighbor_rows:
                if neighbor.id in included_object_ids:
                    continue
                included_object_ids.add(neighbor.id)
                representation_object_ids.add(neighbor.id)
                is_structural = edge.type in STRUCTURAL_EDGE_TYPES
                protected = is_structural or edge.origin == "source"
                trim_order = _TRIM_NEIGHBOR if not is_structural else 0
                slots.append(
                    _Slot(
                        sort_key=(1 if is_structural else 5, edge.type, str(neighbor.id), -1),
                        trim_order=trim_order,
                        protected=protected,
                        item=self._object_item(
                            neighbor,
                            content=self._neighbor_reference_content(neighbor),
                            edge=edge,
                            why_included=(
                                f"structural graph relation ({edge.type})"
                                if is_structural
                                else f"direct graph neighbor ({edge.type})"
                            ),
                        ),
                    )
                )

        if query and not is_folder_scope:
            semantic_results = self._search.search(query=query, limit=MAX_SEMANTIC_CANDIDATES)
            for result in semantic_results:
                if result.id in included_object_ids:
                    continue
                obj = self._session.scalar(
                    select(Object).where(
                        Object.id == result.id,
                        Object.user_id == self._user_id,
                    )
                )
                if obj is None or obj.state == "rejected" or is_object_hidden_from_active_reads(obj):
                    continue
                included_object_ids.add(obj.id)
                representation_object_ids.add(obj.id)
                slots.append(
                    _Slot(
                        sort_key=(6, str(obj.id), "", -1),
                        trim_order=_TRIM_SEMANTIC,
                        item=self._object_item(
                            obj,
                            content=self._neighbor_reference_content(obj),
                            why_included="semantic object match",
                        ),
                    )
                )

        for obj_id in sorted(representation_object_ids, key=str):
            obj = self._session.scalar(
                select(Object).where(Object.id == obj_id, Object.user_id == self._user_id)
            )
            if obj is None:
                continue
            reps = filter_current_representations(
                obj,
                self._representations.list_for_object(obj_id),
            )
            if not reps:
                continue
            slots.extend(
                self._representation_slots(
                    obj=obj,
                    representations=reps,
                    query=query,
                )
            )

        slots.sort(key=lambda slot: slot.sort_key)
        trimmed_slots, truncated = self._trim_to_budget(slots, max_chars)
        trimmed_slots, truncated_content = self._truncate_to_budget(trimmed_slots, max_chars)
        trimmed = truncated or truncated_content
        trimmed_slots.sort(key=lambda slot: slot.sort_key)
        items = [slot.item for slot in trimmed_slots]
        total_chars = sum(_item_chars(item) for item in items)
        return ContextBuildResult(items=items, total_chars=total_chars, truncated=trimmed)

    def _trim_to_budget(self, slots: list[_Slot], max_chars: int) -> tuple[list[_Slot], bool]:
        working = list(slots)
        truncated = False

        while _slots_chars(working) > max_chars:
            removable = [
                index
                for index, slot in enumerate(working)
                if not slot.protected and slot.trim_order > 0
            ]
            if not removable:
                break
            remove_index = max(
                removable,
                key=lambda index: (working[index].trim_order, index),
            )
            working.pop(remove_index)
            truncated = True

        return working, truncated

    def _truncate_to_budget(self, slots: list[_Slot], max_chars: int) -> tuple[list[_Slot], bool]:
        working = list(slots)
        truncated = False

        while _slots_chars(working) > max_chars:
            protected = [slot for slot in working if slot.protected]
            if not protected:
                break
            slot = max(protected, key=lambda item: len(item.item.content))
            if not slot.item.content:
                break
            truncated = True
            excess = _slots_chars(working) - max_chars
            new_len = max(0, len(slot.item.content) - excess)
            slot.item = slot.item.model_copy(
                update={"content": _truncate_text(slot.item.content, new_len)}
            )

        return working, truncated

    def _representation_slots(
        self,
        obj: Object,
        representations: list[Representation],
        query: str | None,
    ) -> list[_Slot]:
        slots: list[_Slot] = []

        summary_rep = next((rep for rep in representations if rep.kind == KIND_SUMMARY), None)
        full_rep = next((rep for rep in representations if rep.kind == KIND_FULL), None)
        chunk_reps = [rep for rep in representations if rep.kind == KIND_CHUNK]

        if summary_rep is not None:
            slots.append(
                _Slot(
                    sort_key=(2, str(obj.id), KIND_SUMMARY, summary_rep.part_index or 0),
                    trim_order=_TRIM_REPR_DETAIL,
                    item=self._representation_item(
                        obj,
                        summary_rep,
                        why_included="document summary",
                    ),
                )
            )
        elif full_rep is not None and not chunk_reps:
            slots.append(
                _Slot(
                    sort_key=(2, str(obj.id), KIND_FULL, 0),
                    trim_order=_TRIM_REPR_DETAIL,
                    item=self._representation_item(
                        obj,
                        full_rep,
                        why_included="small resource full text",
                    ),
                )
            )

        for rep in representations:
            if rep.kind == KIND_SCHEMA:
                slots.append(
                    _Slot(
                        sort_key=(3, str(obj.id), KIND_SCHEMA, 0),
                        trim_order=_TRIM_REPR_DETAIL,
                        item=self._representation_item(
                            obj,
                            rep,
                            why_included="dataset schema",
                        ),
                    )
                )
            elif rep.kind == KIND_STATISTICS:
                slots.append(
                    _Slot(
                        sort_key=(4, str(obj.id), KIND_STATISTICS, 0),
                        trim_order=_TRIM_REPR_DETAIL,
                        item=self._representation_item(
                            obj,
                            rep,
                            why_included="dataset statistics",
                        ),
                    )
                )
            elif rep.kind == KIND_SAMPLE:
                slots.append(
                    _Slot(
                        sort_key=(5, str(obj.id), KIND_SAMPLE, 0),
                        trim_order=_TRIM_REPR_DETAIL,
                        item=self._representation_item(
                            obj,
                            rep,
                            why_included="dataset sample",
                        ),
                    )
                )

        if chunk_reps and query:
            ranked_chunks = self._rank_chunks(chunk_reps, query)
            for rank, chunk_rep in enumerate(ranked_chunks[:MAX_CHUNKS]):
                slots.append(
                    _Slot(
                        sort_key=(7, str(obj.id), KIND_CHUNK, rank),
                        trim_order=_TRIM_CHUNK,
                        item=self._representation_item(
                            obj,
                            chunk_rep,
                            why_included="relevant document chunk",
                            query=query,
                        ),
                    )
                )

        return slots

    def _rank_chunks(self, chunk_reps: list[Representation], query: str) -> list[Representation]:
        query_vector: list[float] | None = None
        if self._embedding_service is not None:
            try:
                query_vector = self._embedding_service.embed(query)
            except Exception:  # noqa: BLE001
                logger.warning("chunk ranking embedding failed; using lexical fallback")
                query_vector = None

        def rank_key(rep: Representation) -> tuple[float, float, float, int, str]:
            exact_match, coverage = lexical_match_score(rep.text or "", query)
            if rep.embedding is not None and query_vector is not None:
                distance = _cosine_distance(list(rep.embedding), query_vector)
            else:
                distance = 1.0
            return (
                exact_match,
                coverage,
                -distance,
                -(rep.part_index or 0),
                str(rep.id),
            )

        return sorted(chunk_reps, key=rank_key, reverse=True)

    def _rank_chunks_lexical(
        self,
        chunk_reps: list[Representation],
        query: str,
    ) -> list[Representation]:
        query_norm = _normalize_lexical_text(query)
        query_tokens = _lexical_tokens(query_norm)

        def score(rep: Representation) -> tuple[float, float, int, str]:
            text_norm = _normalize_lexical_text(rep.text or "")
            exact_match = 1.0 if query_norm and query_norm in text_norm else 0.0
            if not query_tokens:
                coverage = 0.0
            else:
                text_tokens = _lexical_tokens(text_norm)
                coverage = len(query_tokens & text_tokens) / len(query_tokens)
            return (
                exact_match,
                coverage,
                -(rep.part_index or 0),
                str(rep.id),
            )

        return sorted(chunk_reps, key=score, reverse=True)

    def _object_item(
        self,
        obj: Object,
        content: str,
        why_included: str,
        edge: Edge | None = None,
    ) -> ContextItem:
        return ContextItem(
            object_id=obj.id,
            kind=obj.kind,
            title=obj.title,
            content=content,
            origin=obj.origin,
            state=obj.state,
            confidence=obj.confidence,
            relation_type=edge.type if edge is not None else None,
            relation_origin=edge.origin if edge is not None else None,
            relation_state=edge.state if edge is not None else None,
            relation_confidence=edge.confidence if edge is not None else None,
            why_included=why_included,
            canonical_uri=obj.canonical_uri,
        )

    def _representation_item(
        self,
        obj: Object,
        rep: Representation,
        why_included: str,
        query: str | None = None,
    ) -> ContextItem:
        content = rep.text or ""
        if query and rep.kind == KIND_CHUNK and content:
            content = build_query_centered_snippet(
                content,
                query,
                CONTEXT_EVIDENCE_MAX_CHARS,
            )
        return ContextItem(
            object_id=obj.id,
            kind=obj.kind,
            title=obj.title,
            content=content,
            origin=obj.origin,
            state=obj.state,
            confidence=obj.confidence,
            representation_kind=rep.kind,
            why_included=why_included,
            canonical_uri=obj.canonical_uri,
        )

    def _pinned_context_content(self, obj: Object) -> str:
        parts = [obj.title]
        if obj.canonical_uri:
            parts.append(f"reference: {obj.canonical_uri}")
        if self._has_useful_representations(obj.id):
            return "\n".join(parts)
        if obj.body:
            excerpt, truncated = _bounded_body_excerpt(obj.body, PINNED_BODY_EXCERPT_MAX)
            label = "body excerpt (truncated)" if truncated else "body excerpt"
            parts.append(f"{label}:\n{excerpt}")
        return "\n".join(parts)

    def _filtered_representations(self, obj: Object) -> list[Representation]:
        return filter_current_representations(
            obj,
            self._representations.list_for_object(obj.id),
        )

    def _has_useful_representations(self, object_id: UUID) -> bool:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            return False
        reps = self._filtered_representations(obj)
        return any(
            rep.kind in USEFUL_REPRESENTATION_KINDS and (rep.text or rep.kind == KIND_SCHEMA)
            for rep in reps
        )

    def _target_reference_content(self, obj: Object) -> str:
        reps = self._filtered_representations(obj)
        if any(rep.kind in {KIND_CHUNK, KIND_SCHEMA} for rep in reps):
            if obj.canonical_uri:
                return f"reference: {obj.canonical_uri}"
            return f"{obj.title} (resource with representations)"
        if obj.body:
            return f"{obj.title}\n{obj.body}"
        return obj.title

    def _neighbor_reference_content(self, obj: Object) -> str:
        if obj.canonical_uri:
            return f"reference: {obj.canonical_uri}"
        reps = self._filtered_representations(obj)
        if any(rep.kind in {KIND_CHUNK, KIND_SCHEMA} for rep in reps):
            return f"{obj.title} (resource with representations)"
        if obj.body and len(obj.body) <= 500:
            return f"{obj.title}\n{obj.body}"
        return obj.title

    def _folder_contained_slots(
        self,
        folder: Object,
        query: str | None,
        included_object_ids: set[UUID],
        representation_object_ids: set[UUID],
    ) -> list[_Slot]:
        contained_edges = self._session.scalars(
            select(Edge).where(
                Edge.user_id == self._user_id,
                Edge.source_id == folder.id,
                Edge.type == EDGE_TYPE_CONTAINS,
                Edge.state != "rejected",
            )
        ).all()
        contained_ids = [edge.target_id for edge in contained_edges]
        if not contained_ids:
            return []

        objects = list(
            self._session.scalars(
                select(Object).where(
                    Object.user_id == self._user_id,
                    Object.id.in_(contained_ids),
                    Object.state != "rejected",
                )
            ).all()
        )
        if query:
            query_lower = query.lower()
            objects.sort(
                key=lambda obj: (
                    -_folder_contained_text_score(obj, query_lower),
                    str(obj.id),
                )
            )
        else:
            objects.sort(
                key=lambda obj: (
                    -(obj.updated_at.timestamp() if obj.updated_at else 0),
                    str(obj.id),
                )
            )
        objects = objects[:MAX_FOLDER_CONTAINED]

        slots: list[_Slot] = []
        for obj in objects:
            if obj.id in included_object_ids:
                continue
            included_object_ids.add(obj.id)
            representation_object_ids.add(obj.id)
            meta = obj.metadata_ or {}
            summary = meta.get(SEMANTIC_SUMMARY_METADATA_KEY)
            content = (
                str(summary)[:500]
                if isinstance(summary, str) and summary.strip()
                else self._neighbor_reference_content(obj)
            )
            slots.append(
                _Slot(
                    sort_key=(2, str(obj.id), "", -1),
                    trim_order=_TRIM_NEIGHBOR,
                    item=self._object_item(
                        obj,
                        content=content,
                        why_included="folder-contained resource",
                    ),
                )
            )
        return slots


def _folder_contained_text_score(obj: Object, query_lower: str) -> int:
    if not query_lower:
        return 0
    score = 0
    title = obj.title.lower()
    if query_lower in title:
        score += 10
    meta = obj.metadata_ or {}
    summary = meta.get(SEMANTIC_SUMMARY_METADATA_KEY)
    if isinstance(summary, str) and query_lower in summary.lower():
        score += 5
    if obj.body and query_lower in obj.body.lower():
        score += 3
    return score


def _bounded_body_excerpt(body: str, max_len: int) -> tuple[str, bool]:
    if len(body) <= max_len:
        return body, False
    if max_len <= 1:
        return "…", True
    return body[: max_len - 1].rstrip() + "…", True


def _item_chars(item: ContextItem) -> int:
    return len(item.content) + len(item.title) + len(item.why_included)


def _slots_chars(slots: list[_Slot]) -> int:
    return sum(_item_chars(slot.item) for slot in slots)


def _truncate_text(text: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len == 1:
        return "…"
    return text[: max_len - 1].rstrip() + "…"


def _cosine_distance(left: list[float], right: list[float]) -> float:
    dot = sum(l * r for l, r in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 1.0
    return 1.0 - dot / (left_norm * right_norm)


def _normalize_lexical_text(text: str) -> str:
    return " ".join(text.lower().split())


def _lexical_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in text.split():
        cleaned = token.strip(".,;:!?\"'«»()[]{}")
        if len(cleaned) >= 3:
            tokens.add(cleaned)
    return tokens
