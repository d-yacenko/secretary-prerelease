"""Grounded People workspace over canonical Person objects.

Salience only orders the overview. It does not hide a known Person from
search or a rooted view, and this service does not create People or edges.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.db.models import Edge, Object, PersonIdentity, PersonIdentityEvidence
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.person_assistant import feedback_identity_key, parse_feedback_identity
from app.domain.person_candidate_score import USER_CONFIRMED, USER_REJECTED
from app.domain.person_identity import NormalizedPersonIdentity, PersonIdentityInputError
from app.domain.task_lifecycle import TERMINAL_TASK_STATUSES_FOR_READS, is_terminal_for_reads
from app.services.errors import NotFoundError, ValidationError
from app.services.graph_workspace_service import (
    DEFAULT_NEIGHBOR_LIMIT,
    DEFAULT_SEED_LIMIT,
    MAX_NEIGHBOR_LIMIT,
    MAX_SEED_LIMIT,
)
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_evidence_service import PersonEvidenceService, _identity_from_identity_row
from app.services.person_identity_service import PERSON_KIND, PersonIdentityService
from app.services.person_salience_service import PersonSalienceService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE, USER_ORIGIN
from app.tools.schemas import ListPersonRoutesInput, PersonIdentityFeedbackOutput

_MAX_IDENTITIES = 8
_MAX_ROUTES = 5
_MAX_CANDIDATES = 5
_MAX_COMMUNICATIONS = 3
_COMMUNICATION_KINDS = frozenset({"email", "chat_message"})
_FORBIDDEN_EDGE_TYPES = frozenset(
    {"member_of", "role_at", "manager_of", "works_with", "colleague", "manager", "friend"}
)
# Rooted neighbor walks stop after this many edges. Counts use SQL aggregates.
PEOPLE_EDGE_SCAN_CAP = 64
_FEEDBACK_TYPES = frozenset({USER_CONFIRMED, USER_REJECTED})


@dataclass(frozen=True)
class PeopleWorkspaceResult:
    root_id: UUID | None
    seed_ids: list[UUID]
    nodes: list[Object]
    edges: list[Edge]
    truncated: bool
    people: list[dict]


class PersonGraphWorkspaceService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._people = PersonIdentityService(session, user_id)
        self._evidence = PersonEvidenceService(session, user_id)
        self._assistant = PersonAssistantService(session, user_id)

    def get_workspace(
        self,
        *,
        root_id: UUID | None = None,
        query: str | None = None,
        seed_limit: int = DEFAULT_SEED_LIMIT,
        neighbor_limit: int = DEFAULT_NEIGHBOR_LIMIT,
    ) -> PeopleWorkspaceResult:
        seed_limit = min(max(1, seed_limit), MAX_SEED_LIMIT)
        neighbor_limit = min(max(1, neighbor_limit), MAX_NEIGHBOR_LIMIT)
        if root_id is not None:
            return self._rooted(root_id, neighbor_limit)
        if query and query.strip():
            return self._search(query.strip(), seed_limit)
        return self._overview(seed_limit)

    def correct_identity(
        self,
        person_id: UUID,
        *,
        action: str,
        identity_type: str,
        provider: str,
        realm: str,
        canonical_value: str,
    ) -> PersonIdentityFeedbackOutput:
        self._require_person(person_id)
        try:
            identity = parse_feedback_identity(identity_type, provider, realm, canonical_value)
        except PersonIdentityInputError as exc:
            raise ValidationError("identity tuple is malformed") from exc
        if action == "retract":
            return self._retract_feedback(person_id, identity)
        grounded = self._grounding(person_id, identity)
        if grounded is None:
            raise ValidationError("person identity was not exposed as a candidate")
        if action == "confirm":
            if grounded == "blocked":
                raise ValidationError("person identity is conflicted")
            self._fail_closed_confirm(person_id, identity)
            row = self._evidence.record_confirmation(
                person_id,
                identity,
                f"graph_ui:user_confirmed:{identity.canonical_value}",
                explanation="explicit graph correction",
            )
            return _feedback_output(person_id, row)
        if action == "reject":
            row = self._evidence.record_rejection(
                person_id,
                identity,
                f"graph_ui:user_rejected:{identity.canonical_value}",
                explanation="explicit graph rejection",
            )
            return _feedback_output(person_id, row)
        raise ValidationError("person identity action is unknown")

    def _overview(self, seed_limit: int) -> PeopleWorkspaceResult:
        scores, ranked = self._ranked_people()
        positive = [person for person in ranked if scores.get(person.id, 0) > 0]
        positive.sort(key=lambda person: (-scores[person.id], person.title.casefold(), str(person.id)))
        if len(positive) >= seed_limit:
            visible = positive[:seed_limit]
            shown = {person.id for person in visible}
            truncated = len(positive) > seed_limit or self._other_person_exists(shown)
            return self._result(None, visible, [], [], truncated, include_details=False, scores=scores)
        fill = seed_limit - len(positive)
        rest = self._people_page(exclude={person.id for person in positive}, limit=fill + 1)
        visible = [*positive, *rest[:fill]]
        return self._result(None, visible, [], [], len(rest) > fill, include_details=False, scores=scores)

    def _search(self, query: str, seed_limit: int) -> PeopleWorkspaceResult:
        folded = query.casefold()
        scores, ranked = self._ranked_people()
        matched = {person.id for person in self._search_people(folded, only={person.id for person in ranked})}
        positive = [
            person for person in ranked if person.id in matched and scores.get(person.id, 0) > 0
        ]
        positive.sort(key=lambda person: (-scores[person.id], person.title.casefold(), str(person.id)))
        if len(positive) >= seed_limit:
            visible = positive[:seed_limit]
            more = self._search_people(folded, exclude={person.id for person in visible}, limit=1)
            truncated = len(positive) > seed_limit or bool(more)
            return self._result(None, visible, [], [], truncated, include_details=False, scores=scores)
        fill = seed_limit - len(positive)
        rest = self._search_people(
            folded,
            exclude={person.id for person in positive},
            limit=fill + 1,
        )
        visible = [*positive, *rest[:fill]]
        return self._result(None, visible, [], [], len(rest) > fill, include_details=False, scores=scores)

    def _rooted(self, root_id: UUID, neighbor_limit: int) -> PeopleWorkspaceResult:
        root = self._require_person(root_id)
        neighbors, edges, truncated = self._neighbors(root, neighbor_limit)
        nodes = [root, *neighbors]
        return self._result(root.id, nodes, [], edges, truncated, include_details=True)

    def _result(
        self,
        root_id: UUID | None,
        nodes: list[Object],
        seed_ids: list[UUID],
        edges: list[Edge],
        truncated: bool,
        *,
        include_details: bool,
        scores: dict[UUID, int] | None = None,
    ) -> PeopleWorkspaceResult:
        people = [person for person in nodes if person.kind == PERSON_KIND]
        if root_id is None:
            seed_ids = [person.id for person in people]
        if scores is None:
            scores = self._scores()
        return PeopleWorkspaceResult(
            root_id=root_id,
            seed_ids=seed_ids,
            nodes=nodes,
            edges=edges,
            truncated=truncated,
            people=[
                self._presentation(person, scores.get(person.id, 0), include_details=include_details)
                for person in people
            ],
        )

    def _scores(self) -> dict[UUID, int]:
        return {item.person_id: item.score for item in PersonSalienceService(self._session, self._user_id).rank()}

    def _ranked_people(self) -> tuple[dict[UUID, int], list[Object]]:
        scores = self._scores()
        return scores, self._people_by_ids(list(scores))

    def _active_filters(self):
        return (
            Object.user_id == self._user_id,
            Object.kind == PERSON_KIND,
            Object.state != REJECTED_STATE,
            object_is_active(),
        )

    def _people_by_ids(self, ids: list[UUID]) -> list[Object]:
        if not ids:
            return []
        return list(
            self._session.scalars(select(Object).where(Object.id.in_(ids), *self._active_filters()))
        )

    def _people_page(self, *, exclude: set[UUID], limit: int) -> list[Object]:
        stmt = select(Object).where(*self._active_filters())
        if exclude:
            stmt = stmt.where(Object.id.notin_(exclude))
        stmt = stmt.order_by(func.lower(Object.title), Object.id).limit(limit)
        return list(self._session.scalars(stmt))

    def _other_person_exists(self, shown: set[UUID]) -> bool:
        stmt = select(Object.id).where(*self._active_filters())
        if shown:
            stmt = stmt.where(Object.id.notin_(shown))
        return self._session.scalar(stmt.limit(1)) is not None

    def _search_people(
        self,
        folded: str,
        *,
        exclude: set[UUID] | None = None,
        only: set[UUID] | None = None,
        limit: int | None = None,
    ) -> list[Object]:
        if only is not None and not only:
            return []
        stmt = select(Object).where(*self._active_filters(), self._search_clause(folded))
        if exclude:
            stmt = stmt.where(Object.id.notin_(exclude))
        if only is not None:
            stmt = stmt.where(Object.id.in_(only))
        stmt = stmt.order_by(func.lower(Object.title), Object.id)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self._session.scalars(stmt))

    def _search_clause(self, folded: str):
        pattern = _like_pattern(folded)
        title = func.lower(Object.title).like(pattern, escape="\\")
        identity = exists(
            select(PersonIdentity.id).where(
                PersonIdentity.user_id == self._user_id,
                PersonIdentity.person_object_id == Object.id,
                PersonIdentity.state != REJECTED_STATE,
                _identity_is_effective(),
                or_(
                    func.lower(PersonIdentity.canonical_value).like(pattern, escape="\\"),
                    func.lower(func.coalesce(PersonIdentity.display_value, "")).like(pattern, escape="\\"),
                ),
            )
        )
        return or_(title, identity)

    def _require_person(self, person_id: UUID) -> Object:
        person = self._session.get(Object, person_id)
        if (
            person is None
            or person.user_id != self._user_id
            or person.kind != PERSON_KIND
            or person.state == REJECTED_STATE
            or is_object_hidden_from_active_reads(person)
        ):
            raise NotFoundError("person", person_id)
        return person

    def _neighbors(self, person: Object, limit: int) -> tuple[list[Object], list[Edge], bool]:
        scanned = list(
            self._session.scalars(
                select(Edge)
                .where(
                    Edge.user_id == self._user_id,
                    Edge.state != REJECTED_STATE,
                    Edge.type.notin_(_FORBIDDEN_EDGE_TYPES),
                    or_(Edge.source_id == person.id, Edge.target_id == person.id),
                )
                .order_by(Edge.id)
                .limit(PEOPLE_EDGE_SCAN_CAP + 1)
            )
        )
        scan_truncated = len(scanned) > PEOPLE_EDGE_SCAN_CAP
        edges = scanned[:PEOPLE_EDGE_SCAN_CAP]
        chosen: list[tuple[Object, Edge]] = []
        communications = 0
        for edge in edges:
            other_id = edge.target_id if edge.source_id == person.id else edge.source_id
            other = self._session.get(Object, other_id)
            if other is None or other.user_id != self._user_id or is_object_hidden_from_active_reads(other):
                continue
            if other.state == REJECTED_STATE:
                continue
            open_task = other.kind == "task" and not is_terminal_for_reads(other.status)
            grounded = edge.state == CONFIRMED_STATE or edge.origin == USER_ORIGIN
            if open_task or (grounded and other.kind != PERSON_KIND):
                if other.kind in _COMMUNICATION_KINDS:
                    communications += 1
                    if communications > _MAX_COMMUNICATIONS:
                        continue
                chosen.append((other, edge))
        chosen.sort(key=lambda item: (0 if item[0].kind == "task" else 1, item[0].title, str(item[0].id)))
        truncated = scan_truncated or len(chosen) > limit
        visible = chosen[:limit]
        return [item[0] for item in visible], [item[1] for item in visible], truncated

    def _presentation(self, person: Object, score: int, *, include_details: bool) -> dict:
        identities = self._identity_presentations(person.id, include_rejected=include_details)
        conflict = any(item["state"] == "conflicted" for item in identities)
        routes = self._routes(person.id) if include_details else self._email_route_summaries(person.id)
        if include_details:
            identities.extend(self._candidates(person.id))
            conflict = conflict or any(item["state"] == "conflicted" for item in identities)
        return {
            "person_id": person.id,
            "title": person.title,
            "salience_score": score,
            "identities": identities[: _MAX_IDENTITIES + _MAX_CANDIDATES],
            "routes": routes[:_MAX_ROUTES],
            "identity_conflict": conflict,
            "open_task_count": self._open_task_count(person.id),
            "recent_communication_count": self._communication_count(person.id),
        }

    def _identity_presentations(self, person_id: UUID, *, include_rejected: bool) -> list[dict]:
        rows = []
        for row in self._identity_rows(person_id):
            identity = _identity_from_identity_row(row)
            rejected = self._evidence.is_rejected(person_id, identity)
            if rejected and not include_rejected:
                continue
            state = "rejected" if rejected else ("conflicted" if self._is_conflicted(identity) else "effective")
            rows.append(self._identity_payload(identity, state, confirmable=False))
        return rows[:_MAX_IDENTITIES]

    def _candidates(self, person_id: UUID) -> list[dict]:
        page = self._assistant.find_identity_candidates(
            person_id,
            include_quarantined_telegram=True,
        )
        found = []
        for item in page.candidates[:_MAX_CANDIDATES]:
            state = "conflicted" if "identity_conflict" in item.reasons else "candidate"
            found.append(
                {
                    "provider": item.identity.provider,
                    "identity_type": item.identity.identity_type,
                    "display_value": item.identity.display_value or item.identity.canonical_value,
                    "realm": item.identity.realm,
                    "canonical_value": item.identity.canonical_value,
                    "state": state,
                    "confirmable": item.confirmable,
                }
            )
        return found

    def _routes(self, person_id: UUID) -> list[dict]:
        listed = self._assistant.list_routes(
            ListPersonRoutesInput(person_id=person_id),
            include_quarantined_telegram=True,
        )
        return [
            {"provider": route.provider, "label": route.label, "route_key": route.route_key}
            for route in listed.routes[:_MAX_ROUTES]
        ]

    def _email_route_summaries(self, person_id: UUID) -> list[dict]:
        rows = self._session.scalars(
            select(PersonIdentity)
            .where(
                PersonIdentity.user_id == self._user_id,
                PersonIdentity.person_object_id == person_id,
                PersonIdentity.state != REJECTED_STATE,
                PersonIdentity.identity_type == "email",
                _identity_is_effective(),
            )
            .limit(_MAX_ROUTES)
        )
        return [
            {
                "provider": row.provider,
                "label": row.display_value or row.canonical_value,
                "route_key": f"email:{row.canonical_value}",
            }
            for row in rows
        ]

    def _identity_rows(self, person_id: UUID) -> list[PersonIdentity]:
        return [
            row
            for row in self._people.list_identities(person_id)
            if row.state != REJECTED_STATE
        ]

    def _open_task_count(self, person_id: UUID) -> int:
        other = aliased(Object)
        count = self._session.scalar(
            select(func.count())
            .select_from(Edge)
            .join(other, _linked_object(person_id, other))
            .where(
                Edge.user_id == self._user_id,
                Edge.state != REJECTED_STATE,
                other.user_id == self._user_id,
                other.kind == "task",
                object_is_active(other),
                or_(other.status.is_(None), other.status.notin_(tuple(TERMINAL_TASK_STATUSES_FOR_READS))),
            )
        )
        return int(count or 0)

    def _communication_count(self, person_id: UUID) -> int:
        other = aliased(Object)
        count = self._session.scalar(
            select(func.count())
            .select_from(Edge)
            .join(other, _linked_object(person_id, other))
            .where(
                Edge.user_id == self._user_id,
                Edge.state != REJECTED_STATE,
                other.user_id == self._user_id,
                other.kind.in_(_COMMUNICATION_KINDS),
                other.state != REJECTED_STATE,
                object_is_active(other),
            )
        )
        return min(int(count or 0), 20)

    def _retract_feedback(
        self,
        person_id: UUID,
        identity: NormalizedPersonIdentity,
    ) -> PersonIdentityFeedbackOutput:
        rows = [
            row
            for row in self._evidence.history(person_id, identity)
            if row.state == "active" and row.evidence_type in _FEEDBACK_TYPES
        ]
        if not rows:
            raise ValidationError("no active identity feedback to retract")
        retracted = rows[0]
        for row in rows:
            retracted = self._evidence.retract(row.id)
        return _feedback_output(person_id, retracted)

    def _grounding(self, person_id: UUID, identity: NormalizedPersonIdentity) -> str | None:
        wanted = feedback_identity_key(identity)
        for row in self._identity_rows(person_id):
            if feedback_identity_key(_identity_from_identity_row(row)) == wanted:
                return "attached"
        linked = self._session.scalar(
            select(PersonIdentityEvidence.id)
            .where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id == person_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
            )
            .limit(1)
        )
        if linked is not None:
            return "evidence"
        page = self._assistant.find_identity_candidates(
            person_id,
            include_quarantined_telegram=True,
        )
        for item in page.candidates:
            key = (
                item.identity.identity_type,
                item.identity.provider,
                item.identity.realm,
                item.identity.canonical_value,
            )
            if key != wanted:
                continue
            return "candidate" if item.confirmable else "blocked"
        return None

    def _is_conflicted(self, identity: NormalizedPersonIdentity) -> bool:
        rows = self._session.scalars(
            select(PersonIdentityEvidence).where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type == USER_CONFIRMED,
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
            )
        )
        people = {row.person_object_id for row in rows}
        owner = self._people.resolve(identity)
        if owner is not None:
            people.add(owner.id)
        return len(people) > 1

    def _fail_closed_confirm(self, person_id: UUID, identity: NormalizedPersonIdentity) -> None:
        owner = self._people.resolve(identity)
        if owner is not None and owner.id != person_id:
            raise ValidationError("person identity is owned by another person")
        if self._is_conflicted(identity):
            raise ValidationError("person identity is conflicted")

    def _identity_payload(self, identity: NormalizedPersonIdentity, state: str, *, confirmable: bool) -> dict:
        return {
            "provider": identity.provider,
            "identity_type": identity.identity_type,
            "display_value": identity.display_value or identity.canonical_value,
            "realm": identity.realm,
            "canonical_value": identity.canonical_value,
            "state": state,
            "confirmable": confirmable,
        }


def _like_pattern(folded: str) -> str:
    escaped = folded.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _identity_is_effective():
    return ~exists(
        select(PersonIdentityEvidence.id).where(
            PersonIdentityEvidence.user_id == PersonIdentity.user_id,
            PersonIdentityEvidence.person_object_id == PersonIdentity.person_object_id,
            PersonIdentityEvidence.state == "active",
            PersonIdentityEvidence.evidence_type == USER_REJECTED,
            PersonIdentityEvidence.provider == PersonIdentity.provider,
            PersonIdentityEvidence.identity_type == PersonIdentity.identity_type,
            PersonIdentityEvidence.realm == PersonIdentity.realm,
            PersonIdentityEvidence.canonical_value == PersonIdentity.canonical_value,
        )
    )


def _linked_object(person_id: UUID, other):
    return or_(
        and_(Edge.source_id == person_id, other.id == Edge.target_id),
        and_(Edge.target_id == person_id, other.id == Edge.source_id),
    )


def _feedback_output(person_id: UUID, row: PersonIdentityEvidence) -> PersonIdentityFeedbackOutput:
    return PersonIdentityFeedbackOutput(
        person_id=person_id,
        evidence_id=row.id,
        evidence_type=row.evidence_type,
        state=row.state,
    )
