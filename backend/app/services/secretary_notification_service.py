from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ContextBuildResult, ContextItem
from app.db.models import Object
from app.llm.secretary_models import SecretaryAnalysis, SecretaryProposal
from app.services.notification_service import NotificationService


def calculate_notification_priority(
    analysis: SecretaryAnalysis,
    proposal: SecretaryProposal,
) -> str:
    importance = analysis.importance or 0.0
    urgency = analysis.urgency or 0.0
    score = max(importance, urgency) * 0.6 + proposal.confidence * 0.4
    if importance >= 0.9 and urgency >= 0.85:
        return "urgent"
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "normal"
    return "low"


def _existing_object_id(session: Session, user_id: UUID, object_id: UUID | None) -> UUID | None:
    if object_id is None:
        return None
    owned = session.scalar(
        select(Object.id).where(Object.id == object_id, Object.user_id == user_id)
    )
    return object_id if owned is not None else None


def _evidence_entry(index: int, item: ContextItem) -> dict:
    entry: dict = {
        "context_index": index,
        "object_id": str(item.object_id),
        "kind": item.kind,
        "title": item.title,
        "why_included": item.why_included,
        "origin": item.origin,
        "state": item.state,
    }
    if item.confidence is not None:
        entry["confidence"] = item.confidence
    if item.canonical_uri is not None:
        entry["canonical_uri"] = item.canonical_uri
    if item.relation_type is not None:
        entry["relation_type"] = item.relation_type
    if item.relation_origin is not None:
        entry["relation_origin"] = item.relation_origin
    if item.relation_state is not None:
        entry["relation_state"] = item.relation_state
    if item.relation_confidence is not None:
        entry["relation_confidence"] = item.relation_confidence
    return entry


def proposal_to_payload(
    proposal: SecretaryProposal,
    context: ContextBuildResult,
) -> dict:
    evidence = [
        _evidence_entry(index, context.items[index])
        for index in proposal.evidence_item_indices
    ]
    return {
        "type": proposal.type,
        "title": proposal.title,
        "description": proposal.description,
        "confidence": proposal.confidence,
        "due_at": proposal.due_at.isoformat() if proposal.due_at else None,
        "start_at": proposal.start_at.isoformat() if proposal.start_at else None,
        "relation_type": proposal.relation_type,
        "target_object_id": (
            str(proposal.target_object_id) if proposal.target_object_id else None
        ),
        "evidence": evidence,
    }


def create_notifications_from_analysis(
    service: NotificationService,
    analysis: SecretaryAnalysis,
    context: ContextBuildResult,
) -> list:
    from app.db.models import Notification

    session = service._session
    notifications: list[Notification] = []
    for proposal in analysis.proposals:
        source_item = context.items[proposal.evidence_item_indices[0]]
        related_object_id = _existing_object_id(session, service._user_id, proposal.target_object_id)
        notification = service.create(
            title=proposal.title,
            body=proposal.description or analysis.summary,
            priority=calculate_notification_priority(analysis, proposal),
            source_object_id=source_item.object_id,
            related_object_id=related_object_id,
            proposal=proposal_to_payload(proposal, context),
        )
        notifications.append(notification)
    return notifications
