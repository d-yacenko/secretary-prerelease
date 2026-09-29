"""Grounded People workspace over canonical Person objects.

Salience only orders the overview. It does not hide a known Person from
search or a rooted view, and this service does not create People or edges.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.db.models import Edge, Object, PersonIdentity, PersonIdentityEvidence
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.person_assistant import feedback_identity_key, parse_feedback_identity
from app.domain.person_candidate_score import USER_CONFIRMED, USER_REJECTED
from app.domain.person_identity import (
    NormalizedPersonIdentity,
    PersonIdentityInputError,
    normalize_email,
)
from app.domain.task_lifecycle import TERMINAL_TASK_STATUSES_FOR_READS, is_terminal_for_reads
from app.domain.task_relations import TASK_ACTOR_ROLES
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.graph_workspace_service import (
    DEFAULT_NEIGHBOR_LIMIT,
    DEFAULT_SEED_LIMIT,
    MAX_NEIGHBOR_LIMIT,
    MAX_SEED_LIMIT,
    GraphWorkspaceService,
)
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_consolidation_service import PersonConsolidationService
from app.services.person_evidence_service import PersonEvidenceService, _identity_from_identity_row
from app.services.person_identity_service import PERSON_KIND, PersonIdentityService
from app.services.person_promotion_service import PersonPromotionService, parse_promotion_identity
from app.services.person_salience_service import PersonSalienceService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE, USER_ORIGIN
from app.tools.schemas import (
    FindPersonCommunicationsInput,
    ListPersonRoutesInput,
    PersonIdentityFeedbackOutput,
)

_MAX_IDENTITIES = 8
_MAX_ROUTES = 5
_MAX_CANDIDATES = 5
_MAX_COMMUNICATIONS = 3
_MAX_TRUTH_ROWS = 8
_COMMUNICATION_KINDS = frozenset({"email", "chat_message"})
_FORBIDDEN_EDGE_TYPES = frozenset(
    {"member_of", "role_at", "manager_of", "works_with", "colleague", "manager", "friend"}
)
# Rooted neighbor walks stop after this many edges. Counts use SQL aggregates.
PEOPLE_EDGE_SCAN_CAP = 64
# Distinct confirmed Task anchors returned for later landscape projection.
PEOPLE_LANDSCAPE_TASK_ANCHOR_CAP = 64
_FEEDBACK_TYPES = frozenset({USER_CONFIRMED, USER_REJECTED})


@dataclass(frozen=True)
class PeopleWorkspaceResult:
    root_id: UUID | None
    seed_ids: list[UUID]
    nodes: list[Object]
    edges: list[Edge]
    truncated: bool
    people: list[dict]
    landscape_tasks: list[Object]
    landscape_task_edges: list[Edge]
    landscape_task_context_complete: bool
    promotion_candidates: list[dict]
    promotion_candidates_truncated: bool
    promotion_suppressions: list[dict]


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
            created = self._activate_unattached(person_id, identity)
            row = self._evidence.record_confirmation(
                person_id,
                identity,
                f"graph_ui:user_confirmed:{identity.canonical_value}",
                explanation="explicit graph correction",
            )
            if created is not None and row.person_identity_id is None:
                row.person_identity_id = created.id
                self._session.flush()
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

    def apply_promotion(
        self,
        *,
        action: str,
        identity_type: str,
        provider: str,
        realm: str,
        canonical_value: str,
    ) -> dict:
        identity = parse_promotion_identity(identity_type, provider, realm, canonical_value)
        promotions = PersonPromotionService(self._session, self._user_id)
        if action == "approve":
            person = promotions.approve(identity)
            return {"action": "approve", "person_id": str(person.id)}
        if action == "suppress":
            row = promotions.suppress(identity, display_value=identity.display_value)
            return {"action": "suppress", "state": row.state}
        if action == "retract":
            row = promotions.retract(identity)
            return {"action": "retract", "state": row.state}
        raise ValidationError("person promotion action is unknown")

    def bind_email(self, person_id: UUID, raw_email: str) -> PersonIdentityFeedbackOutput:
        self._require_person(person_id)
        try:
            identity = normalize_email(raw_email)
        except PersonIdentityInputError as exc:
            raise ValidationError("email identity is malformed") from exc
        owner = self._people.resolve(identity)
        if owner is not None and owner.id != person_id:
            raise ConflictError("person email is already bound")
        if self._confirmed_by_other_person(person_id, identity):
            raise ConflictError("person email is already bound")
        created = None
        if owner is None:
            try:
                created = self._people.attach(person_id, identity)
            except ConflictError as exc:
                raise ConflictError("person email is already bound") from exc
        existing = self._active_confirmation(person_id, identity)
        if existing is not None:
            if created is not None and existing.person_identity_id is None:
                existing.person_identity_id = created.id
                self._session.flush()
            return _feedback_output(person_id, existing)
        row = self._evidence.record_confirmation(
            person_id,
            identity,
            f"graph_ui:manual_email:{identity.canonical_value}",
            explanation="explicit manual email binding",
        )
        if created is not None and row.person_identity_id is None:
            row.person_identity_id = created.id
            self._session.flush()
        return _feedback_output(person_id, row)

    def _with_promotions(self, result: PeopleWorkspaceResult) -> PeopleWorkspaceResult:
        candidates, truncated, suppressions = PersonPromotionService(
            self._session,
            self._user_id,
        ).overview(include_quarantined_telegram=True)
        return replace(
            result,
            promotion_candidates=candidates,
            promotion_candidates_truncated=truncated,
            promotion_suppressions=suppressions,
        )

    def _overview(self, seed_limit: int) -> PeopleWorkspaceResult:
        scores, ranked = self._ranked_people()
        positive = [person for person in ranked if scores.get(person.id, 0) > 0]
        positive.sort(key=lambda person: (-scores[person.id], person.title.casefold(), str(person.id)))
        if len(positive) >= seed_limit:
            visible = positive[:seed_limit]
            shown = {person.id for person in visible}
            truncated = len(positive) > seed_limit or self._other_person_exists(shown)
            return self._with_promotions(
                self._result(None, visible, [], [], truncated, include_details=False, scores=scores)
            )
        fill = seed_limit - len(positive)
        rest = self._people_page(exclude={person.id for person in positive}, limit=fill + 1)
        visible = [*positive, *rest[:fill]]
        return self._with_promotions(
            self._result(None, visible, [], [], len(rest) > fill, include_details=False, scores=scores)
        )

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
        person_ids = [person.id for person in people]
        communication_counts, communication_truncated = self._communication_counts(person_ids)
        landscape_anchors = self._landscape_task_anchors(person_ids)
        people_payloads = [
            self._presentation(
                person,
                scores.get(person.id, 0),
                include_details=include_details,
                include_truth=include_details and person.id == root_id,
                communication_count=communication_counts.get(person.id, 0),
                communication_count_truncated=communication_truncated,
                landscape_task_ids=landscape_anchors[person.id][0],
                landscape_task_ids_complete=landscape_anchors[person.id][1],
            )
            for person in people
        ]
        anchor_ids: set[UUID] = set()
        for payload in people_payloads:
            if payload["landscape_task_ids_complete"]:
                anchor_ids.update(payload["landscape_task_ids"])
        context_tasks, context_edges, context_complete = GraphWorkspaceService(
            self._session,
            self._user_id,
        ).landscape_task_context(anchor_ids)
        return PeopleWorkspaceResult(
            root_id=root_id,
            seed_ids=seed_ids,
            nodes=nodes,
            edges=edges,
            truncated=truncated,
            promotion_candidates=[],
            promotion_candidates_truncated=False,
            promotion_suppressions=[],
            people=people_payloads,
            landscape_tasks=context_tasks,
            landscape_task_edges=context_edges,
            landscape_task_context_complete=context_complete,
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

    def _presentation(
        self,
        person: Object,
        score: int,
        *,
        include_details: bool,
        include_truth: bool,
        communication_count: int,
        communication_count_truncated: bool = False,
        landscape_task_ids: list[UUID] | None = None,
        landscape_task_ids_complete: bool = True,
    ) -> dict:
        identities = self._identity_presentations(person.id, include_rejected=include_details)
        conflict = any(item["state"] == "conflicted" for item in identities)
        routes = self._routes(person.id) if include_details else self._email_route_summaries(person.id)
        payload = {
            "person_id": person.id,
            "title": person.title,
            "salience_score": score,
            "identities": identities[:_MAX_IDENTITIES],
            "routes": routes[:_MAX_ROUTES],
            "identity_conflict": conflict,
            "open_task_count": self._open_task_count(person.id),
            "recent_communication_count": communication_count,
            "recent_communication_count_truncated": communication_count_truncated,
            "landscape_task_ids": landscape_task_ids or [],
            "landscape_task_ids_complete": landscape_task_ids_complete,
        }
        if include_truth:
            involvement, involvement_truncated = self._task_involvement(person.id)
            flow = self._assistant.find_communications(
                FindPersonCommunicationsInput(person_id=person.id, limit=_MAX_TRUTH_ROWS),
                include_quarantined_telegram=True,
            )
            salience = PersonSalienceService(self._session, self._user_id).evaluate_rooted(person.id)
            candidates, candidates_truncated = self._identity_candidates(person.id)
            payload.update(
                {
                    "task_involvement": involvement,
                    "task_involvement_truncated": involvement_truncated,
                    "recent_communications": [
                        {
                            "object_id": item.id,
                            "kind": item.kind,
                            "provider": item.provider,
                            "title": item.title,
                            "occurred_at": item.occurred_at,
                        }
                        for item in flow.objects
                    ],
                    "recent_communications_truncated": flow.truncated,
                    "salience": {
                        "score": salience.score,
                        "tier": salience.tier,
                        "components": [
                            {"name": component.name, "value": component.value}
                            for component in salience.components
                        ],
                        "truncated": salience.truncated,
                        "window_days": salience.window_days,
                        "claims_object_importance": salience.claims_object_importance,
                    },
                    "identity_candidates": candidates,
                    "identity_candidates_truncated": candidates_truncated,
                    "rejected_identity_candidates": self._rejected_identity_candidates(person.id),
                    "consolidations": PersonConsolidationService(
                        self._session, self._user_id
                    ).history_for(person.id),
                }
            )
        return payload

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

    def _identity_candidates(self, person_id: UUID) -> tuple[list[dict], bool]:
        page = self._assistant.find_identity_candidates(
            person_id,
            include_quarantined_telegram=True,
        )
        found = []
        for item in page.candidates:
            state = "conflicted" if "identity_conflict" in item.reasons else "candidate"
            payload = {
                "provider": item.identity.provider,
                "identity_type": item.identity.identity_type,
                "realm": item.identity.realm,
                "canonical_value": item.identity.canonical_value,
                "display_value": item.identity.display_value or item.identity.canonical_value,
                "confirmable": item.confirmable,
                "state": state,
                "reasons": list(item.reasons),
                "assessment_resolution": item.assessment_resolution,
                "sources": self._source_previews(item.source_object_ids),
            }
            if state == "conflicted" and "grounded_duplicate" in item.reasons:
                owner = self._people.resolve(
                    NormalizedPersonIdentity(
                        identity_type=item.identity.identity_type,
                        provider=item.identity.provider,
                        realm=item.identity.realm,
                        canonical_value=item.identity.canonical_value,
                        display_value=item.identity.display_value,
                    )
                )
                if owner is not None and owner.id != person_id and self._is_active_person(owner.id):
                    payload["conflicting_person_id"] = owner.id
            found.append(payload)
        return found, page.truncated

    def _source_previews(self, object_ids: tuple[UUID, ...]) -> list[dict]:
        wanted = list(object_ids)[:3]
        if not wanted:
            return []
        rows = self._session.scalars(
            select(Object).where(
                Object.user_id == self._user_id,
                Object.id.in_(wanted),
                object_is_active(Object),
            )
        )
        by_id = {row.id: row for row in rows}
        previews = []
        for object_id in wanted:
            item = by_id.get(object_id)
            if item is None:
                continue
            previews.append(
                {
                    "object_id": item.id,
                    "kind": item.kind,
                    "provider": item.provider,
                    "title": item.title,
                    "occurred_at": item.occurred_at,
                }
            )
        return previews

    def _rejected_identity_candidates(self, person_id: UUID) -> list[dict]:
        attached = {
            (row.provider, row.identity_type, row.realm, row.canonical_value)
            for row in self._identity_rows(person_id)
        }
        rows = self._session.scalars(
            select(PersonIdentityEvidence)
            .where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id == person_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type == USER_REJECTED,
            )
            .order_by(PersonIdentityEvidence.canonical_value, PersonIdentityEvidence.id)
            .limit(_MAX_CANDIDATES)
        )
        found = []
        for row in rows:
            key = (row.provider, row.identity_type, row.realm, row.canonical_value)
            if key in attached:
                continue
            found.append(
                {
                    "provider": row.provider,
                    "identity_type": row.identity_type,
                    "realm": row.realm,
                    "canonical_value": row.canonical_value,
                    "display_value": row.canonical_value,
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

    def _task_involvement(self, person_id: UUID) -> tuple[list[dict], bool]:
        task = aliased(Object)
        rows = list(
            self._session.execute(
                select(Edge, task)
                .join(task, task.id == Edge.source_id)
                .where(
                    Edge.user_id == self._user_id,
                    Edge.target_id == person_id,
                    Edge.type.in_(tuple(TASK_ACTOR_ROLES)),
                    Edge.state != REJECTED_STATE,
                    task.user_id == self._user_id,
                    task.kind == "task",
                    object_is_active(task),
                    or_(
                        task.status.is_(None),
                        task.status.notin_(tuple(TERMINAL_TASK_STATUSES_FOR_READS)),
                    ),
                )
                .order_by(
                    task.due_at.asc().nulls_last(),
                    func.lower(task.title),
                    task.id,
                    Edge.type,
                    Edge.id,
                )
                .limit(_MAX_TRUTH_ROWS + 1)
            )
        )
        visible = rows[:_MAX_TRUTH_ROWS]
        return [
            {
                "edge_id": edge.id,
                "task_id": item.id,
                "title": item.title,
                "status": item.status,
                "completion_mode": item.completion_mode,
                "due_at": item.due_at,
                "role": edge.type,
                "edge_state": edge.state,
                "edge_origin": edge.origin,
            }
            for edge, item in visible
        ], len(rows) > _MAX_TRUTH_ROWS

    def _landscape_task_anchors(self, person_ids: list[UUID]) -> dict[UUID, tuple[list[UUID], bool]]:
        result = {person_id: ([], True) for person_id in person_ids}
        if not person_ids:
            return result
        task = aliased(Object)
        pairs = (
            select(Edge.target_id.label("person_id"), task.id.label("task_id"))
            .join(task, task.id == Edge.source_id)
            .where(
                Edge.user_id == self._user_id,
                Edge.target_id.in_(person_ids),
                Edge.type.in_(tuple(TASK_ACTOR_ROLES)),
                Edge.state == CONFIRMED_STATE,
                task.user_id == self._user_id,
                task.kind == "task",
                task.state != REJECTED_STATE,
                object_is_active(task),
                or_(
                    task.status.is_(None),
                    task.status.notin_(tuple(TERMINAL_TASK_STATUSES_FOR_READS)),
                ),
            )
            .distinct()
            .subquery()
        )
        ranked = select(
            pairs.c.person_id,
            pairs.c.task_id,
            func.row_number()
            .over(partition_by=pairs.c.person_id, order_by=pairs.c.task_id)
            .label("rn"),
        ).subquery()
        rows = self._session.execute(
            select(ranked.c.person_id, ranked.c.task_id).where(
                ranked.c.rn <= PEOPLE_LANDSCAPE_TASK_ANCHOR_CAP + 1
            )
        )
        grouped: dict[UUID, list[UUID]] = {}
        for person_id, task_id in rows:
            grouped.setdefault(person_id, []).append(task_id)
        for person_id, task_ids in grouped.items():
            ordered = sorted(task_ids)
            complete = len(ordered) <= PEOPLE_LANDSCAPE_TASK_ANCHOR_CAP
            result[person_id] = (ordered[:PEOPLE_LANDSCAPE_TASK_ANCHOR_CAP], complete)
        return result

    def _open_task_count(self, person_id: UUID) -> int:
        other = aliased(Object)
        count = self._session.scalar(
            select(func.count(func.distinct(other.id)))
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

    def _communication_counts(self, person_ids: list[UUID]) -> tuple[dict[UUID, int], bool]:
        # Identity-grounded count from one shared bounded scan, not graph edges.
        return self._assistant.count_attributable_communications(
            person_ids,
            include_quarantined_telegram=True,
        )

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
        created_ids = [
            row.person_identity_id
            for row in rows
            if row.evidence_type == USER_CONFIRMED and row.person_identity_id is not None
        ]
        retracted = rows[0]
        for row in rows:
            retracted = self._evidence.retract(row.id)
        for identity_id in created_ids:
            self._detach_confirmation_identity(person_id, identity_id)
        return _feedback_output(person_id, retracted)

    def _activate_unattached(
        self,
        person_id: UUID,
        identity: NormalizedPersonIdentity,
    ) -> PersonIdentity | None:
        if self._people.resolve(identity) is not None:
            return None
        try:
            return self._people.attach(person_id, identity)
        except ConflictError as exc:
            raise ValidationError("person identity is conflicted") from exc

    def _detach_confirmation_identity(self, person_id: UUID, identity_id: UUID) -> None:
        row = self._session.get(PersonIdentity, identity_id)
        if row is None or row.user_id != self._user_id:
            return
        if row.person_object_id != person_id or row.state == REJECTED_STATE:
            return
        self._people.detach(row.id)

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
        people = {row.person_object_id for row in rows if self._is_active_person(row.person_object_id)}
        owner = self._people.resolve(identity)
        if owner is not None and self._is_active_person(owner.id):
            people.add(owner.id)
        return len(people) > 1

    def _is_active_person(self, person_id: UUID) -> bool:
        person = self._session.get(Object, person_id)
        return (
            person is not None
            and person.user_id == self._user_id
            and person.kind == PERSON_KIND
            and person.state != REJECTED_STATE
            and not is_object_hidden_from_active_reads(person)
        )

    def _active_confirmation(
        self,
        person_id: UUID,
        identity: NormalizedPersonIdentity,
    ) -> PersonIdentityEvidence | None:
        return self._session.scalar(
            select(PersonIdentityEvidence).where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id == person_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type == USER_CONFIRMED,
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
            ).limit(1)
        )

    def _confirmed_by_other_person(self, person_id: UUID, identity: NormalizedPersonIdentity) -> bool:
        other = self._session.scalar(
            select(PersonIdentityEvidence.id)
            .join(Object, Object.id == PersonIdentityEvidence.person_object_id)
            .where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id != person_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type == USER_CONFIRMED,
                PersonIdentityEvidence.provider == identity.provider,
                PersonIdentityEvidence.identity_type == identity.identity_type,
                PersonIdentityEvidence.realm == identity.realm,
                PersonIdentityEvidence.canonical_value == identity.canonical_value,
                Object.user_id == self._user_id,
                Object.kind == PERSON_KIND,
                Object.state != REJECTED_STATE,
                object_is_active(),
            )
            .limit(1)
        )
        return other is not None

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
