"""Assisted promotion from stored direct contacts to an explicit Person.

Reads do not create People. Approval creates one Person and one exact identity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Object, PersonIdentity, PersonIdentityEvidence, PersonPromotionFeedback
from app.domain.object_visibility import object_is_active
from app.domain.person_assistant import (
    MAX_PERSON_SCAN_ROWS,
    PERSON_LOOKBACK_DAYS,
    parse_feedback_identity,
)
from app.domain.person_identity import NormalizedPersonIdentity, PersonIdentityInputError
from app.domain.person_promotion import (
    MAX_DIRECT_HITS,
    MAX_PROMOTION_CANDIDATES,
    MAX_SOURCE_PREVIEWS,
    MIN_DIRECT_HITS,
    REPEATED_DIRECT_CONTACT,
    direct_promotion_identity,
)
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PERSON_KIND, PersonIdentityService
from app.services.provenance import REJECTED_STATE, USER_ORIGIN

_COMMUNICATION_KINDS = ("email", "chat_message")
_SUPPRESSION = "suppression"
_ACTIVE = "active"
_RETRACTED = "retracted"
_PROMOTION_EXPLANATION = "explicit promotion of an unresolved direct contact"


@dataclass(frozen=True)
class PromotionCandidate:
    identity: NormalizedPersonIdentity
    display_value: str
    direct_hit_count: int
    latest_occurred_at: datetime | None
    sources: tuple[Object, ...]


@dataclass
class _Hit:
    identity: NormalizedPersonIdentity
    display_value: str
    count: int
    latest: datetime | None
    sources: list[Object]


class PersonPromotionService:
    def __init__(self, session: Session, user_id: UUID, *, now: datetime | None = None) -> None:
        self._session = session
        self._user_id = user_id
        self._now = now or datetime.now(UTC)
        self._people = PersonIdentityService(session, user_id)
        self._evidence = PersonEvidenceService(session, user_id)

    def overview(
        self, *, include_quarantined_telegram: bool = False
    ) -> tuple[list[dict], bool, list[dict]]:
        hits, truncated = self._hits(include_quarantined_telegram=include_quarantined_telegram)
        owned = self._owned_keys()
        suppressed = {self._key(row): row for row in self._active_feedback()}
        ranked = [
            self._candidate(item)
            for item in hits.values()
            if item.count >= MIN_DIRECT_HITS
            and self._key(item.identity) not in owned
            and self._key(item.identity) not in suppressed
        ]
        ranked.sort(key=self._rank)
        visible = ranked[:MAX_PROMOTION_CANDIDATES]
        return (
            [self._candidate_payload(item) for item in visible],
            truncated,
            [self._suppression_payload(row) for row in suppressed.values()],
        )

    def suppress(
        self, identity: NormalizedPersonIdentity, *, display_value: str | None = None
    ) -> PersonPromotionFeedback:
        existing = self._active_for(identity)
        if existing is not None:
            return existing
        if not display_value or display_value == identity.canonical_value:
            hits, _truncated = self._hits(include_quarantined_telegram=True)
            item = hits.get(self._key(identity))
            if item is not None:
                display_value = item.display_value
        label = _label(display_value or identity.display_value, identity.canonical_value)
        row = PersonPromotionFeedback(
            user_id=self._user_id,
            provider=identity.provider,
            identity_type=identity.identity_type,
            realm=identity.realm,
            canonical_value=identity.canonical_value,
            display_value=label,
            feedback_kind=_SUPPRESSION,
            state=_ACTIVE,
            origin=USER_ORIGIN,
            provenance_key=_provenance(identity),
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            found = self._active_for(identity)
            if found is None:
                raise
            return found
        return row

    def retract(self, identity: NormalizedPersonIdentity) -> PersonPromotionFeedback:
        row = self._active_for(identity)
        if row is None:
            raise NotFoundError("person_promotion_feedback", identity.canonical_value)
        row.state = _RETRACTED
        row.retracted_at = datetime.now(UTC)
        row.updated_at = row.retracted_at
        self._session.flush()
        return row

    def approve(self, identity: NormalizedPersonIdentity) -> Object:
        owner = self._people.resolve(identity)
        if owner is not None:
            if self._promotion_confirmation(owner.id, identity) is not None:
                return owner
            raise ConflictError("person identity is already bound")
        if self._confirmation_people(identity):
            raise ConflictError("person identity is already bound")
        if not self._eligible(identity):
            raise ValidationError("promotion candidate is not exposed")
        label = self._approval_label(identity)
        try:
            with self._session.begin_nested():
                person = self._people.create_person(label)
                attached = self._people.attach(person.id, identity)
                evidence = self._evidence.record_confirmation(
                    person.id,
                    identity,
                    _provenance(identity),
                    explanation=_PROMOTION_EXPLANATION,
                )
                if evidence.person_identity_id is None:
                    evidence.person_identity_id = attached.id
                    self._session.flush()
                return person
        except ConflictError:
            owner = self._people.resolve(identity)
            if owner is not None and self._promotion_confirmation(owner.id, identity) is not None:
                return owner
            raise ConflictError("person identity is already bound") from None

    def _eligible(self, identity: NormalizedPersonIdentity) -> bool:
        if self._key(identity) in self._owned_keys() or self._active_for(identity) is not None:
            return False
        hits, _truncated = self._hits(include_quarantined_telegram=True)
        item = hits.get(self._key(identity))
        return item is not None and item.count >= MIN_DIRECT_HITS

    def _hits(
        self, *, include_quarantined_telegram: bool
    ) -> tuple[dict[tuple[str, str, str, str], _Hit], bool]:
        stamp = func.coalesce(Object.occurred_at, Object.created_at)
        cutoff = self._now - timedelta(days=PERSON_LOOKBACK_DAYS)
        rows = list(
            self._session.scalars(
                select(Object)
                .where(
                    Object.user_id == self._user_id,
                    Object.kind.in_(_COMMUNICATION_KINDS),
                    Object.state != REJECTED_STATE,
                    object_is_active(),
                    stamp >= cutoff,
                )
                .order_by(stamp.desc(), Object.id)
                .limit(MAX_PERSON_SCAN_ROWS + 1)
            )
        )
        truncated = len(rows) > MAX_PERSON_SCAN_ROWS
        found: dict[tuple[str, str, str, str], _Hit] = {}
        for source in rows[:MAX_PERSON_SCAN_ROWS]:
            if source.provider == "telegram" and not include_quarantined_telegram:
                continue
            identity = direct_promotion_identity(source)
            if identity is None:
                continue
            key = self._key(identity)
            when = source.occurred_at or source.created_at
            current = found.get(key)
            if current is None:
                found[key] = _Hit(
                    identity,
                    _label(identity.display_value, identity.canonical_value),
                    1,
                    when,
                    [source],
                )
                continue
            current.count += 1
            if len(current.sources) < MAX_SOURCE_PREVIEWS:
                current.sources.append(source)
            if current.display_value == identity.canonical_value and identity.display_value:
                current.display_value = _label(identity.display_value, identity.canonical_value)
        return found, truncated

    def _approval_label(self, identity: NormalizedPersonIdentity) -> str:
        hits, _truncated = self._hits(include_quarantined_telegram=True)
        item = hits.get(self._key(identity))
        if item is not None:
            return item.display_value
        return _label(identity.display_value, identity.canonical_value)

    def _owned_keys(self) -> set[tuple[str, str, str, str]]:
        rows = self._session.scalars(
            select(PersonIdentity)
            .join(Object, Object.id == PersonIdentity.person_object_id)
            .where(
                PersonIdentity.user_id == self._user_id,
                PersonIdentity.state != REJECTED_STATE,
                Object.user_id == self._user_id,
                Object.kind == PERSON_KIND,
                Object.state != REJECTED_STATE,
                object_is_active(),
            )
        )
        return {(row.provider, row.identity_type, row.realm, row.canonical_value) for row in rows}

    def _active_feedback(self) -> list[PersonPromotionFeedback]:
        return list(
            self._session.scalars(
                select(PersonPromotionFeedback)
                .where(
                    PersonPromotionFeedback.user_id == self._user_id,
                    PersonPromotionFeedback.state == _ACTIVE,
                    PersonPromotionFeedback.feedback_kind == _SUPPRESSION,
                )
                .order_by(
                    PersonPromotionFeedback.provider,
                    PersonPromotionFeedback.identity_type,
                    PersonPromotionFeedback.realm,
                    PersonPromotionFeedback.canonical_value,
                )
            )
        )

    def _active_for(self, identity: NormalizedPersonIdentity) -> PersonPromotionFeedback | None:
        return self._session.scalar(
            select(PersonPromotionFeedback).where(
                PersonPromotionFeedback.user_id == self._user_id,
                PersonPromotionFeedback.state == _ACTIVE,
                PersonPromotionFeedback.provider == identity.provider,
                PersonPromotionFeedback.identity_type == identity.identity_type,
                PersonPromotionFeedback.realm == identity.realm,
                PersonPromotionFeedback.canonical_value == identity.canonical_value,
            )
        )

    def _promotion_confirmation(
        self, person_id: UUID, identity: NormalizedPersonIdentity
    ) -> PersonIdentityEvidence | None:
        return self._session.scalar(
            select(PersonIdentityEvidence).where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id == person_id,
                PersonIdentityEvidence.state == _ACTIVE,
                PersonIdentityEvidence.evidence_type == "user_confirmed",
                PersonIdentityEvidence.provenance_key == _provenance(identity),
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
            )
        )

    def _confirmation_people(self, identity: NormalizedPersonIdentity) -> list[UUID]:
        return list(
            self._session.scalars(
                select(PersonIdentityEvidence.person_object_id).where(
                    PersonIdentityEvidence.user_id == self._user_id,
                    PersonIdentityEvidence.state == _ACTIVE,
                    PersonIdentityEvidence.evidence_type == "user_confirmed",
                    PersonIdentityEvidence.provider == identity.provider,
                    PersonIdentityEvidence.identity_type == identity.identity_type,
                    PersonIdentityEvidence.realm == identity.realm,
                    PersonIdentityEvidence.canonical_value == identity.canonical_value,
                )
            )
        )

    def _candidate(self, item: _Hit) -> PromotionCandidate:
        return PromotionCandidate(
            identity=item.identity,
            display_value=item.display_value,
            direct_hit_count=min(item.count, MAX_DIRECT_HITS),
            latest_occurred_at=item.latest,
            sources=tuple(item.sources[:MAX_SOURCE_PREVIEWS]),
        )

    def _rank(self, item: PromotionCandidate) -> tuple:
        latest = item.latest_occurred_at or datetime.min.replace(tzinfo=UTC)
        identity = item.identity
        return (
            -item.direct_hit_count,
            -latest.timestamp(),
            identity.provider,
            identity.identity_type,
            identity.realm,
            identity.canonical_value,
        )

    def _candidate_payload(self, item: PromotionCandidate) -> dict:
        identity = item.identity
        return {
            "provider": identity.provider,
            "identity_type": identity.identity_type,
            "realm": identity.realm,
            "canonical_value": identity.canonical_value,
            "display_value": item.display_value,
            "direct_hit_count": item.direct_hit_count,
            "latest_occurred_at": item.latest_occurred_at,
            "reasons": [REPEATED_DIRECT_CONTACT],
            "sources": [_preview(source) for source in item.sources],
        }

    def _suppression_payload(self, row: PersonPromotionFeedback) -> dict:
        return {
            "provider": row.provider,
            "identity_type": row.identity_type,
            "realm": row.realm,
            "canonical_value": row.canonical_value,
            "display_value": row.display_value or row.canonical_value,
        }

    @staticmethod
    def _key(
        identity: NormalizedPersonIdentity | PersonPromotionFeedback,
    ) -> tuple[str, str, str, str]:
        return (identity.provider, identity.identity_type, identity.realm, identity.canonical_value)


def parse_promotion_identity(
    identity_type: str,
    provider: str,
    realm: str,
    canonical_value: str,
) -> NormalizedPersonIdentity:
    try:
        return parse_feedback_identity(identity_type, provider, realm, canonical_value)
    except PersonIdentityInputError as exc:
        raise ValidationError("identity tuple is malformed") from exc


def _provenance(identity: NormalizedPersonIdentity) -> str:
    raw = (
        f"{identity.provider}|{identity.identity_type}|{identity.realm}|{identity.canonical_value}"
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"graph_ui:promotion:{digest}"


def _label(display: str | None, canonical: str) -> str:
    text = (display or "").strip() or canonical.strip()
    return text[:200]


def _preview(source: Object) -> dict:
    return {
        "object_id": source.id,
        "kind": source.kind,
        "provider": source.provider,
        "title": source.title,
        "occurred_at": source.occurred_at,
    }
