"""Provider-neutral personal relevance evidence models (Pass E-B).

Facts/evidence are code-produced. Semantic judgment (relationship/dependency)
belongs to the Secretary LLM in a later pass. E-B does not infer those enums.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

PERSONAL_RELEVANCE_EVIDENCE_VERSION = 1
PERSONAL_RELEVANCE_MAX_OBJECTS = 20
PERSONAL_RELEVANCE_MAX_LABELS_PER_OBJECT = 8
PERSONAL_RELEVANCE_MAX_TITLE_CHARS = 500
PERSONAL_RELEVANCE_MAX_SEMANTIC_CONTEXT_CHARS = 4000
PERSONAL_RELEVANCE_MAX_IDENTITY_JSON_CHARS = 4000
PERSONAL_RELEVANCE_MAX_PARTICIPATION_ROLES = 8
PERSONAL_RELEVANCE_MAX_EMAIL_ADDRESSES = 20
PERSONAL_RELEVANCE_MAX_ATTENDEES = 20
PERSONAL_RELEVANCE_MAX_MENTIONS = 30
PERSONAL_RELEVANCE_EMAIL_INSPECT_LIMIT = PERSONAL_RELEVANCE_MAX_EMAIL_ADDRESSES + 1
PERSONAL_RELEVANCE_ATTENDEE_INSPECT_LIMIT = PERSONAL_RELEVANCE_MAX_ATTENDEES + 1
PERSONAL_RELEVANCE_MENTION_INSPECT_LIMIT = PERSONAL_RELEVANCE_MAX_MENTIONS + 1
LABEL_EVIDENCE_FETCH_LIMIT = PERSONAL_RELEVANCE_MAX_LABELS_PER_OBJECT + 1

USER_PARTICIPATION_ROLES = (
    "author",
    "sender",
    "direct_recipient",
    "copied_recipient",
    "organizer",
    "attendee",
    "mentioned",
    "assignee",
)

USER_PARTICIPATION_ROLE_SET = frozenset(USER_PARTICIPATION_ROLES)


class PersonalRelationship(StrEnum):
    """Future Secretary judgment vocabulary. E-B code must not assign these."""

    RESPONSIBLE = "responsible"
    PARTICIPANT = "participant"
    OBSERVER = "observer"
    RELATED = "related"
    UNKNOWN = "unknown"


class PersonalDependency(StrEnum):
    """Independent of relationship. E-B code must not assign these."""

    WAITING_ON_USER = "waiting_on_user"
    WAITING_ON_OTHERS = "waiting_on_others"
    NONE = "none"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PersonalRelevanceUserContext:
    full_name: str | None
    preferred_name: str | None
    aliases: tuple[str, ...]
    roles: tuple[str, ...]
    organizations: tuple[str, ...]
    emails: tuple[str, ...]
    phones: tuple[str, ...]
    telegram: tuple[str, ...]
    other_identifiers: tuple[str, ...]
    connected_account_identifiers: tuple[str, ...]
    semantic_context: str
    truncated: bool = False

    def to_payload(self) -> dict:
        return {
            "full_name": self.full_name,
            "preferred_name": self.preferred_name,
            "aliases": list(self.aliases),
            "roles": list(self.roles),
            "organizations": list(self.organizations),
            "emails": list(self.emails),
            "phones": list(self.phones),
            "telegram": list(self.telegram),
            "other_identifiers": list(self.other_identifiers),
            "connected_account_identifiers": list(self.connected_account_identifiers),
            "semantic_context": self.semantic_context,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class AssignedLabelEvidence:
    label_id: UUID
    title: str
    description: str | None
    assignment_origin: str
    assignment_confidence: float | None

    def to_payload(self) -> dict:
        payload: dict = {
            "label_id": str(self.label_id),
            "title": self.title,
            "description": self.description,
            "assignment_origin": self.assignment_origin,
        }
        if self.assignment_confidence is not None:
            payload["assignment_confidence"] = self.assignment_confidence
        return payload


@dataclass(frozen=True)
class ObjectPersonalRelevanceEvidence:
    object_id: UUID
    kind: str
    provider: str | None
    origin: str
    state: str
    status: str | None
    title: str
    updated_at: datetime | None
    due_at: datetime | None
    start_at: datetime | None
    occurred_at: datetime | None
    user_participation_roles: tuple[str, ...]
    assigned_labels: tuple[AssignedLabelEvidence, ...]
    labels_truncated: bool = False
    participation_truncated: bool = False

    def to_payload(self) -> dict:
        return {
            "object_id": str(self.object_id),
            "kind": self.kind,
            "provider": self.provider,
            "origin": self.origin,
            "state": self.state,
            "status": self.status,
            "title": self.title,
            "updated_at": _iso(self.updated_at),
            "due_at": _iso(self.due_at),
            "start_at": _iso(self.start_at),
            "occurred_at": _iso(self.occurred_at),
            "user_participation_roles": list(self.user_participation_roles),
            "participation_truncated": self.participation_truncated,
            "assigned_labels": [item.to_payload() for item in self.assigned_labels],
            "labels_truncated": self.labels_truncated,
        }


@dataclass(frozen=True)
class PersonalRelevanceEvidenceSnapshot:
    version: int
    user_context: PersonalRelevanceUserContext
    objects: tuple[ObjectPersonalRelevanceEvidence, ...]
    user_context_signature: str
    truncated_objects: bool = False
    object_evidence_signatures: dict[str, str] = field(default_factory=dict)

    def to_payload(self) -> dict:
        return {
            "version": self.version,
            "user_context": self.user_context.to_payload(),
            "truncated_objects": self.truncated_objects,
            "user_context_signature": self.user_context_signature,
            "objects": [item.to_payload() for item in self.objects],
            "object_evidence_signatures": dict(self.object_evidence_signatures),
        }


def user_context_canonical_payload(context: PersonalRelevanceUserContext) -> dict:
    return context.to_payload()


def object_evidence_canonical_payload(
    record: ObjectPersonalRelevanceEvidence,
    user_context_signature: str,
) -> dict:
    return {
        "version": PERSONAL_RELEVANCE_EVIDENCE_VERSION,
        **record.to_payload(),
        "user_context_signature": user_context_signature,
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
