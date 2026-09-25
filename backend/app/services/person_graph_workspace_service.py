"""Grounded People workspace over canonical Person objects.

Salience only orders the overview. It does not hide a known Person from
search or a rooted view, and this service does not create People or edges.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Edge, Object, PersonIdentity, PersonIdentityEvidence
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.person_assistant import parse_feedback_identity
from app.domain.person_candidate_score import USER_CONFIRMED
from app.domain.person_identity import NormalizedPersonIdentity, PersonIdentityInputError
from app.domain.task_lifecycle import is_terminal_for_reads
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
from app.tools.schemas import ListPersonRoutesInput, PersonIdentityFeedbackInput

_MAX_IDENTITIES = 8
_MAX_ROUTES = 5
_MAX_CANDIDATES = 5
_MAX_COMMUNICATIONS = 3
_COMMUNICATION_KINDS = frozenset({"email", "chat_message"})
_FORBIDDEN_EDGE_TYPES = frozenset(
    {"member_of", "role_at", "manager_of", "works_with", "colleague", "manager", "friend"}
)


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
    ):
        self._require_person(person_id)
        try:
            identity = parse_feedback_identity(identity_type, provider, realm, canonical_value)
        except PersonIdentityInputError as exc:
            raise ValidationError("identity tuple is malformed") from exc
        payload = PersonIdentityFeedbackInput(
            person_id=person_id,
            identity_type=identity.identity_type,
            provider=identity.provider,
            realm=identity.realm,
            canonical_value=identity.canonical_value,
        )
        if action == "confirm":
            self._fail_closed_confirm(person_id, identity)
            return self._assistant.confirm_person_identity(payload)
        if action == "reject":
            return self._assistant.reject_person_identity(payload)
        if action == "retract":
            return self._assistant.retract_person_identity_feedback(payload)
        raise ValidationError("person identity action is unknown")

    def _overview(self, seed_limit: int) -> PeopleWorkspaceResult:
        ordered = self._ordered_people()
        visible = ordered[:seed_limit]
        return self._result(None, visible, [], [], len(ordered) > seed_limit, include_details=False)

    def _search(self, query: str, seed_limit: int) -> PeopleWorkspaceResult:
        folded = query.casefold()
        matched = [person for person in self._ordered_people() if self._matches(person, folded)]
        visible = matched[:seed_limit]
        return self._result(None, visible, [], [], len(matched) > seed_limit, include_details=False)

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
    ) -> PeopleWorkspaceResult:
        people = [person for person in nodes if person.kind == PERSON_KIND]
        if root_id is None:
            seed_ids = [person.id for person in people]
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

    def _ordered_people(self) -> list[Object]:
        scores = self._scores()
        people = self._active_people()
        people.sort(key=lambda person: (-scores.get(person.id, 0), person.title.casefold(), str(person.id)))
        return people

    def _scores(self) -> dict[UUID, int]:
        return {item.person_id: item.score for item in PersonSalienceService(self._session, self._user_id).rank()}

    def _active_people(self) -> list[Object]:
        rows = self._session.scalars(
            select(Object).where(
                Object.user_id == self._user_id,
                Object.kind == PERSON_KIND,
                Object.state != REJECTED_STATE,
                object_is_active(),
            )
        )
        return [row for row in rows if not is_object_hidden_from_active_reads(row)]

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

    def _matches(self, person: Object, folded: str) -> bool:
        if folded in person.title.casefold():
            return True
        for row in self._identity_rows(person.id):
            display = (row.display_value or row.canonical_value).casefold()
            if folded in display or folded in row.canonical_value.casefold():
                return True
        return False

    def _neighbors(self, person: Object, limit: int) -> tuple[list[Object], list[Edge], bool]:
        edges = self._session.scalars(
            select(Edge).where(
                Edge.user_id == self._user_id,
                Edge.state != REJECTED_STATE,
                Edge.type.notin_(_FORBIDDEN_EDGE_TYPES),
                or_(Edge.source_id == person.id, Edge.target_id == person.id),
            )
        )
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
        truncated = len(chosen) > limit
        visible = chosen[:limit]
        return [item[0] for item in visible], [item[1] for item in visible], truncated

    def _presentation(self, person: Object, score: int, *, include_details: bool) -> dict:
        identities = self._identity_presentations(person.id, include_rejected=include_details)
        conflict = any(item["state"] == "conflicted" for item in identities)
        routes = self._routes(person.id) if include_details else self._email_route_summaries(person.id)
        if include_details:
            identities.extend(self._candidates(person.id))
            conflict = conflict or any(item["state"] == "conflicted" for item in identities)
        tasks = self._open_tasks(person.id)
        return {
            "person_id": person.id,
            "title": person.title,
            "salience_score": score,
            "identities": identities[: _MAX_IDENTITIES + _MAX_CANDIDATES],
            "routes": routes[:_MAX_ROUTES],
            "identity_conflict": conflict,
            "open_task_count": len(tasks),
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
        page = self._assistant.find_identity_candidates(person_id)
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
        listed = self._assistant.list_routes(ListPersonRoutesInput(person_id=person_id))
        return [
            {"provider": route.provider, "label": route.label, "route_key": route.route_key}
            for route in listed.routes[:_MAX_ROUTES]
        ]

    def _email_route_summaries(self, person_id: UUID) -> list[dict]:
        routes = []
        for row in self._evidence.effective_identities():
            if row.person_object_id != person_id or row.identity_type != "email":
                continue
            routes.append(
                {
                    "provider": row.provider,
                    "label": row.display_value or row.canonical_value,
                    "route_key": f"email:{row.canonical_value}",
                }
            )
        return routes[:_MAX_ROUTES]

    def _identity_rows(self, person_id: UUID) -> list[PersonIdentity]:
        return [
            row
            for row in self._people.list_identities(person_id)
            if row.state != REJECTED_STATE
        ]

    def _open_tasks(self, person_id: UUID) -> list[Object]:
        found: list[Object] = []
        edges = self._session.scalars(
            select(Edge).where(
                Edge.user_id == self._user_id,
                Edge.state != REJECTED_STATE,
                or_(Edge.source_id == person_id, Edge.target_id == person_id),
            )
        )
        for edge in edges:
            other_id = edge.target_id if edge.source_id == person_id else edge.source_id
            other = self._session.get(Object, other_id)
            if other is None or other.kind != "task" or is_terminal_for_reads(other.status):
                continue
            if other.user_id != self._user_id or is_object_hidden_from_active_reads(other):
                continue
            found.append(other)
        return found

    def _communication_count(self, person_id: UUID) -> int:
        count = 0
        edges = self._session.scalars(
            select(Edge).where(
                Edge.user_id == self._user_id,
                Edge.state != REJECTED_STATE,
                or_(Edge.source_id == person_id, Edge.target_id == person_id),
            )
        )
        for edge in edges:
            other_id = edge.target_id if edge.source_id == person_id else edge.source_id
            other = self._session.get(Object, other_id)
            if other is None or other.kind not in _COMMUNICATION_KINDS:
                continue
            if is_object_hidden_from_active_reads(other) or other.state == REJECTED_STATE:
                continue
            count += 1
        return min(count, 20)

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
