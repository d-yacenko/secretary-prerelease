"""Read-only Assistant access to stored Person role facts.

This service does not assign, retract, merge, or infer roles.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Object, PersonRoleAssignment, PersonRoleTerm
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.person_role_text import (
    PersonRoleTextError,
    role_context_identity,
    role_term_identity,
)
from app.services.errors import NotFoundError, ValidationError
from app.services.person_identity_service import PERSON_KIND
from app.services.person_role_service import (
    ACTIVE_STATE,
    MAX_ACTIVE_ASSIGNMENTS,
    RETRACTED_STATE,
    PersonRoleService,
)
from app.services.provenance import AGENT_ORIGIN, REJECTED_STATE
from app.tools.schemas import (
    AssignPersonRoleCanonicalInput,
    AssignPersonRoleInput,
    AssignPersonRoleOutput,
    FindPeopleByRoleOutput,
    GetPersonRolesOutput,
    PersonRoleAssignmentOut,
    PersonRoleMatchAssignmentOut,
    PersonRoleMatchOut,
    PersonRoleSuggestionOut,
    RetractPersonRoleCanonicalInput,
    RetractPersonRoleInput,
    RetractPersonRoleOutput,
)

MAX_ROLE_SUGGESTIONS = 8
ASSISTANT_PROVENANCE_KIND = "assistant_action_plan"
EXACT_TERM_NOW_EXISTS = "exact RoleTerm now exists; re-read and reuse that term"
ASSIGNMENT_NO_LONGER_ACTIVE = "role assignment is no longer active"
FROZEN_ROLE_MISMATCH = "frozen role no longer matches the stored RoleTerm"


class PersonRoleAssistantService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._roles = PersonRoleService(session, user_id)

    def get_person_roles(self, person_id: UUID) -> GetPersonRolesOutput:
        person = self._require_active_person(person_id)
        rows = self._session.execute(
            select(PersonRoleAssignment, PersonRoleTerm)
            .join(PersonRoleTerm, PersonRoleTerm.id == PersonRoleAssignment.role_term_id)
            .where(
                PersonRoleAssignment.user_id == self._user_id,
                PersonRoleTerm.user_id == self._user_id,
                PersonRoleAssignment.person_object_id == person.id,
                PersonRoleAssignment.state == ACTIVE_STATE,
            )
            .order_by(
                PersonRoleTerm.normalized_key,
                PersonRoleAssignment.context_key,
                PersonRoleAssignment.id,
            )
            .limit(MAX_ACTIVE_ASSIGNMENTS + 1)
        ).all()
        truncated = len(rows) > MAX_ACTIVE_ASSIGNMENTS
        visible = rows[:MAX_ACTIVE_ASSIGNMENTS]
        return GetPersonRolesOutput(
            person_id=person.id,
            title=person.title or "",
            roles=[
                PersonRoleAssignmentOut(
                    assignment_id=assignment.id,
                    role_term_id=term.id,
                    role=term.display_text,
                    context=assignment.context_text,
                )
                for assignment, term in visible
            ],
            truncated=truncated,
        )

    def find_people_by_role(self, role: str, limit: int) -> FindPeopleByRoleOutput:
        try:
            query, key = role_term_identity(role)
        except PersonRoleTextError as exc:
            raise ValidationError(exc.message) from exc
        searched = self._roles.search(query, limit=MAX_ROLE_SUGGESTIONS)
        exact = self._exact_term(key)
        suggestions = [
            PersonRoleSuggestionOut(role_term_id=term.id, display_text=term.display_text)
            for term in searched.terms
            if exact is None or term.id != exact.id
        ][:MAX_ROLE_SUGGESTIONS]
        if exact is None:
            return FindPeopleByRoleOutput(
                query=query,
                exact_match_term_id=None,
                exact_role=None,
                people=[],
                people_truncated=False,
                suggestions=suggestions,
            )
        people, truncated = self._people_for_term(exact.id, limit)
        return FindPeopleByRoleOutput(
            query=query,
            exact_match_term_id=exact.id,
            exact_role=exact.display_text,
            people=people,
            people_truncated=truncated,
            suggestions=suggestions,
        )

    def prepare_assign(self, payload: AssignPersonRoleInput) -> AssignPersonRoleCanonicalInput:
        self._require_active_person(payload.person_id)
        try:
            context_text, _context_key = role_context_identity(payload.context)
        except PersonRoleTextError as exc:
            raise ValidationError(exc.message) from exc
        operation_id = uuid4()
        if payload.role_term_id is not None:
            term = self._owned_term(payload.role_term_id)
            return AssignPersonRoleCanonicalInput(
                person_id=payload.person_id,
                role_term_id=term.id,
                role=term.display_text,
                context=context_text,
                create_if_missing=False,
                operation_id=operation_id,
            )
        try:
            display, key = role_term_identity(payload.new_role)
        except PersonRoleTextError as exc:
            raise ValidationError(exc.message) from exc
        if self._exact_term(key) is not None:
            raise ValidationError(EXACT_TERM_NOW_EXISTS)
        return AssignPersonRoleCanonicalInput(
            person_id=payload.person_id,
            role_term_id=None,
            role=display,
            context=context_text,
            create_if_missing=True,
            operation_id=operation_id,
        )

    def execute_assign(self, payload: AssignPersonRoleCanonicalInput) -> AssignPersonRoleOutput:
        if payload.create_if_missing:
            role_text = payload.role
        else:
            if payload.role_term_id is None:
                raise ValidationError(FROZEN_ROLE_MISMATCH)
            term = self._owned_term(payload.role_term_id)
            try:
                _display, key = role_term_identity(payload.role)
            except PersonRoleTextError as exc:
                raise ValidationError(exc.message) from exc
            if term.normalized_key != key:
                raise ValidationError(FROZEN_ROLE_MISMATCH)
            role_text = payload.role
        row, changed = self._roles.assign_outcome(
            payload.person_id,
            role_text,
            payload.context,
            origin=AGENT_ORIGIN,
            provenance_kind=ASSISTANT_PROVENANCE_KIND,
            provenance_key=f"aap:{payload.operation_id}",
        )
        stored = self._owned_term(row.role_term_id)
        return AssignPersonRoleOutput(
            person_id=row.person_object_id,
            assignment_id=row.id,
            role_term_id=stored.id,
            role=stored.display_text,
            context=row.context_text,
            changed=changed,
            state=ACTIVE_STATE,
        )

    def prepare_retract(self, payload: RetractPersonRoleInput) -> RetractPersonRoleCanonicalInput:
        self._require_active_person(payload.person_id)
        row = self._owned_assignment(payload.person_id, payload.assignment_id)
        if row.state != ACTIVE_STATE:
            raise ValidationError(ASSIGNMENT_NO_LONGER_ACTIVE)
        term = self._owned_term(row.role_term_id)
        return RetractPersonRoleCanonicalInput(
            person_id=row.person_object_id,
            assignment_id=row.id,
            role_term_id=term.id,
            role=term.display_text,
            context=row.context_text,
            operation_id=uuid4(),
        )

    def execute_retract(self, payload: RetractPersonRoleCanonicalInput) -> RetractPersonRoleOutput:
        row, changed = self._roles.retract_outcome(payload.person_id, payload.assignment_id)
        if row.state != RETRACTED_STATE and changed:
            raise ValidationError(ASSIGNMENT_NO_LONGER_ACTIVE)
        term = self._owned_term(row.role_term_id)
        return RetractPersonRoleOutput(
            person_id=row.person_object_id,
            assignment_id=row.id,
            role_term_id=term.id,
            role=term.display_text,
            context=row.context_text,
            changed=changed,
            state=row.state,
        )

    def _owned_term(self, term_id: UUID) -> PersonRoleTerm:
        term = self._session.get(PersonRoleTerm, term_id)
        if term is None or term.user_id != self._user_id:
            raise NotFoundError("person_role_term", term_id)
        return term

    def _owned_assignment(self, person_id: UUID, assignment_id: UUID) -> PersonRoleAssignment:
        row = self._session.get(PersonRoleAssignment, assignment_id)
        if row is None or row.user_id != self._user_id or row.person_object_id != person_id:
            raise NotFoundError("person_role_assignment", assignment_id)
        return row

    def _exact_term(self, key: str) -> PersonRoleTerm | None:
        return self._session.scalar(
            select(PersonRoleTerm).where(
                PersonRoleTerm.user_id == self._user_id,
                PersonRoleTerm.normalized_key == key,
            )
        )

    def _people_for_term(
        self, term_id: UUID, limit: int
    ) -> tuple[list[PersonRoleMatchOut], bool]:
        selected_people = (
            select(Object.id)
            .join(PersonRoleAssignment, PersonRoleAssignment.person_object_id == Object.id)
            .where(*self._match_filters(term_id))
            .group_by(Object.id, Object.title)
            .order_by(func.lower(Object.title), Object.id)
            .limit(limit + 1)
            .subquery()
        )
        rows = self._session.execute(
            select(PersonRoleAssignment, Object)
            .join(Object, Object.id == PersonRoleAssignment.person_object_id)
            .join(selected_people, selected_people.c.id == Object.id)
            .where(*self._match_filters(term_id))
            .order_by(
                func.lower(Object.title),
                Object.id,
                PersonRoleAssignment.context_key,
                PersonRoleAssignment.id,
            )
        ).all()
        people: list[PersonRoleMatchOut] = []
        index: dict[UUID, PersonRoleMatchOut] = {}
        truncated = False
        for assignment, person in rows:
            current = index.get(person.id)
            if current is None:
                if len(people) >= limit:
                    truncated = True
                    continue
                current = PersonRoleMatchOut(
                    person_id=person.id,
                    title=person.title or "",
                    assignments=[],
                )
                index[person.id] = current
                people.append(current)
            current.assignments.append(
                PersonRoleMatchAssignmentOut(
                    assignment_id=assignment.id,
                    context=assignment.context_text,
                )
            )
        return people, truncated

    def _match_filters(self, term_id: UUID) -> tuple:
        return (
            PersonRoleAssignment.user_id == self._user_id,
            PersonRoleAssignment.role_term_id == term_id,
            PersonRoleAssignment.state == ACTIVE_STATE,
            Object.user_id == self._user_id,
            Object.kind == PERSON_KIND,
            Object.state != REJECTED_STATE,
            object_is_active(),
        )

    def _require_active_person(self, person_id: UUID) -> Object:
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
