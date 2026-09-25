"""Read-only Person resolution and reversible identity feedback.

This service does not send messages, merge People, or call a provider or model.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Object, PersonIdentity, PersonIdentityEvidence
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.person_assistant import (
    AMBIGUOUS,
    MAX_IDENTITIES_PER_PERSON,
    MAX_PERSON_CANDIDATES,
    MAX_PERSON_ROUTES,
    MAX_PERSON_SCAN_ROWS,
    NONE,
    PERSON_LOOKBACK_DAYS,
    PERSON_SCAN_CHUNK,
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
from app.domain.person_salience import (
    _email_address,
    _email_audience,
    _email_direction,
    _positive_id,
    _text,
)
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
    FindPersonIdentityCandidatesOutput,
    ListPersonRoutesInput,
    ListPersonRoutesOutput,
    PersonCandidateOut,
    PersonCommunicationOut,
    PersonIdentityFeedbackInput,
    PersonIdentityFeedbackOutput,
    PersonIdentitySummary,
    PersonRouteOut,
    PersonSourceCandidateOut,
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
            return self._finish(alias_ids, ("alias",), None)
        matches = self._evidence.propose_candidates(None, text)
        return self._finish([match.person_id for match in matches], ("name_similarity",), None)

    def find_communications(
        self, payload: FindPersonCommunicationsInput
    ) -> FindPersonCommunicationsOutput:
        person = self._require_active_person(payload.person_id)
        keys = self._effective_keys(person.id)
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

    def find_identity_candidates(
        self,
        person_id: UUID,
        *,
        include_quarantined_telegram: bool = False,
    ) -> FindPersonIdentityCandidatesOutput:
        person = self._require_active_person(person_id)
        grouped: dict[tuple[str, str, str, str], list] = {}
        candidates: list[PersonSourceCandidateOut] = []
        truncated = False
        completed = False
        saw_row = False
        for chunk, scope_complete in self._message_chunks(
            None,
            apply_telegram_ai_gate=not include_quarantined_telegram,
        ):
            saw_row = True
            for message in chunk:
                for identity in extract_person_identity_evidence(message):
                    if (
                        provider_category(identity) == "telegram"
                        and not include_quarantined_telegram
                        and not telegram_mtproto_ai_enabled()
                    ):
                        continue
                    if include_quarantined_telegram:
                        identity = _ui_telegram_display(message, identity)
                    if self._suppressed(person.id, identity):
                        continue
                    grouped.setdefault(feedback_identity_key(identity), []).append((message, identity))
            candidates = self._source_candidates(person.id, grouped)
            if scope_complete:
                completed = True
                break
            if len(candidates) >= MAX_PERSON_CANDIDATES:
                truncated = True
                break
        if saw_row and not completed:
            truncated = True
        overflow = len(candidates) > MAX_PERSON_CANDIDATES
        return FindPersonIdentityCandidatesOutput(
            person_id=person.id,
            candidates=candidates[:MAX_PERSON_CANDIDATES],
            truncated=truncated or overflow,
        )

    def list_routes(
        self,
        payload: ListPersonRoutesInput,
        *,
        include_quarantined_telegram: bool = False,
    ) -> ListPersonRoutesOutput:
        person = self._require_active_person(payload.person_id)
        category = _route_category(payload.provider)
        routes = self._email_routes(person.id)
        chat_routes, truncated = self._chat_routes(
            person.id,
            include_quarantined_telegram=include_quarantined_telegram,
        )
        routes.extend(chat_routes)
        if category is not None:
            routes = [route for route in routes if route.provider == category]
        routes.sort(key=_route_sort_key)
        overflow = len(routes) > MAX_PERSON_ROUTES
        visible = routes[:MAX_PERSON_ROUTES]
        return ListPersonRoutesOutput(
            person_id=person.id,
            routes=visible,
            ambiguous=len(visible) > 1,
            truncated=truncated or overflow,
        )

    def record_route_choice(
        self, person_id: UUID, route_key: str
    ) -> PersonIdentityFeedbackOutput:
        person = self._require_active_person(person_id)
        category = _category_from_route_key(route_key)
        listed = self.list_routes(
            ListPersonRoutesInput(person_id=person.id, provider=category)
        )
        match = next((route for route in listed.routes if route.route_key == route_key), None)
        if match is None:
            raise ValidationError("person route was not exposed")
        identity = _identity_from_summary(match.identity)
        row = self._evidence.record_route_choice(
            person.id,
            identity,
            _route_choice_provenance(route_key),
            explanation="explicit assistant route choice",
        )
        return _feedback_output(person.id, row)

    def assert_email_route(self, person_id: UUID, recipients: list[str] | None) -> None:
        person = self._require_active_person(person_id)
        if recipients is None or len(recipients) != 1:
            raise ValidationError("person email route requires one recipient")
        try:
            identity = normalize_email(recipients[0])
        except PersonIdentityInputError as exc:
            raise ValidationError("person email route is not effective") from exc
        if not self._email_is_effective(person.id, identity):
            raise ValidationError("person email route is not effective")
        owner = self._people.resolve(identity)
        if owner is None or owner.id != person.id:
            raise ValidationError("person email route is not effective")
        others = [
            confirmed
            for confirmed in self._confirmation_people(identity)
            if confirmed != person.id and not self._suppressed(confirmed, identity)
        ]
        if others:
            raise ValidationError("person email route is conflicted")

    def assert_chat_anchor(self, person_id: UUID, anchor_id: UUID | None) -> None:
        person = self._require_active_person(person_id)
        if anchor_id is None:
            raise ValidationError("person chat route requires an anchor")
        obj = self._session.get(Object, anchor_id)
        if obj is None or obj.user_id != self._user_id or obj.kind != "chat_message":
            raise ValidationError("person chat route is not effective")
        if obj.state == REJECTED_STATE or is_object_hidden_from_active_reads(obj):
            raise ValidationError("person chat route is not effective")
        keys = self._effective_keys(person.id)
        if not _chat_anchor_is_effective(obj, keys):
            raise ValidationError("person chat route is not effective")

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
        owner_rejected = owner is not None and self._suppressed(owner.id, identity)
        confirmed = [
            person_id
            for person_id in self._confirmation_people(identity)
            if not self._suppressed(person_id, identity)
        ]
        if len(confirmed) > 1:
            reasons = ["multiple_user_confirmations"]
            people = list(confirmed)
            if owner is not None and not owner_rejected and owner.id not in people:
                people.append(owner.id)
            if owner is not None:
                reasons.append("identity_conflict")
            return self._finish(people, tuple(reasons), identity)
        if owner is not None and not owner_rejected:
            if confirmed and confirmed[0] != owner.id:
                return self._finish([owner.id, confirmed[0]], ("identity_conflict",), identity)
            return self._finish([owner.id], ("exact_identity",), identity)
        if owner_rejected and confirmed:
            return self._finish(confirmed, ("identity_conflict",), identity)
        if owner_rejected:
            return self._finish([], ("user_rejected",), identity)
        holders = [
            person_id
            for person_id in self._evidence_people(identity)
            if not self._suppressed(person_id, identity)
        ]
        return self._finish(holders, ("exact_identity",), identity)

    def _finish(
        self,
        person_ids: list[UUID],
        reasons: tuple[str, ...],
        identity: NormalizedPersonIdentity | None,
    ) -> ResolvePersonOutput:
        unique = list(dict.fromkeys(person_ids))
        people = [person for person_id in unique if (person := self._active_person(person_id)) is not None]
        ranked = {item.person_id: item for item in self._salience.rank()}
        ordered = self._by_salience(people, ranked)
        truncated = len(ordered) > MAX_PERSON_CANDIDATES
        visible = ordered[:MAX_PERSON_CANDIDATES]
        candidates = [self._candidate(person, reasons, identity, ranked) for person in visible]
        conflict = "identity_conflict" in reasons or "multiple_user_confirmations" in reasons
        if len(candidates) == 1 and not conflict:
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
        reasons: tuple[str, ...],
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
            reasons=reasons,
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
        if any(feedback_identity_key(item) == wanted for item in self._exposed_identities(person_id)):
            return True
        if any(feedback_identity_key(_identity_from_row(row)) == wanted for row in self._active_identity_rows(person_id)):
            return True
        if any(
            feedback_identity_key(_identity_from_evidence(row)) == wanted
            for row in self._evidence_rows(person_id)
        ):
            return True
        page = self.find_identity_candidates(person_id)
        return any(
            item.confirmable and feedback_identity_key(_identity_from_summary(item.identity)) == wanted
            for item in page.candidates
        )

    def _suppressed(self, person_id: UUID, identity: NormalizedPersonIdentity) -> bool:
        return self._evidence.is_rejected(person_id, identity)

    def _effective_keys(self, person_id: UUID) -> set[tuple[str, str, str]]:
        keys: set[tuple[str, str, str]] = set()
        for row in self._active_identity_rows(person_id):
            identity = _identity_from_row(row)
            if self._suppressed(person_id, identity):
                continue
            keys.add((identity.identity_type, identity.realm, identity.canonical_value))
        return keys

    def _email_is_effective(self, person_id: UUID, identity: NormalizedPersonIdentity) -> bool:
        for row in self._evidence.effective_identities():
            if row.person_object_id != person_id:
                continue
            if (
                row.identity_type == identity.identity_type
                and row.provider == identity.provider
                and row.realm == identity.realm
                and row.canonical_value == identity.canonical_value
            ):
                return True
        return False

    def _email_routes(self, person_id: UUID) -> list[PersonRouteOut]:
        routes: list[PersonRouteOut] = []
        for row in self._evidence.effective_identities():
            if row.person_object_id != person_id or row.identity_type != "email":
                continue
            identity = _identity_from_row(row)
            routes.append(
                self._route_out(
                    person_id=person_id,
                    route_key=f"email:{identity.canonical_value}",
                    route_kind="email",
                    provider="email",
                    label=identity.canonical_value,
                    identity=identity,
                    anchor=None,
                    conversation_label=None,
                    last_used_at=None,
                )
            )
        return routes

    def _chat_routes(
        self,
        person_id: UUID,
        *,
        include_quarantined_telegram: bool = False,
    ) -> tuple[list[PersonRouteOut], bool]:
        keys = self._effective_keys(person_id)
        identities = {
            (row.identity_type, row.realm, row.canonical_value): _identity_from_row(row)
            for row in self._evidence.effective_identities()
            if row.person_object_id == person_id
        }
        newest: dict[tuple[str, str, str], Object] = {}
        inbound: dict[tuple[str, str, str], Object] = {}
        chosen: dict[tuple[str, str, str], NormalizedPersonIdentity] = {}
        truncated = False
        completed = False
        saw_row = False
        for chunk, scope_complete in self._message_chunks(
            None,
            apply_telegram_ai_gate=not include_quarantined_telegram,
        ):
            saw_row = True
            for obj in chunk:
                observed = _observe_chat(obj, keys, identities)
                if observed is None:
                    continue
                conv_key, identity = observed
                newest.setdefault(conv_key, obj)
                if identity is not None:
                    chosen[conv_key] = identity
                    inbound.setdefault(conv_key, obj)
            if scope_complete:
                completed = True
                break
        if saw_row and not completed:
            truncated = True
        routes: list[PersonRouteOut] = []
        for conv_key, identity in chosen.items():
            obj = inbound.get(conv_key, newest[conv_key])
            routes.append(
                self._route_out(
                    person_id=person_id,
                    route_key=_chat_route_key(conv_key),
                    route_kind="chat",
                    provider=conv_key[0],
                    label=_conversation_label(obj) or identity.canonical_value,
                    identity=identity,
                    anchor=obj,
                    conversation_label=_conversation_label(obj),
                    last_used_at=obj.occurred_at,
                )
            )
        return routes, truncated

    def _route_out(
        self,
        *,
        person_id: UUID,
        route_key: str,
        route_kind: str,
        provider: str,
        label: str,
        identity: NormalizedPersonIdentity,
        anchor: Object | None,
        conversation_label: str | None,
        last_used_at: datetime | None,
    ) -> PersonRouteOut:
        chosen = self._has_route_choice(person_id, identity, route_key)
        reasons = ["exact_identity"]
        if chosen:
            reasons.append("user_route_choice")
        return PersonRouteOut(
            route_key=route_key,
            route_kind=route_kind,  # type: ignore[arg-type]
            provider=provider,
            label=label,
            identity=_summary(identity),
            anchor_object_id=None if anchor is None else anchor.id,
            conversation_label=conversation_label,
            last_used_at=last_used_at,
            has_route_choice=chosen,
            reasons=tuple(reasons),
        )

    def _has_route_choice(
        self, person_id: UUID, identity: NormalizedPersonIdentity, route_key: str
    ) -> bool:
        row = self._session.scalar(
            select(PersonIdentityEvidence.id).where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id == person_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type == "user_route_choice",
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
                PersonIdentityEvidence.provenance_key == _route_choice_provenance(route_key),
            )
        )
        return row is not None

    def _source_candidates(
        self,
        person_id: UUID,
        grouped: dict[tuple[str, str, str, str], list],
    ) -> list[PersonSourceCandidateOut]:
        candidates: list[PersonSourceCandidateOut] = []
        for _key, rows in sorted(grouped.items(), key=lambda item: item[0]):
            identity = rows[0][1]
            owner = self._people.resolve(identity)
            if owner is not None and owner.id == person_id:
                continue
            source_ids = tuple(message.id for message, _identity in rows[:3])
            if owner is not None and owner.id != person_id:
                candidates.append(
                    PersonSourceCandidateOut(
                        confirmable=False,
                        reasons=("identity_conflict",),
                        assessment_resolution=self._evidence.score(person_id, identity).resolution,
                        identity=_summary(identity),
                        source_object_ids=source_ids,
                    )
                )
                continue
            proposals = self._evidence.propose_candidates(identity, identity.display_value)
            matched = next((item for item in proposals if item.person_id == person_id), None)
            if matched is None:
                continue
            candidates.append(
                PersonSourceCandidateOut(
                    confirmable=True,
                    reasons=(matched.reason,),
                    assessment_resolution=matched.assessment.resolution,
                    identity=_summary(identity),
                    source_object_ids=source_ids,
                )
            )
        return candidates

    def _matching_messages(
        self,
        keys: set[tuple[str, str, str]],
        payload: FindPersonCommunicationsInput,
    ) -> tuple[list[Object], bool]:
        if not keys:
            return [], False
        anchors: set[tuple[str, str, str]] = set()
        pending: list[Object] = []
        matched: list[Object] = []
        saw_row = False
        for chunk, scope_complete in self._message_chunks(payload):
            saw_row = True
            for index, obj in enumerate(chunk):
                _collect_match(obj, keys, anchors, pending, matched, payload.direction)
                if len(matched) >= payload.limit:
                    more = index + 1 < len(chunk) or not scope_complete or len(matched) > payload.limit
                    return _newest_first(matched)[: payload.limit], more
            if scope_complete:
                return _newest_first(matched)[: payload.limit], False
        return _newest_first(matched)[: payload.limit], saw_row

    def _message_chunks(
        self,
        payload: FindPersonCommunicationsInput | None,
        *,
        apply_telegram_ai_gate: bool = True,
    ):
        cutoff = self._now - timedelta(days=PERSON_LOOKBACK_DAYS)
        stamp = func.coalesce(Object.occurred_at, Object.created_at)
        examined = 0
        cursor_stamp = None
        cursor_id = None
        while examined < MAX_PERSON_SCAN_ROWS:
            page_limit = min(PERSON_SCAN_CHUNK, MAX_PERSON_SCAN_ROWS - examined)
            query = select(Object).where(
                Object.user_id == self._user_id,
                Object.kind.in_(_COMMUNICATION_KINDS),
                Object.state != REJECTED_STATE,
                object_is_active(),
                stamp >= cutoff,
            )
            if apply_telegram_ai_gate:
                query = query.where(telegram_mtproto_ai_predicate())
            if payload is not None and payload.occurred_from is not None:
                query = query.where(stamp >= payload.occurred_from)
            if payload is not None and payload.occurred_to is not None:
                query = query.where(stamp <= payload.occurred_to)
            if payload is not None and payload.provider:
                query = query.where(Object.provider == payload.provider)
            if cursor_id is not None:
                query = query.where(
                    or_(
                        stamp < cursor_stamp,
                        and_(stamp == cursor_stamp, Object.id > cursor_id),
                    )
                )
            rows = list(
                self._session.scalars(query.order_by(stamp.desc(), Object.id).limit(page_limit))
            )
            if not rows:
                return
            examined += len(rows)
            scope_complete = len(rows) < page_limit
            if not scope_complete and examined < MAX_PERSON_SCAN_ROWS:
                last = rows[-1]
                cursor_stamp = last.occurred_at or last.created_at
                cursor_id = last.id
                continue_query = query.where(
                    or_(
                        stamp < cursor_stamp,
                        and_(stamp == cursor_stamp, Object.id > cursor_id),
                    )
                )
                follower = self._session.scalar(continue_query.order_by(stamp.desc(), Object.id).limit(1))
                scope_complete = follower is None
            yield rows, scope_complete
            if scope_complete or examined >= MAX_PERSON_SCAN_ROWS:
                return
            last = rows[-1]
            cursor_stamp = last.occurred_at or last.created_at
            cursor_id = last.id

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
        for row in self._evidence.effective_identities():
            display = row.display_value
            if isinstance(display, str) and display.casefold() == folded and row.person_object_id not in found:
                found.append(row.person_object_id)
        return found

    def _confirmation_people(self, identity: NormalizedPersonIdentity) -> list[UUID]:
        rows = self._session.scalars(
            select(PersonIdentityEvidence.person_object_id)
            .join(Object, Object.id == PersonIdentityEvidence.person_object_id)
            .where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type == "user_confirmed",
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
                Object.user_id == self._user_id,
                Object.kind == PERSON_KIND,
                Object.state != REJECTED_STATE,
                object_is_active(),
            )
            .distinct()
        )
        return list(rows)

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


def _route_choice_provenance(route_key: str) -> str:
    return f"assistant:user_route_choice:{route_key}"


def _category_from_route_key(route_key: str) -> str:
    prefix, separator, rest = route_key.partition(":")
    if separator and rest and prefix in {"email", "mattermost", "teams", "telegram"}:
        return prefix
    raise ValidationError("person route was not exposed")


def _route_category(provider: str | None) -> str | None:
    if provider is None or not provider.strip():
        return None
    folded = provider.strip().casefold()
    if folded in {"email", "gmail", "google", "yandex", "yandex_mail"}:
        return "email"
    if folded in {"mattermost", "teams", "telegram"}:
        return folded
    raise ValidationError("person route provider is unknown")


def _route_sort_key(route: PersonRouteOut) -> tuple:
    stamp = route.last_used_at or datetime(1970, 1, 1, tzinfo=UTC)
    return (not route.has_route_choice, -stamp.timestamp(), route.route_key)


def _chat_route_key(conv_key: tuple[str, str, str]) -> str:
    return ":".join(conv_key)


def _conversation_label(obj: Object) -> str | None:
    metadata = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    for field in ("channel_display_name", "peer_title", "chat_display_title"):
        value = _text(metadata.get(field))
        if value:
            return value[:120]
    title = _text(obj.title)
    return None if title is None else title[:120]


def _identity_for(
    identities: dict[tuple[str, str, str], NormalizedPersonIdentity],
    identity_type: str,
    realm: str,
    canonical: str,
) -> NormalizedPersonIdentity | None:
    return identities.get((identity_type, realm, canonical))


def _extracted_identity(
    obj: Object,
    identities: dict[tuple[str, str, str], NormalizedPersonIdentity],
) -> NormalizedPersonIdentity | None:
    for item in extract_person_identity_evidence(obj):
        found = identities.get((item.identity_type, item.realm, item.canonical_value))
        if found is not None:
            return found
    return None


def _ui_telegram_display(obj: Object, identity: NormalizedPersonIdentity) -> NormalizedPersonIdentity:
    """First-party reads may use a stored private-chat label as display text.

    Model-facing discovery does not call this. Group and channel messages stay unlabeled.
    """
    if identity.display_value or provider_category(identity) != "telegram":
        return identity
    metadata = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    if _text(metadata.get("peer_kind")) != "private":
        return identity
    display = _text(metadata.get("sender_display_name")) or _text(metadata.get("peer_title"))
    if display is None:
        return identity
    return replace(identity, display_value=display[:120])


def _observe_chat(
    obj: Object,
    keys: set[tuple[str, str, str]],
    identities: dict[tuple[str, str, str], NormalizedPersonIdentity],
) -> tuple[tuple[str, str, str], NormalizedPersonIdentity | None] | None:
    metadata = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    if obj.provider == "telegram" and metadata.get("transport") == "mtproto":
        if _text(metadata.get("peer_kind")) != "private":
            return None
        role = _direct_role(obj, keys)
        if role not in {"inbound", "outbound"}:
            return None
        realm = _text(metadata.get("account_id")) or ""
        canonical = _positive_id(metadata.get("peer_id")) if role == "outbound" else _positive_id(
            metadata.get("sender_peer_id")
        )
        if not realm or not canonical:
            return None
        return (("telegram", realm, canonical), _identity_for(identities, "telegram_user_id", realm, canonical))
    conv = _conversation_key(obj)
    if conv is None:
        return None
    if _direct_role(obj, keys) == "inbound":
        return (conv, _extracted_identity(obj, identities))
    if _stored_direction(obj) == "outbound":
        return (conv, None)
    return None


def _chat_anchor_is_effective(obj: Object, keys: set[tuple[str, str, str]]) -> bool:
    metadata = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    if obj.provider == "telegram" and metadata.get("transport") == "mtproto":
        if _text(metadata.get("peer_kind")) != "private":
            return False
        return _direct_role(obj, keys) in {"inbound", "outbound"}
    if _conversation_key(obj) is None:
        return False
    return _direct_role(obj, keys) == "inbound"


def _summary(identity: NormalizedPersonIdentity) -> PersonIdentitySummary:
    return PersonIdentitySummary(
        category=provider_category(identity) or "",
        identity_type=identity.identity_type,
        provider=identity.provider,
        realm=identity.realm,
        canonical_value=identity.canonical_value,
        display_value=identity.display_value,
    )


def _identity_from_summary(summary: PersonIdentitySummary) -> NormalizedPersonIdentity:
    return NormalizedPersonIdentity(
        identity_type=summary.identity_type,
        provider=summary.provider,
        realm=summary.realm,
        canonical_value=summary.canonical_value,
        display_value=summary.display_value,
    )


def _collect_match(
    obj: Object,
    keys: set[tuple[str, str, str]],
    anchors: set[tuple[str, str, str]],
    pending: list[Object],
    matched: list[Object],
    direction_filter: str | None,
) -> None:
    anchor = _conversation_anchor(obj, keys)
    if anchor is not None:
        anchors.add(anchor)
    if _attributable(obj, keys, anchors, direction_filter):
        matched.append(obj)
    elif _awaiting_anchor(obj, keys):
        pending.append(obj)
    if anchor is None:
        return
    still: list[Object] = []
    for item in pending:
        if _attributable(item, keys, anchors, direction_filter):
            matched.append(item)
        else:
            still.append(item)
    pending[:] = still


def _awaiting_anchor(obj: Object, keys: set[tuple[str, str, str]]) -> bool:
    if _conversation_key(obj) is None or _direct_role(obj, keys) is not None:
        return False
    return _stored_direction(obj) == "outbound"


def _newest_first(rows: list[Object]) -> list[Object]:
    return sorted(rows, key=lambda obj: ((obj.occurred_at or obj.created_at), obj.id), reverse=True)


def _attributable(
    obj: Object,
    keys: set[tuple[str, str, str]],
    anchors: set[tuple[str, str, str]],
    direction_filter: str | None,
) -> bool:
    role = _direct_role(obj, keys)
    anchored = _conversation_key(obj) in anchors
    if role is None and not anchored:
        return False
    observed = role if role is not None else _stored_direction(obj)
    return direction_filter is None or observed == direction_filter


def _conversation_anchor(obj: Object, keys: set[tuple[str, str, str]]) -> tuple[str, str, str] | None:
    if _direct_role(obj, keys) != "inbound":
        return None
    return _conversation_key(obj)


def _conversation_key(obj: Object) -> tuple[str, str, str] | None:
    metadata = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    if obj.provider == "teams" and metadata.get("chat_type") == "oneOnOne":
        tenant = _text(metadata.get("tenant_id"))
        chat = _text(metadata.get("chat_id"))
        if tenant and chat:
            return ("teams", tenant.casefold(), chat)
    if obj.provider == "mattermost" and str(metadata.get("channel_type") or "").upper() == "D":
        raw_realm = _text(metadata.get("server_url"))
        channel = _text(metadata.get("channel_id"))
        if raw_realm and channel:
            try:
                from app.connectors.mattermost.errors import MattermostSecurityError
                from app.connectors.mattermost.normalize import normalize_server_url

                return ("mattermost", normalize_server_url(raw_realm), channel)
            except MattermostSecurityError:
                return None
    return None


def _direct_role(obj: Object, keys: set[tuple[str, str, str]]) -> str | None:
    metadata = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    if obj.provider in {"gmail", "yandex_mail"}:
        direction = _email_direction(obj.provider, metadata)
        if direction == "inbound":
            sender = _email_address(metadata.get("sender") or metadata.get("from"))
            if sender and ("email", "", sender) in keys:
                return "inbound"
        if direction == "outbound" and any(
            ("email", "", address) in keys for address in _email_audience(metadata)
        ):
            return "outbound"
        return None
    if obj.provider == "telegram" and metadata.get("transport") == "mtproto":
        realm = _text(metadata.get("account_id"))
        direction = _text(metadata.get("direction"))
        if realm is None or direction not in {"inbound", "outbound"}:
            return None
        peer_kind = _text(metadata.get("peer_kind")) or ""
        if peer_kind == "private" and direction == "outbound":
            peer = _positive_id(metadata.get("peer_id"))
            if peer and ("telegram_user_id", realm, peer) in keys:
                return "outbound"
            return None
        if direction == "outbound":
            return None
        sender = _positive_id(metadata.get("sender_peer_id"))
        if sender and ("telegram_user_id", realm, sender) in keys:
            return "inbound"
        return None
    direction = _stored_direction(obj)
    if direction != "inbound":
        return None
    extracted = {
        (item.identity_type, item.realm, item.canonical_value)
        for item in extract_person_identity_evidence(obj)
    }
    if extracted.intersection(keys):
        return "inbound"
    return None


def _stored_direction(obj: Object) -> str | None:
    metadata = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    value = metadata.get("direction")
    if value in {"inbound", "outbound"}:
        return value
    if obj.provider in {"gmail", "yandex_mail"}:
        return _email_direction(obj.provider, metadata)
    return None


def _feedback_output(person_id: UUID, row: PersonIdentityEvidence) -> PersonIdentityFeedbackOutput:
    return PersonIdentityFeedbackOutput(
        person_id=person_id,
        evidence_id=row.id,
        evidence_type=row.evidence_type,
        state=row.state,
    )
