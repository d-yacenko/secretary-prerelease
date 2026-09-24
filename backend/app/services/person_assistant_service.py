"""Read-only Person resolution and reversible identity feedback.

This service does not send messages, merge People, or call a provider or model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Object, PersonIdentity, PersonIdentityEvidence
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.person_assistant import (
    AMBIGUOUS,
    MAX_IDENTITIES_PER_PERSON,
    MAX_PERSON_CANDIDATES,
    MAX_PERSON_SCAN,
    NONE,
    PERSON_LOOKBACK_DAYS,
    RESOLVED,
    feedback_identity_key,
    parse_feedback_identity,
)
from app.domain.person_enrichment import provider_category
from app.domain.person_identity import (
    NormalizedPersonIdentity,
    PersonIdentityInputError,
    normalize_email,
)
from app.domain.person_identity_evidence import extract_person_identity_evidence
from app.domain.person_salience import communication_identity_keys
from app.domain.telegram_mtproto_ai import (
    telegram_mtproto_ai_enabled,
    telegram_mtproto_ai_predicate,
)
from app.services.errors import NotFoundError, ValidationError
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PERSON_KIND, PersonIdentityService
from app.services.person_salience_service import PersonSalienceService
from app.services.provenance import REJECTED_STATE
from app.tools.schemas import (
    FindPersonCommunicationsInput,
    FindPersonCommunicationsOutput,
    PersonCandidateOut,
    PersonCommunicationOut,
    PersonIdentityFeedbackInput,
    PersonIdentityFeedbackOutput,
    PersonIdentitySummary,
    ResolvePersonOutput,
)

_COMMUNICATION_KINDS = ("email", "chat_message")
_FEEDBACK_TYPES = ("user_confirmed", "user_rejected")


class PersonAssistantService:
    def __init__(self, session: Session, user_id: UUID, *, now: datetime | None = None) -> None:
        self._session = session
        self._user_id = user_id
        self._now = now or datetime.now(UTC)
        self._people = PersonIdentityService(session, user_id)
        self._evidence = PersonEvidenceService(session, user_id)
        self._salience = PersonSalienceService(session, user_id, now=self._now)

    def resolve(self, query: str) -> ResolvePersonOutput:
        text = query.strip()
        if not text:
            raise ValidationError("person query is required")
        exact = _exact_query(text)
        if exact is not None:
            return self._resolve_exact(exact)
        alias_ids = self._alias_people(text)
        if alias_ids:
            return self._finish(alias_ids, "alias", None)
        matches = self._evidence.propose_candidates(None, text)
        return self._finish([match.person_id for match in matches], "name_similarity", None)

    def find_communications(
        self, payload: FindPersonCommunicationsInput
    ) -> FindPersonCommunicationsOutput:
        person = self._require_active_person(payload.person_id)
        keys = {
            (row.identity_type, row.realm, row.canonical_value)
            for row in self._active_identity_rows(person.id)
        }
        matches, truncated = self._matching_messages(keys, payload)
        return FindPersonCommunicationsOutput(
            person_id=person.id,
            objects=[
                PersonCommunicationOut(
                    id=obj.id,
                    kind=obj.kind,
                    provider=obj.provider,
                    title=obj.title,
                    occurred_at=obj.occurred_at,
                )
                for obj in matches
            ],
            truncated=truncated,
        )

    def confirm_person_identity(
        self, payload: PersonIdentityFeedbackInput
    ) -> PersonIdentityFeedbackOutput:
        person, identity = self._feedback_target(payload)
        row = self._evidence.record_confirmation(
            person.id,
            identity,
            f"assistant:user_confirmed:{identity.canonical_value}",
            explanation="explicit assistant confirmation",
        )
        return _feedback_output(person.id, row)

    def reject_person_identity(
        self, payload: PersonIdentityFeedbackInput
    ) -> PersonIdentityFeedbackOutput:
        person, identity = self._feedback_target(payload)
        row = self._evidence.record_rejection(
            person.id,
            identity,
            f"assistant:user_rejected:{identity.canonical_value}",
            explanation="explicit assistant rejection",
        )
        return _feedback_output(person.id, row)

    def retract_person_identity_feedback(
        self, payload: PersonIdentityFeedbackInput
    ) -> PersonIdentityFeedbackOutput:
        person, identity = self._feedback_target(payload, require_exposed=False)
        rows = [
            row
            for row in self._evidence.history(person.id, identity)
            if row.state == "active" and row.evidence_type in _FEEDBACK_TYPES
        ]
        if not rows:
            raise ValidationError("no active identity feedback to retract")
        retracted = rows[0]
        for row in rows:
            self._evidence.retract(row.id)
            retracted = row
        return _feedback_output(person.id, retracted)

    def _resolve_exact(self, identity: NormalizedPersonIdentity) -> ResolvePersonOutput:
        owner = self._people.resolve(identity)
        if owner is not None:
            return self._finish([owner.id], "exact_identity", identity)
        holders = [
            person_id
            for person_id in self._evidence_people(identity)
            if not self._suppressed(person_id, identity)
        ]
        return self._finish(holders, "exact_identity", identity)

    def _finish(
        self,
        person_ids: list[UUID],
        reason: str,
        identity: NormalizedPersonIdentity | None,
    ) -> ResolvePersonOutput:
        unique = list(dict.fromkeys(person_ids))
        people = [person for person_id in unique if (person := self._active_person(person_id)) is not None]
        ranked = {item.person_id: item for item in self._salience.rank()}
        ordered = self._by_salience(people, ranked)
        truncated = len(ordered) > MAX_PERSON_CANDIDATES
        visible = ordered[:MAX_PERSON_CANDIDATES]
        candidates = [self._candidate(person, reason, identity, ranked) for person in visible]
        if len(candidates) == 1:
            state = RESOLVED
            chosen = candidates[0].person_id
        elif candidates:
            state = AMBIGUOUS
            chosen = None
        else:
            state = NONE
            chosen = None
        return ResolvePersonOutput(
            state=state,
            person_id=chosen,
            candidates=candidates,
            truncated=truncated,
        )

    def _candidate(
        self,
        person: Object,
        reason: str,
        identity: NormalizedPersonIdentity | None,
        ranked: dict,
    ) -> PersonCandidateOut:
        item = ranked.get(person.id)
        assessment = None
        if identity is not None:
            assessment = self._evidence.score(person.id, identity).resolution
        return PersonCandidateOut(
            person_id=person.id,
            title=person.title or "",
            identities=self._summaries(person.id),
            assessment_resolution=assessment,
            reasons=(reason,),
            salience_tier=None if item is None else item.tier,
            salience_score=None if item is None else item.score,
        )

    def _summaries(self, person_id: UUID) -> list[PersonIdentitySummary]:
        summaries: list[PersonIdentitySummary] = []
        seen: set[tuple[str, str, str, str]] = set()
        for identity in self._exposed_identities(person_id):
            key = feedback_identity_key(identity)
            if key in seen:
                continue
            category = provider_category(identity)
            if category is None:
                continue
            if category == "telegram" and not telegram_mtproto_ai_enabled():
                continue
            seen.add(key)
            summaries.append(
                PersonIdentitySummary(
                    category=category,
                    identity_type=identity.identity_type,
                    provider=identity.provider,
                    realm=identity.realm,
                    canonical_value=identity.canonical_value,
                    display_value=identity.display_value,
                )
            )
            if len(summaries) >= MAX_IDENTITIES_PER_PERSON:
                break
        return summaries

    def _exposed_identities(self, person_id: UUID) -> list[NormalizedPersonIdentity]:
        found: list[NormalizedPersonIdentity] = []
        for row in self._active_identity_rows(person_id):
            identity = _identity_from_row(row)
            if not self._suppressed(person_id, identity):
                found.append(identity)
        for row in self._evidence_rows(person_id):
            if row.evidence_type == "user_rejected":
                continue
            identity = _identity_from_evidence(row)
            if self._suppressed(person_id, identity):
                continue
            found.append(identity)
        return found

    def _feedback_target(
        self,
        payload: PersonIdentityFeedbackInput,
        *,
        require_exposed: bool = True,
    ) -> tuple[Object, NormalizedPersonIdentity]:
        person = self._require_active_person(payload.person_id)
        try:
            identity = parse_feedback_identity(
                payload.identity_type,
                payload.provider,
                payload.realm,
                payload.canonical_value,
            )
        except PersonIdentityInputError as exc:
            raise ValidationError("identity tuple is malformed") from exc
        if require_exposed and not self._is_exposed(person.id, identity):
            raise ValidationError("person identity was not exposed as a candidate")
        return person, identity

    def _is_exposed(self, person_id: UUID, identity: NormalizedPersonIdentity) -> bool:
        wanted = feedback_identity_key(identity)
        return any(feedback_identity_key(item) == wanted for item in self._exposed_identities(person_id))

    def _suppressed(self, person_id: UUID, identity: NormalizedPersonIdentity) -> bool:
        row = self._session.scalar(
            select(PersonIdentityEvidence.id).where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id == person_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type == "user_rejected",
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
            )
        )
        return row is not None

    def _matching_messages(
        self,
        keys: set[tuple[str, str, str]],
        payload: FindPersonCommunicationsInput,
    ) -> tuple[list[Object], bool]:
        if not keys:
            return [], False
        cutoff = payload.occurred_from or (self._now - timedelta(days=PERSON_LOOKBACK_DAYS))
        stamp = func.coalesce(Object.occurred_at, Object.created_at)
        query = select(Object).where(
            Object.user_id == self._user_id,
            Object.kind.in_(_COMMUNICATION_KINDS),
            Object.state != REJECTED_STATE,
            object_is_active(),
            stamp >= cutoff,
            telegram_mtproto_ai_predicate(),
        )
        if payload.occurred_to is not None:
            query = query.where(stamp <= payload.occurred_to)
        if payload.provider:
            query = query.where(Object.provider == payload.provider)
        rows = list(
            self._session.scalars(
                query.order_by(stamp.desc(), Object.id).limit(MAX_PERSON_SCAN + 1)
            )
        )
        scan_truncated = len(rows) > MAX_PERSON_SCAN
        matched: list[Object] = []
        for obj in rows[:MAX_PERSON_SCAN]:
            if not _message_matches(obj, keys, payload.direction):
                continue
            matched.append(obj)
            if len(matched) > payload.limit:
                break
        truncated = scan_truncated or len(matched) > payload.limit
        return matched[: payload.limit], truncated

    def _by_salience(self, people: list[Object], ranked: dict) -> list[Object]:
        def sort_key(person: Object) -> tuple:
            item = ranked.get(person.id)
            score = item.score if item is not None else 0
            return (-score, str(person.id))

        return sorted(people, key=sort_key)

    def _alias_people(self, query: str) -> list[UUID]:
        folded = query.casefold()
        people = self._session.scalars(
            select(Object).where(
                Object.user_id == self._user_id,
                Object.kind == PERSON_KIND,
                Object.state != REJECTED_STATE,
                object_is_active(),
            )
        )
        found = [person.id for person in people if (person.title or "").casefold() == folded]
        displays = self._session.execute(
            select(PersonIdentity.person_object_id, PersonIdentity.display_value)
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
        for person_id, display in displays:
            if isinstance(display, str) and display.casefold() == folded and person_id not in found:
                found.append(person_id)
        return found

    def _evidence_people(self, identity: NormalizedPersonIdentity) -> list[UUID]:
        rows = self._session.scalars(
            select(PersonIdentityEvidence.person_object_id)
            .join(Object, Object.id == PersonIdentityEvidence.person_object_id)
            .where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
                PersonIdentityEvidence.evidence_type != "user_rejected",
                Object.user_id == self._user_id,
                Object.kind == PERSON_KIND,
                Object.state != REJECTED_STATE,
                object_is_active(),
            )
            .distinct()
        )
        return list(rows)

    def _active_identity_rows(self, person_id: UUID) -> list[PersonIdentity]:
        return list(
            self._session.scalars(
                select(PersonIdentity).where(
                    PersonIdentity.user_id == self._user_id,
                    PersonIdentity.person_object_id == person_id,
                    PersonIdentity.state != REJECTED_STATE,
                )
            )
        )

    def _evidence_rows(self, person_id: UUID) -> list[PersonIdentityEvidence]:
        return list(
            self._session.scalars(
                select(PersonIdentityEvidence).where(
                    PersonIdentityEvidence.user_id == self._user_id,
                    PersonIdentityEvidence.person_object_id == person_id,
                    PersonIdentityEvidence.state == "active",
                )
            )
        )

    def _active_person(self, person_id: UUID) -> Object | None:
        person = self._session.get(Object, person_id)
        if person is None or person.user_id != self._user_id or person.kind != PERSON_KIND:
            return None
        if person.state == REJECTED_STATE or is_object_hidden_from_active_reads(person):
            return None
        return person

    def _require_active_person(self, person_id: UUID) -> Object:
        person = self._active_person(person_id)
        if person is None:
            raise NotFoundError("person", person_id)
        return person


def _exact_query(query: str) -> NormalizedPersonIdentity | None:
    if "@" not in query:
        return None
    try:
        return normalize_email(query)
    except PersonIdentityInputError:
        return None


def _identity_from_row(row: PersonIdentity) -> NormalizedPersonIdentity:
    return NormalizedPersonIdentity(
        identity_type=row.identity_type,
        provider=row.provider,
        realm=row.realm,
        canonical_value=row.canonical_value,
        display_value=row.display_value,
    )


def _identity_from_evidence(row: PersonIdentityEvidence) -> NormalizedPersonIdentity:
    return NormalizedPersonIdentity(
        identity_type=row.identity_type,
        provider=row.provider,
        realm=row.realm,
        canonical_value=row.canonical_value,
        display_value=None,
    )


def _message_matches(obj: Object, keys: set[tuple[str, str, str]], direction: str | None) -> bool:
    metadata = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    extracted = {
        (item.identity_type, item.realm, item.canonical_value)
        for item in extract_person_identity_evidence(obj)
    }
    if not extracted:
        extracted = set(communication_identity_keys(provider=obj.provider, metadata=metadata))
    if not extracted.intersection(keys):
        return False
    if direction is None:
        return True
    return _direction(obj) == direction


def _direction(obj: Object) -> str | None:
    metadata = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    value = metadata.get("direction")
    if value in {"inbound", "outbound"}:
        return value
    if obj.provider != "gmail":
        return None
    labels = {str(label).upper() for label in metadata.get("labels") or []}
    if "SENT" in labels and not ({"INBOX", "UNREAD"} & labels):
        return "outbound"
    if ({"INBOX", "UNREAD"} & labels) and "SENT" not in labels:
        return "inbound"
    return None


def _feedback_output(person_id: UUID, row: PersonIdentityEvidence) -> PersonIdentityFeedbackOutput:
    return PersonIdentityFeedbackOutput(
        person_id=person_id,
        evidence_id=row.id,
        evidence_type=row.evidence_type,
        state=row.state,
    )
