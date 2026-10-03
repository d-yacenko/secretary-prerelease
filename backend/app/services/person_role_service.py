"""Emergent per-user Person role vocabulary and manual assignments."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Object, PersonRoleAssignment, PersonRoleTerm
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.domain.person_role_text import (
    PersonRoleTextError,
    collapse_role_text,
    role_context_identity,
    role_search_key,
    role_term_identity,
)
from app.services.errors import NotFoundError, ValidationError
from app.services.person_identity_service import PERSON_KIND
from app.services.provenance import REJECTED_STATE

ACTIVE_STATE = "active"
RETRACTED_STATE = "retracted"
MANUAL_ORIGIN = "user"
MANUAL_PROVENANCE_KIND = "user_manual"
MANUAL_PROVENANCE_KEY = "user_manual"
MAX_ACTIVE_ASSIGNMENTS = 16
SEARCH_DEFAULT_LIMIT = 8
SEARCH_MAX_LIMIT = 20


class PersonRoleService:
    def __init__(self, session: Session, user_id: uuid.UUID) -> None:
        self._session = session
        self._user_id = user_id

    def search(self, query: str | None, limit: int = SEARCH_DEFAULT_LIMIT) -> list[PersonRoleTerm]:
        bounded = min(max(limit, 1), SEARCH_MAX_LIMIT)
        stmt = select(PersonRoleTerm).where(PersonRoleTerm.user_id == self._user_id)
        key = role_search_key(query)
        if query and collapse_role_text(query) and key is None:
            return []
        if key:
            stmt = stmt.where(PersonRoleTerm.normalized_key.contains(key, autoescape=True))
        stmt = stmt.order_by(PersonRoleTerm.normalized_key, PersonRoleTerm.id).limit(bounded)
        return list(self._session.scalars(stmt))

    def assign(
        self, person_id: uuid.UUID, role: str, context: str | None = None
    ) -> PersonRoleAssignment:
        try:
            display, key = role_term_identity(role)
            context_text, context_key = role_context_identity(context)
        except PersonRoleTextError as exc:
            raise ValidationError(exc.message) from exc
        self._require_person(person_id)
        existing = self._active_assignment(person_id, key, context_key)
        if existing is not None:
            return existing
        if self._active_count(person_id) >= MAX_ACTIVE_ASSIGNMENTS:
            raise ValidationError("active role assignment cap reached")
        nested = self._session.begin_nested()
        try:
            term = self._reuse_or_create_term(display, key)
            row = PersonRoleAssignment(
                user_id=self._user_id,
                person_object_id=person_id,
                role_term_id=term.id,
                context_text=context_text,
                context_key=context_key,
                origin=MANUAL_ORIGIN,
                state=ACTIVE_STATE,
                provenance_kind=MANUAL_PROVENANCE_KIND,
                provenance_key=MANUAL_PROVENANCE_KEY,
            )
            self._session.add(row)
            self._session.flush()
            nested.commit()
        except IntegrityError:
            nested.rollback()
            raced = self._active_assignment(person_id, key, context_key)
            if raced is not None:
                return raced
            raise
        except Exception:
            nested.rollback()
            raise
        return row

    def retract(self, person_id: uuid.UUID, assignment_id: uuid.UUID) -> PersonRoleAssignment:
        row = self._session.get(PersonRoleAssignment, assignment_id)
        if row is None or row.user_id != self._user_id or row.person_object_id != person_id:
            raise NotFoundError("person_role_assignment", assignment_id)
        self._require_person(person_id)
        if row.state == RETRACTED_STATE:
            return row
        row.state = RETRACTED_STATE
        row.retracted_at = datetime.now(UTC)
        self._session.flush()
        return row

    def active_for_people(self, person_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
        grouped: dict[uuid.UUID, list[dict]] = {person_id: [] for person_id in person_ids}
        if not person_ids:
            return grouped
        rows = self._session.execute(
            select(PersonRoleAssignment, PersonRoleTerm)
            .join(PersonRoleTerm, PersonRoleTerm.id == PersonRoleAssignment.role_term_id)
            .where(
                PersonRoleAssignment.user_id == self._user_id,
                PersonRoleTerm.user_id == self._user_id,
                PersonRoleAssignment.person_object_id.in_(person_ids),
                PersonRoleAssignment.state == ACTIVE_STATE,
            )
            .order_by(
                func.lower(PersonRoleTerm.display_text),
                PersonRoleAssignment.context_key,
                PersonRoleAssignment.id,
            )
        ).all()
        for assignment, term in rows:
            grouped.setdefault(assignment.person_object_id, []).append(
                _assignment_payload(assignment, term)
            )
        return grouped

    def _require_person(self, person_id: uuid.UUID) -> Object:
        person = self._session.get(Object, person_id)
        if person is None or person.user_id != self._user_id:
            raise NotFoundError("person", person_id)
        if (
            person.kind != PERSON_KIND
            or person.state == REJECTED_STATE
            or is_object_hidden_from_active_reads(person)
        ):
            raise ValidationError("person is not an active person")
        return person

    def _reuse_or_create_term(self, display: str, key: str) -> PersonRoleTerm:
        term = self._session.scalar(
            select(PersonRoleTerm).where(
                PersonRoleTerm.user_id == self._user_id,
                PersonRoleTerm.normalized_key == key,
            )
        )
        if term is not None:
            return term
        term = PersonRoleTerm(
            user_id=self._user_id,
            display_text=display,
            normalized_key=key,
        )
        self._session.add(term)
        self._session.flush()
        return term

    def _active_assignment(
        self,
        person_id: uuid.UUID,
        role_key: str,
        context_key: str,
    ) -> PersonRoleAssignment | None:
        return self._session.scalar(
            select(PersonRoleAssignment)
            .join(PersonRoleTerm, PersonRoleTerm.id == PersonRoleAssignment.role_term_id)
            .where(
                PersonRoleAssignment.user_id == self._user_id,
                PersonRoleAssignment.person_object_id == person_id,
                PersonRoleAssignment.state == ACTIVE_STATE,
                PersonRoleAssignment.context_key == context_key,
                PersonRoleTerm.user_id == self._user_id,
                PersonRoleTerm.normalized_key == role_key,
            )
        )

    def _active_count(self, person_id: uuid.UUID) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(PersonRoleAssignment)
                .where(
                    PersonRoleAssignment.user_id == self._user_id,
                    PersonRoleAssignment.person_object_id == person_id,
                    PersonRoleAssignment.state == ACTIVE_STATE,
                )
            )
            or 0
        )


def _assignment_payload(assignment: PersonRoleAssignment, term: PersonRoleTerm) -> dict:
    return {
        "id": assignment.id,
        "person_id": assignment.person_object_id,
        "role_term_id": term.id,
        "role_display_text": term.display_text,
        "context": assignment.context_text,
        "origin": assignment.origin,
        "state": assignment.state,
    }
