"""Explainable Person evidence and candidate scoring.

Recording evidence never attaches a PersonIdentity and never merges People.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Object, PersonIdentity, PersonIdentityEvidence
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.person_candidate_names import names_match
from app.domain.person_candidate_score import (
    ACTIVE,
    AUTOMATIC_LINK_THRESHOLD,
    EVIDENCE_TYPES,
    RETRACTED,
    USER_CONFIRMED,
    USER_REJECTED,
    USER_ROUTE_CHOICE,
    CandidateAssessment,
    assess_evidence,
    evidence_polarity,
    evidence_weight,
)
from app.domain.person_identity import NormalizedPersonIdentity
from app.services.errors import NotFoundError, ValidationError
from app.services.person_identity_service import PERSON_KIND, PersonIdentityService
from app.services.provenance import REJECTED_STATE

_MAX_KEY_CHARS = 200
_MAX_EXPLANATION_CHARS = 400
_SECRET_MARKERS = ("token", "password", "secret", "session", "credential", "authorization")


@dataclass(frozen=True)
class PersonCandidate:
    person_id: UUID
    reason: str
    assessment: CandidateAssessment


class PersonEvidenceService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._people = PersonIdentityService(session, user_id)

    def record(
        self,
        person_id: UUID,
        identity: NormalizedPersonIdentity,
        evidence_type: str,
        *,
        provenance_kind: str,
        provenance_key: str,
        source_object_id: UUID | None = None,
        person_identity_id: UUID | None = None,
        explanation: str | None = None,
        details: dict | None = None,
    ) -> PersonIdentityEvidence:
        self._require_active_person(person_id)
        if evidence_type not in EVIDENCE_TYPES:
            raise ValidationError("person evidence type is unknown")
        key = _bounded_key(provenance_key)
        kind = _bounded_key(provenance_kind)
        text = _bounded_explanation(explanation)
        payload = _safe_details(details)
        self._require_source(source_object_id)
        self._require_linked_identity(person_id, person_identity_id, identity)
        existing = self._active_source(person_id, identity, evidence_type, key)
        if existing is not None:
            return existing
        row = PersonIdentityEvidence(
            user_id=self._user_id,
            person_object_id=person_id,
            person_identity_id=person_identity_id,
            provider=identity.provider,
            identity_type=identity.identity_type,
            realm=identity.realm,
            canonical_value=identity.canonical_value,
            evidence_type=evidence_type,
            polarity=evidence_polarity(evidence_type),
            weight=evidence_weight(evidence_type),
            provenance_kind=kind,
            provenance_key=key,
            source_object_id=source_object_id,
            explanation=text,
            details=payload,
            state=ACTIVE,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def record_route_choice(
        self,
        person_id: UUID,
        identity: NormalizedPersonIdentity,
        provenance_key: str,
        *,
        explanation: str | None = None,
    ) -> PersonIdentityEvidence:
        return self.record(
            person_id,
            identity,
            USER_ROUTE_CHOICE,
            provenance_kind="user_feedback",
            provenance_key=provenance_key,
            explanation=explanation,
        )

    def record_confirmation(
        self,
        person_id: UUID,
        identity: NormalizedPersonIdentity,
        provenance_key: str,
        *,
        explanation: str | None = None,
    ) -> PersonIdentityEvidence:
        row = self.record(
            person_id,
            identity,
            USER_CONFIRMED,
            provenance_kind="user_feedback",
            provenance_key=provenance_key,
            explanation=explanation,
        )
        self._retract_type(person_id, identity, USER_REJECTED, superseded_by=row.id)
        return row

    def record_rejection(
        self,
        person_id: UUID,
        identity: NormalizedPersonIdentity,
        provenance_key: str,
        *,
        explanation: str | None = None,
    ) -> PersonIdentityEvidence:
        row = self.record(
            person_id,
            identity,
            USER_REJECTED,
            provenance_kind="user_feedback",
            provenance_key=provenance_key,
            explanation=explanation,
        )
        self._retract_type(person_id, identity, USER_CONFIRMED, superseded_by=row.id)
        return row

    def retract(self, evidence_id: UUID) -> PersonIdentityEvidence:
        row = self._session.get(PersonIdentityEvidence, evidence_id)
        if row is None or row.user_id != self._user_id:
            raise NotFoundError("person_identity_evidence", evidence_id)
        if row.state == ACTIVE:
            row.state = RETRACTED
            row.retracted_at = datetime.now(UTC)
            self._session.flush()
        return row

    def is_rejected(self, person_id: UUID, identity: NormalizedPersonIdentity) -> bool:
        row = self._session.scalar(
            select(PersonIdentityEvidence.id).where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id == person_id,
                PersonIdentityEvidence.state == ACTIVE,
                PersonIdentityEvidence.evidence_type == USER_REJECTED,
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
            )
        )
        return row is not None

    def score(
        self,
        person_id: UUID,
        identity: NormalizedPersonIdentity,
    ) -> CandidateAssessment:
        self._require_person(person_id)
        return assess_evidence(self._rows(person_id, identity, active_only=True))

    def history(
        self,
        person_id: UUID,
        identity: NormalizedPersonIdentity,
    ) -> list[PersonIdentityEvidence]:
        self._require_person(person_id)
        return self._rows(person_id, identity, active_only=False)

    def propose_candidates(
        self,
        identity: NormalizedPersonIdentity | None = None,
        display_name: str | None = None,
    ) -> list[PersonCandidate]:
        found: dict[UUID, str] = {}
        if identity is not None:
            person = self._people.resolve(identity)
            if person is not None:
                found[person.id] = "exact_identifier"
        if display_name:
            for person_id in self._name_matches(display_name):
                found.setdefault(person_id, "name_similarity")
        candidates: list[PersonCandidate] = []
        for person_id, reason in found.items():
            assessment = (
                self.score(person_id, identity)
                if identity is not None
                else CandidateAssessment(0, "possible", (), False)
            )
            candidates.append(PersonCandidate(person_id, reason, assessment))
        return candidates

    def automatic_link_threshold(self) -> int:
        return AUTOMATIC_LINK_THRESHOLD

    def _retract_type(
        self,
        person_id: UUID,
        identity: NormalizedPersonIdentity,
        evidence_type: str,
        *,
        superseded_by: UUID,
    ) -> None:
        now = datetime.now(UTC)
        for row in self._rows(person_id, identity, active_only=True):
            if row.evidence_type != evidence_type or row.id == superseded_by:
                continue
            row.state = RETRACTED
            row.retracted_at = now
            row.superseded_by_id = superseded_by
        self._session.flush()

    def _rows(
        self,
        person_id: UUID,
        identity: NormalizedPersonIdentity,
        *,
        active_only: bool,
    ) -> list[PersonIdentityEvidence]:
        filters = [
            PersonIdentityEvidence.user_id == self._user_id,
            PersonIdentityEvidence.person_object_id == person_id,
            PersonIdentityEvidence.provider == identity.provider,
            PersonIdentityEvidence.identity_type == identity.identity_type,
            PersonIdentityEvidence.realm == identity.realm,
            PersonIdentityEvidence.canonical_value == identity.canonical_value,
        ]
        if active_only:
            filters.append(PersonIdentityEvidence.state == ACTIVE)
        rows = self._session.scalars(
            select(PersonIdentityEvidence)
            .where(*filters)
            .order_by(PersonIdentityEvidence.created_at, PersonIdentityEvidence.id)
        )
        return list(rows)

    def _active_source(
        self,
        person_id: UUID,
        identity: NormalizedPersonIdentity,
        evidence_type: str,
        provenance_key: str,
    ) -> PersonIdentityEvidence | None:
        return self._session.scalar(
            select(PersonIdentityEvidence).where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id == person_id,
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
                PersonIdentityEvidence.evidence_type == evidence_type,
                PersonIdentityEvidence.provenance_key == provenance_key,
                PersonIdentityEvidence.state == ACTIVE,
            )
        )

    def _require_person(self, person_id: UUID) -> Object:
        person = self._session.get(Object, person_id)
        if person is None or person.user_id != self._user_id:
            raise NotFoundError("person", person_id)
        if person.kind != PERSON_KIND:
            raise ValidationError("evidence target must be a person")
        return person

    def _require_active_person(self, person_id: UUID) -> Object:
        person = self._require_person(person_id)
        if not _person_is_active(person):
            raise ValidationError("evidence target must be an active person")
        return person

    def _require_source(self, source_object_id: UUID | None) -> None:
        if source_object_id is None:
            return
        source = self._session.get(Object, source_object_id)
        if source is None or source.user_id != self._user_id:
            raise NotFoundError("object", source_object_id)

    def _require_linked_identity(
        self,
        person_id: UUID,
        person_identity_id: UUID | None,
        identity: NormalizedPersonIdentity,
    ) -> None:
        if person_identity_id is None:
            return
        row = self._session.get(PersonIdentity, person_identity_id)
        if row is None or row.user_id != self._user_id:
            raise NotFoundError("person_identity", person_identity_id)
        if row.person_object_id != person_id:
            raise ValidationError("evidence identity belongs to another person")
        if row.state == REJECTED_STATE:
            raise ValidationError("evidence identity is not active")
        same = (
            row.provider == identity.provider
            and row.identity_type == identity.identity_type
            and row.realm == identity.realm
            and row.canonical_value == identity.canonical_value
        )
        if not same:
            raise ValidationError("evidence identity does not match the linked identity")

    def _name_matches(self, display_name: str) -> list[UUID]:
        people = self._session.scalars(
            select(Object).where(
                Object.user_id == self._user_id,
                Object.kind == PERSON_KIND,
                Object.state != REJECTED_STATE,
                object_is_active(),
            )
        )
        matched = [person.id for person in people if names_match(display_name, person.title)]
        displays = self._session.execute(
            select(PersonIdentity.person_object_id, PersonIdentity.display_value)
            .join(Object, Object.id == PersonIdentity.person_object_id)
            .where(
                PersonIdentity.user_id == self._user_id,
                PersonIdentity.state != REJECTED_STATE,
                PersonIdentity.display_value.is_not(None),
                Object.user_id == self._user_id,
                Object.kind == PERSON_KIND,
                Object.state != REJECTED_STATE,
                object_is_active(),
            )
        )
        for person_id, display_value in displays:
            if person_id not in matched and names_match(display_name, display_value):
                matched.append(person_id)
        return matched


def _person_is_active(person: Object) -> bool:
    return person.state != REJECTED_STATE and not is_object_hidden_from_active_reads(person)


def _bounded_key(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > _MAX_KEY_CHARS:
        raise ValidationError("person evidence provenance is malformed")
    return cleaned


def _bounded_explanation(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) > _MAX_EXPLANATION_CHARS:
        raise ValidationError("person evidence explanation is too long")
    return cleaned or None


def _safe_details(details: dict | None) -> dict:
    payload = details or {}
    if not isinstance(payload, dict):
        raise ValidationError("person evidence details are malformed")
    for key, value in payload.items():
        haystack = f"{key} {value}".casefold()
        if any(marker in haystack for marker in _SECRET_MARKERS):
            raise ValidationError("person evidence cannot store provider secrets")
    return payload
