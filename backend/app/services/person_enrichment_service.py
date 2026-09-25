"""Bounded identity-enrichment planning from stored facts.

This service does not call providers, directories, or models, and it does not
create People or merge them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Object, PersonIdentity, PersonIdentityEvidence
from app.domain.object_visibility import object_is_active
from app.domain.person_candidate_score import EXACT_IDENTIFIER, USER_CONFIRMED
from app.domain.person_enrichment import (
    ATTACH_EXACT,
    IGNORE_FOR_NOW,
    MAX_ENRICHMENT_CANDIDATES,
    MAX_ENRICHMENT_SCAN,
    MAX_SOURCE_REFS,
    NEEDS_CONFIRMATION,
    NEEDS_PROVIDER_LOOKUP,
    PROVIDER_CATEGORIES,
    RECORD_PROVIDER_EVIDENCE,
    PersonCoverage,
    PersonEnrichmentCandidate,
    PersonResolutionPlan,
    candidate_sort_key,
    provider_category,
)
from app.domain.person_identity import NormalizedPersonIdentity
from app.domain.person_identity_evidence import extract_person_identity_evidence
from app.domain.person_salience import FOCUS, KNOWN, WINDOW_DAYS
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PersonIdentityService
from app.services.person_salience_service import PersonSalienceService
from app.services.provenance import REJECTED_STATE

_COMMUNICATION_KINDS = ("email", "chat_message")
_DISPLAY_KEYS = ("author_display_name", "sender_display_name")


class PersonEnrichmentService:
    def __init__(self, session: Session, user_id: UUID, *, now: datetime | None = None) -> None:
        self._session = session
        self._user_id = user_id
        self._now = now or datetime.now(UTC)
        self._people = PersonIdentityService(session, user_id)
        self._evidence = PersonEvidenceService(session, user_id)
        self._salience = PersonSalienceService(session, user_id, now=self._now)

    def plan(self) -> PersonResolutionPlan:
        messages, scan_truncated = self._load_messages()
        salience = {item.person_id: item for item in self._salience.rank() if item.person_id}
        candidates: list[PersonEnrichmentCandidate] = []
        for message in messages:
            candidates.extend(self._candidates_from_message(message, salience))
        coverage = tuple(self._coverage(person_id, salience[person_id]) for person_id in salience)
        for person_id, item in salience.items():
            candidates.append(self._coverage_candidate(person_id, item, coverage))
        ordered = tuple(sorted(candidates, key=candidate_sort_key))
        capped = len(ordered) > MAX_ENRICHMENT_CANDIDATES
        truncated = scan_truncated or capped
        visible = ordered[:MAX_ENRICHMENT_CANDIDATES]
        if truncated:
            visible = tuple(self._with_truncated(item) for item in visible)
        return PersonResolutionPlan(visible, coverage, truncated)

    def _candidates_from_message(
        self,
        message: Object,
        salience: dict,
    ) -> list[PersonEnrichmentCandidate]:
        identities = extract_person_identity_evidence(message)
        if identities:
            found: list[PersonEnrichmentCandidate] = []
            for identity in identities:
                found.extend(self._exact_candidates(message, identity, salience))
            return found
        display = _display_name(message)
        if not display:
            return []
        matches = self._evidence.propose_candidates(None, display)
        if not matches:
            return [
                self._unresolved(message, None, IGNORE_FOR_NOW, ("public_or_unknown",), salience)
            ]
        return [
            PersonEnrichmentCandidate(
                person_id=match.person_id,
                identity=None,
                provider=message.provider or "",
                reasons=("display_name_similarity",),
                assessment_resolution=match.assessment.resolution,
                salience_tier=_tier(salience, match.person_id),
                salience_score=_score(salience, match.person_id),
                next_step=NEEDS_CONFIRMATION,
                source_object_ids=(message.id,),
                truncated=False,
            )
            for match in matches[:MAX_SOURCE_REFS]
        ]

    def _exact_candidates(
        self,
        message: Object,
        identity: NormalizedPersonIdentity,
        salience: dict,
    ) -> list[PersonEnrichmentCandidate]:
        owner = self._people.resolve(identity)
        confirmed_ids = self._confirmed_people(identity)
        if len(confirmed_ids) > 1:
            return self._confirmation_conflicts(message, identity, owner, confirmed_ids, salience)
        confirmed = confirmed_ids[0] if confirmed_ids else None
        if (
            owner is not None
            and self._evidence.is_rejected(owner.id, identity)
            and (confirmed is None or confirmed == owner.id)
        ):
            return [
                self._known(
                    owner.id,
                    identity,
                    message,
                    NEEDS_CONFIRMATION,
                    ("user_rejected",),
                    salience,
                )
            ]
        if owner is not None and (confirmed is None or confirmed == owner.id):
            self._record_exact(owner.id, identity, message.id)
            return [
                self._known(
                    owner.id,
                    identity,
                    message,
                    RECORD_PROVIDER_EVIDENCE,
                    ("exact_identity",),
                    salience,
                )
            ]
        if confirmed is not None and owner is None:
            self._people.attach(confirmed, identity)
            self._record_exact(confirmed, identity, message.id)
            return [
                self._known(
                    confirmed,
                    identity,
                    message,
                    ATTACH_EXACT,
                    ("explicit_confirmation",),
                    salience,
                )
            ]
        if owner is not None and confirmed is not None and confirmed != owner.id:
            return [
                self._known(
                    confirmed,
                    identity,
                    message,
                    NEEDS_CONFIRMATION,
                    ("identity_conflict",),
                    salience,
                )
            ]
        names = self._evidence.propose_candidates(identity, identity.display_value)
        if names:
            return [PersonEnrichmentCandidate(
                person_id=names[0].person_id,
                identity=identity,
                provider=identity.provider,
                reasons=("display_name_similarity",),
                assessment_resolution=names[0].assessment.resolution,
                salience_tier=_tier(salience, names[0].person_id),
                salience_score=_score(salience, names[0].person_id),
                next_step=NEEDS_CONFIRMATION,
                source_object_ids=(message.id,),
                truncated=False,
            )]
        step = NEEDS_PROVIDER_LOOKUP if _is_direct(message) else IGNORE_FOR_NOW
        reason = "direct_unresolved" if step == NEEDS_PROVIDER_LOOKUP else "public_or_unknown"
        return [self._unresolved(message, identity, step, (reason,), salience)]

    def _confirmation_conflicts(
        self,
        message: Object,
        identity: NormalizedPersonIdentity,
        owner: Object | None,
        confirmed_ids: tuple[UUID, ...],
        salience: dict,
    ) -> list[PersonEnrichmentCandidate]:
        reasons = ["multiple_user_confirmations"]
        if owner is not None:
            reasons.append("identity_conflict")
        visible = confirmed_ids[:MAX_SOURCE_REFS]
        hidden = len(confirmed_ids) > MAX_SOURCE_REFS
        return [
            PersonEnrichmentCandidate(
                person_id=person_id,
                identity=identity,
                provider=identity.provider,
                reasons=tuple(reasons),
                assessment_resolution=self._evidence.score(person_id, identity).resolution,
                salience_tier=_tier(salience, person_id),
                salience_score=_score(salience, person_id),
                next_step=NEEDS_CONFIRMATION,
                source_object_ids=(message.id,),
                truncated=hidden,
            )
            for person_id in visible
        ]

    def _coverage_candidate(
        self,
        person_id: UUID,
        item,
        coverage: tuple[PersonCoverage, ...],
    ) -> PersonEnrichmentCandidate:
        view = next(row for row in coverage if row.person_id == person_id)
        confirmed = self._person_has_confirmation(person_id)
        promote = item.tier in {FOCUS, KNOWN} or confirmed
        if view.missing and promote:
            reasons = ["incomplete_provider_coverage"]
            if confirmed:
                reasons.append("user_attention")
            step = NEEDS_PROVIDER_LOOKUP
        else:
            reasons = ["low_salience"]
            step = IGNORE_FOR_NOW
        return PersonEnrichmentCandidate(
            person_id=person_id,
            identity=None,
            provider="coverage",
            reasons=tuple(reasons),
            assessment_resolution=None,
            salience_tier=item.tier,
            salience_score=item.score,
            next_step=step,
            source_object_ids=(),
            truncated=False,
        )

    def _coverage(self, person_id: UUID, item) -> PersonCoverage:
        del item
        known = {
            category
            for row in self._evidence.effective_identities()
            if row.person_object_id == person_id
            and (category := provider_category(_identity_from_row(row))) is not None
        }
        missing = tuple(category for category in PROVIDER_CATEGORIES if category not in known)
        return PersonCoverage(person_id, tuple(sorted(known)), missing)

    def _confirmed_people(self, identity: NormalizedPersonIdentity) -> tuple[UUID, ...]:
        rows = self._session.scalars(
            select(PersonIdentityEvidence.person_object_id)
            .join(Object, Object.id == PersonIdentityEvidence.person_object_id)
            .where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type == USER_CONFIRMED,
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
                Object.user_id == self._user_id,
                Object.kind == "person",
                Object.state != REJECTED_STATE,
                object_is_active(),
            )
            .distinct()
        )
        return tuple(sorted(set(rows), key=str))

    def _person_has_confirmation(self, person_id: UUID) -> bool:
        row = self._session.scalar(
            select(PersonIdentityEvidence.id).where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id == person_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type == USER_CONFIRMED,
            )
        )
        return row is not None

    def _record_exact(self, person_id: UUID, identity: NormalizedPersonIdentity, source_id: UUID) -> None:
        self._evidence.record(
            person_id,
            identity,
            EXACT_IDENTIFIER,
            provenance_kind="provider_fact",
            provenance_key=f"source:{source_id}:{identity.identity_type}:{identity.canonical_value}",
            source_object_id=source_id,
            explanation="exact identity from stored communication",
        )

    def _load_messages(self) -> tuple[list[Object], bool]:
        cutoff = self._now - timedelta(days=WINDOW_DAYS)
        stamp = func.coalesce(Object.occurred_at, Object.created_at)
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
                .limit(MAX_ENRICHMENT_SCAN + 1)
            )
        )
        return rows[:MAX_ENRICHMENT_SCAN], len(rows) > MAX_ENRICHMENT_SCAN

    def _known(self, person_id, identity, message, step, reasons, salience) -> PersonEnrichmentCandidate:
        return PersonEnrichmentCandidate(
            person_id=person_id,
            identity=identity,
            provider=identity.provider,
            reasons=reasons,
            assessment_resolution=self._evidence.score(person_id, identity).resolution,
            salience_tier=_tier(salience, person_id),
            salience_score=_score(salience, person_id),
            next_step=step,
            source_object_ids=(message.id,),
            truncated=False,
        )

    def _unresolved(self, message, identity, step, reasons, salience) -> PersonEnrichmentCandidate:
        del salience
        return PersonEnrichmentCandidate(
            person_id=None,
            identity=identity,
            provider=(identity.provider if identity is not None else message.provider or ""),
            reasons=reasons,
            assessment_resolution=None,
            salience_tier=None,
            salience_score=None,
            next_step=step,
            source_object_ids=(message.id,),
            truncated=False,
        )

    def _with_truncated(self, candidate: PersonEnrichmentCandidate) -> PersonEnrichmentCandidate:
        return PersonEnrichmentCandidate(
            person_id=candidate.person_id,
            identity=candidate.identity,
            provider=candidate.provider,
            reasons=candidate.reasons,
            assessment_resolution=candidate.assessment_resolution,
            salience_tier=candidate.salience_tier,
            salience_score=candidate.salience_score,
            next_step=candidate.next_step,
            source_object_ids=candidate.source_object_ids,
            truncated=True,
        )


def _identity_from_row(row: PersonIdentity) -> NormalizedPersonIdentity:
    return NormalizedPersonIdentity(
        identity_type=row.identity_type,
        provider=row.provider,
        realm=row.realm,
        canonical_value=row.canonical_value,
        display_value=row.display_value,
    )


def _display_name(message: Object) -> str | None:
    metadata = message.metadata_ if isinstance(message.metadata_, dict) else {}
    for key in _DISPLAY_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_direct(message: Object) -> bool:
    metadata = message.metadata_ if isinstance(message.metadata_, dict) else {}
    if message.provider == "telegram" and metadata.get("transport") == "mtproto":
        return metadata.get("peer_kind") == "private"
    if message.provider == "teams":
        return metadata.get("chat_type") == "oneOnOne" and metadata.get("sender_kind") == "user"
    if message.provider == "mattermost":
        return str(metadata.get("channel_type") or "").upper() == "D"
    if message.provider in {"gmail", "yandex_mail"}:
        recipients = metadata.get("recipients")
        copied = metadata.get("cc")
        return isinstance(recipients, list) and len(recipients) == 1 and not copied
    return False


def _tier(salience: dict, person_id: UUID | None) -> str | None:
    item = salience.get(person_id) if person_id is not None else None
    return None if item is None else item.tier


def _score(salience: dict, person_id: UUID | None) -> int | None:
    item = salience.get(person_id) if person_id is not None else None
    return None if item is None else item.score
