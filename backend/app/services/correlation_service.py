"""Orchestrates bounded correlation runs."""

import math
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import EdgeCreate
from app.db.models import Object
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.llm.correlation_judge import CorrelationJudge
from app.services.correlation_candidate_service import CorrelationCandidateService
from app.services.correlation_constants import (
    CORRELATION_ALLOWED_TYPES,
    CORRELATION_MAX_PROPOSED_EDGES,
    CORRELATION_MIN_CONFIDENCE,
    CORRELATION_TRIGGER_KINDS,
    CORRELATION_VERSION,
)
from app.services.correlation_input import effective_trigger_summary
from app.services.correlation_models import CorrelationCandidate, CorrelationDecision
from app.services.deterministic_relation_service import DeterministicRelationService
from app.services.edge_dedup import (
    correlation_signature,
    has_equivalent_relation,
    has_rejected_proposal_signature,
)
from app.services.errors import NotFoundError
from app.services.graph_service import GraphService
from app.services.provenance import AGENT_ORIGIN, PROPOSED_STATE


class CorrelationService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        judge: CorrelationJudge,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._judge = judge
        self._graph = GraphService(session, user_id)
        self._candidates = CorrelationCandidateService(session, user_id)
        self._deterministic = DeterministicRelationService(session, user_id)

    def run_correlation(self, trigger_object_id: UUID) -> int:
        trigger = self._session.scalar(
            select(Object).where(
                Object.id == trigger_object_id,
                Object.user_id == self._user_id,
            )
        )
        if trigger is None:
            raise NotFoundError("object", trigger_object_id)
        if trigger.kind not in CORRELATION_TRIGGER_KINDS:
            return 0
        if trigger.state == "rejected":
            return 0

        self._deterministic.apply_source_relations(trigger_object_id)
        candidate_list = self._candidates.collect_candidates(trigger_object_id)
        if not candidate_list:
            return 0

        allowed_candidate_ids = {candidate.object_id for candidate in candidate_list}
        trigger_summary = effective_trigger_summary(trigger)
        judge_result = self._judge.judge(
            trigger_title=trigger.title,
            trigger_kind=trigger.kind,
            trigger_summary=trigger_summary,
            candidates=candidate_list,
        )

        created = 0
        for decision in judge_result.decisions:
            if created >= CORRELATION_MAX_PROPOSED_EDGES:
                break
            if not _is_valid_judge_decision(
                decision,
                trigger_object_id,
                allowed_candidate_ids,
                self._session,
                self._user_id,
            ):
                continue
            if has_equivalent_relation(
                self._session,
                self._user_id,
                trigger_object_id,
                decision.target_object_id,
                decision.relation_type,
            ):
                continue
            signature = correlation_signature(
                trigger_object_id,
                decision.target_object_id,
                decision.relation_type,
            )
            if has_rejected_proposal_signature(
                self._session,
                self._user_id,
                trigger_object_id,
                decision.target_object_id,
                decision.relation_type,
                signature,
            ):
                continue
            candidate_reasons = _candidate_reasons(
                candidate_list, decision.target_object_id
            )
            meta = {
                "trigger_object_id": str(trigger_object_id),
                "candidate_reasons": candidate_reasons,
                "rationale": decision.rationale,
                "correlation_version": CORRELATION_VERSION,
                "correlation_signature": signature,
            }
            self._graph.create_edge(
                EdgeCreate(
                    source_id=trigger_object_id,
                    target_id=decision.target_object_id,
                    type=decision.relation_type,
                    origin=AGENT_ORIGIN,
                    state=PROPOSED_STATE,
                    confidence=decision.confidence,
                    metadata=meta,
                )
            )
            created += 1
        return created


def _is_valid_judge_decision(
    decision: CorrelationDecision,
    trigger_object_id: UUID,
    allowed_candidate_ids: set[UUID],
    session: Session,
    user_id: UUID,
) -> bool:
    target_id = decision.target_object_id
    if target_id not in allowed_candidate_ids:
        return False
    if target_id == trigger_object_id:
        return False
    if decision.relation_type not in CORRELATION_ALLOWED_TYPES:
        return False
    confidence = decision.confidence
    if not math.isfinite(confidence):
        return False
    if confidence < 0.0 or confidence > 1.0:
        return False
    if confidence < CORRELATION_MIN_CONFIDENCE:
        return False
    target = session.scalar(
        select(Object).where(Object.id == target_id, Object.user_id == user_id)
    )
    if target is None:
        return False
    if target.state == "rejected":
        return False
    if is_object_hidden_from_active_reads(target):
        return False
    return True


def _candidate_reasons(
    candidates: list[CorrelationCandidate],
    target_id: UUID,
) -> list[str]:
    for candidate in candidates:
        if candidate.object_id == target_id:
            return list(candidate.reasons)
    return []
