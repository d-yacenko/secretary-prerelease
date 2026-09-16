"""Bounded correlation candidate generation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Edge, Object
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.services.correlation_constants import (
    CANDIDATE_MAX_EXACT_THREAD,
    CANDIDATE_MAX_PARTICIPANT_TIME,
    CANDIDATE_MAX_SEMANTIC,
    CORRELATION_MAX_FINAL_CANDIDATES,
    MAX_MAIL_PEER_LOOKUP_ROWS,
    SEMANTIC_SUMMARY_METADATA_KEY,
)
from app.services.correlation_input import extract_correlation_participants
from app.services.correlation_models import CorrelationCandidate
from app.services.errors import NotFoundError
from app.services.representation_service import KIND_SUMMARY, RepresentationService
from app.services.search_service import SearchService

_TIME_WINDOW_HOURS = 72


def _primary_date_label(obj: Object) -> str | None:
    if obj.occurred_at is not None:
        return obj.occurred_at.isoformat()
    if obj.due_at is not None:
        return obj.due_at.isoformat()
    if obj.start_at is not None:
        return obj.start_at.isoformat()
    meta = obj.metadata_ or {}
    for key in ("timestamp", "modified_at", "registered_at"):
        value = meta.get(key)
        if value:
            return str(value)
    return None


def _content_summary(obj: Object, summary_rep: str | None) -> str:
    meta = obj.metadata_ or {}
    semantic = meta.get(SEMANTIC_SUMMARY_METADATA_KEY)
    if isinstance(semantic, str) and semantic.strip():
        return semantic.strip()[:500]
    if summary_rep:
        return summary_rep[:500]
    if obj.body:
        return obj.body[:500]
    return obj.title[:500]


class CorrelationCandidateService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._representations = RepresentationService(session, user_id)
        self._search = SearchService(session, user_id)

    def collect_candidates(self, trigger_object_id: UUID) -> list[CorrelationCandidate]:
        trigger = self._session.scalar(
            select(Object).where(
                Object.id == trigger_object_id,
                Object.user_id == self._user_id,
            )
        )
        if trigger is None:
            raise NotFoundError("object", trigger_object_id)

        by_id: dict[UUID, CorrelationCandidate] = {}

        def add_candidate(candidate: CorrelationCandidate) -> None:
            if candidate.object_id == trigger_object_id:
                return
            if len(by_id) >= CORRELATION_MAX_FINAL_CANDIDATES:
                return
            existing = by_id.get(candidate.object_id)
            if existing is None:
                by_id[candidate.object_id] = candidate
                return
            merged_reasons = tuple(dict.fromkeys((*existing.reasons, *candidate.reasons)))
            by_id[candidate.object_id] = CorrelationCandidate(
                object_id=existing.object_id,
                kind=existing.kind,
                title=existing.title,
                primary_date=existing.primary_date,
                content_summary=existing.content_summary,
                reasons=merged_reasons,
                existing_relation=existing.existing_relation or candidate.existing_relation,
            )

        for candidate in self._exact_thread_candidates(trigger):
            add_candidate(candidate)
            if len(by_id) >= CORRELATION_MAX_FINAL_CANDIDATES:
                break

        if len(by_id) < CORRELATION_MAX_FINAL_CANDIDATES:
            for candidate in self._participant_time_candidates(trigger):
                add_candidate(candidate)
                if len(by_id) >= CORRELATION_MAX_FINAL_CANDIDATES:
                    break

        if len(by_id) < CORRELATION_MAX_FINAL_CANDIDATES:
            for candidate in self._semantic_candidates(trigger, by_id):
                add_candidate(candidate)
                if len(by_id) >= CORRELATION_MAX_FINAL_CANDIDATES:
                    break

        ordered = sorted(by_id.values(), key=lambda row: (row.kind, row.title, str(row.object_id)))
        return ordered[:CORRELATION_MAX_FINAL_CANDIDATES]

    def _is_eligible_target(self, obj: Object) -> bool:
        if obj.state == "rejected":
            return False
        if is_object_hidden_from_active_reads(obj):
            return False
        return True

    def _to_candidate(
        self,
        obj: Object,
        reasons: tuple[str, ...],
        existing_relation: str | None = None,
    ) -> CorrelationCandidate:
        summary_rep = None
        reps = self._representations.list_for_object(obj.id)
        for rep in reps:
            if rep.kind == KIND_SUMMARY:
                summary_rep = rep.text
                break
        return CorrelationCandidate(
            object_id=obj.id,
            kind=obj.kind,
            title=obj.title,
            primary_date=_primary_date_label(obj),
            content_summary=_content_summary(obj, summary_rep),
            reasons=reasons,
            existing_relation=existing_relation,
        )

    def _exact_thread_candidates(self, trigger: Object) -> list[CorrelationCandidate]:
        if trigger.kind != "email":
            return []
        meta = trigger.metadata_ or {}
        thread_id = meta.get("thread_id")
        if not thread_id:
            return []
        peers = self._session.scalars(
            select(Object).where(
                Object.user_id == self._user_id,
                Object.kind == "email",
                Object.provider == trigger.provider,
                Object.id != trigger.id,
            )
            .order_by(Object.occurred_at.desc().nullslast(), Object.id)
            .limit(MAX_MAIL_PEER_LOOKUP_ROWS)
        ).all()
        results: list[CorrelationCandidate] = []
        for peer in peers:
            if not self._is_eligible_target(peer):
                continue
            peer_meta = peer.metadata_ or {}
            if str(peer_meta.get("thread_id")) != str(thread_id):
                continue
            results.append(
                self._to_candidate(peer, ("same_thread",), self._relation_hint(trigger.id, peer.id))
            )
            if len(results) >= CANDIDATE_MAX_EXACT_THREAD:
                break
        return results

    def _participant_time_candidates(self, trigger: Object) -> list[CorrelationCandidate]:
        participants = extract_correlation_participants(trigger)
        anchor_time = trigger.occurred_at or trigger.start_at or trigger.due_at
        if not participants and anchor_time is None:
            return []

        candidates = self._session.scalars(
            select(Object).where(
                Object.user_id == self._user_id,
                Object.id != trigger.id,
            )
            .order_by(Object.updated_at.desc().nullslast(), Object.id)
            .limit(MAX_MAIL_PEER_LOOKUP_ROWS)
        ).all()

        results: list[CorrelationCandidate] = []
        for obj in candidates:
            if not self._is_eligible_target(obj):
                continue
            reasons: list[str] = []
            if participants and self._participants_overlap(
                participants, extract_correlation_participants(obj)
            ):
                reasons.append("shared_participant")
            if anchor_time is not None and self._time_close(anchor_time, obj):
                reasons.append("time_proximity")
            if not reasons:
                continue
            results.append(
                self._to_candidate(obj, tuple(reasons), self._relation_hint(trigger.id, obj.id))
            )
            if len(results) >= CANDIDATE_MAX_PARTICIPANT_TIME:
                break
        return results

    def _semantic_candidates(
        self,
        trigger: Object,
        existing: dict[UUID, CorrelationCandidate],
    ) -> list[CorrelationCandidate]:
        remaining = CORRELATION_MAX_FINAL_CANDIDATES - len(existing)
        semantic_limit = min(CANDIDATE_MAX_SEMANTIC, remaining)
        if semantic_limit <= 0:
            return []

        query_parts = [trigger.title]
        meta = trigger.metadata_ or {}
        semantic = meta.get(SEMANTIC_SUMMARY_METADATA_KEY)
        if isinstance(semantic, str):
            query_parts.append(semantic)
        if trigger.body:
            query_parts.append(trigger.body[:400])
        query = " ".join(part for part in query_parts if part).strip()
        if not query:
            return []
        hits = self._search.search(query=query, limit=semantic_limit)
        results: list[CorrelationCandidate] = []
        for hit in hits:
            if hit.id == trigger.id or hit.id in existing:
                continue
            obj = self._session.scalar(
                select(Object).where(Object.id == hit.id, Object.user_id == self._user_id)
            )
            if obj is None or not self._is_eligible_target(obj):
                continue
            results.append(
                self._to_candidate(
                    obj,
                    ("semantic_retrieval",),
                    self._relation_hint(trigger.id, obj.id),
                )
            )
            if len(results) >= semantic_limit:
                break
        return results

    def _relation_hint(self, left_id: UUID, right_id: UUID) -> str | None:
        edge = self._session.scalar(
            select(Edge).where(
                Edge.user_id == self._user_id,
                Edge.state != "rejected",
                or_(
                    Edge.source_id == left_id,
                    Edge.target_id == left_id,
                ),
                or_(
                    Edge.source_id == right_id,
                    Edge.target_id == right_id,
                ),
            ).limit(1)
        )
        if edge is None:
            return None
        return f"{edge.type}:{edge.state}"

    def _participants_overlap(self, left: set[str], right: set[str]) -> bool:
        if not left or not right:
            return False
        return not left.isdisjoint(right)

    def _time_close(self, anchor: datetime, obj: Object) -> bool:
        candidate_time = obj.occurred_at or obj.start_at or obj.due_at
        if candidate_time is None:
            return False
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=UTC)
        if candidate_time.tzinfo is None:
            candidate_time = candidate_time.replace(tzinfo=UTC)
        delta = abs((candidate_time - anchor).total_seconds())
        return delta <= _TIME_WINDOW_HOURS * 3600
