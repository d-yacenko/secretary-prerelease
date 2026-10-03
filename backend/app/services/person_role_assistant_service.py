"""Read-only Assistant access to stored Person role facts.

This service does not assign, retract, merge, or infer roles.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Object, PersonRoleAssignment, PersonRoleTerm
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.person_role_text import PersonRoleTextError, role_term_identity
from app.services.errors import NotFoundError, ValidationError
from app.services.person_identity_service import PERSON_KIND
from app.services.person_role_service import (
    ACTIVE_STATE,
    MAX_ACTIVE_ASSIGNMENTS,
    PersonRoleService,
)
from app.services.provenance import REJECTED_STATE
from app.tools.schemas import (
    FindPeopleByRoleOutput,
    GetPersonRolesOutput,
    PersonRoleAssignmentOut,
    PersonRoleMatchAssignmentOut,
    PersonRoleMatchOut,
    PersonRoleSuggestionOut,
)

MAX_ROLE_SUGGESTIONS = 8


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
