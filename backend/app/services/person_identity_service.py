"""Canonical Person objects and exact provider-identity links.

Conflicting exact identities are reported. This service does not merge People
and does not call a provider or a model.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import ObjectCreate
from app.db.models import Object, PersonIdentity
from app.domain.person_identity import NormalizedPersonIdentity
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE, USER_ORIGIN

PERSON_KIND = "person"
IDENTITY_CONFLICT = "person_identity_conflict"
_MAX_TITLE_CHARS = 200


class PersonIdentityService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._graph = GraphService(session, user_id)

    def create_person(self, title: str) -> Object:
        cleaned = title.strip()
        if not cleaned or len(cleaned) > _MAX_TITLE_CHARS:
            raise ValidationError("person title is required")
        return self._graph.create_object(
            ObjectCreate(
                kind=PERSON_KIND,
                title=cleaned,
                origin=USER_ORIGIN,
                state=CONFIRMED_STATE,
            )
        )

    def attach(self, person_id: UUID, identity: NormalizedPersonIdentity) -> PersonIdentity:
        self._require_person(person_id)
        existing = self._active_identity(identity)
        if existing is not None:
            if existing.person_object_id == person_id:
                return existing
            raise ConflictError(IDENTITY_CONFLICT)
        row = PersonIdentity(
            user_id=self._user_id,
            person_object_id=person_id,
            identity_type=identity.identity_type,
            provider=identity.provider,
            realm=identity.realm,
            canonical_value=identity.canonical_value,
            display_value=identity.display_value,
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
            confidence=1.0,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            raise ConflictError(IDENTITY_CONFLICT) from exc
        return row

    def resolve(self, identity: NormalizedPersonIdentity) -> Object | None:
        row = self._active_identity(identity)
        if row is None:
            return None
        person = self._session.get(Object, row.person_object_id)
        if person is None or person.user_id != self._user_id or person.kind != PERSON_KIND:
            return None
        return person

    def list_identities(self, person_id: UUID) -> list[PersonIdentity]:
        self._require_person(person_id)
        rows = self._session.scalars(
            select(PersonIdentity)
            .where(
                PersonIdentity.user_id == self._user_id,
                PersonIdentity.person_object_id == person_id,
                PersonIdentity.state != REJECTED_STATE,
            )
            .order_by(
                PersonIdentity.provider,
                PersonIdentity.identity_type,
                PersonIdentity.canonical_value,
            )
        )
        return list(rows)

    def detach(self, identity_id: UUID) -> PersonIdentity:
        row = self._require_identity(identity_id)
        row.state = REJECTED_STATE
        self._session.flush()
        return row

    def reassign(self, identity_id: UUID, person_id: UUID) -> PersonIdentity:
        row = self._require_identity(identity_id)
        self._require_person(person_id)
        if row.person_object_id == person_id and row.state != REJECTED_STATE:
            return row
        identity = NormalizedPersonIdentity(
            identity_type=row.identity_type,
            provider=row.provider,
            realm=row.realm,
            canonical_value=row.canonical_value,
            display_value=row.display_value,
        )
        holder = self._active_identity(identity)
        if holder is not None and holder.id != row.id:
            raise ConflictError(IDENTITY_CONFLICT)
        row.state = REJECTED_STATE
        self._session.flush()
        return self.attach(person_id, identity)

    def _require_person(self, person_id: UUID) -> Object:
        person = self._session.get(Object, person_id)
        if person is None or person.user_id != self._user_id:
            raise NotFoundError("person", person_id)
        if person.kind != PERSON_KIND:
            raise ValidationError("identity target must be a person")
        return person

    def _require_identity(self, identity_id: UUID) -> PersonIdentity:
        row = self._session.get(PersonIdentity, identity_id)
        if row is None or row.user_id != self._user_id:
            raise NotFoundError("person_identity", identity_id)
        return row

    def _active_identity(self, identity: NormalizedPersonIdentity) -> PersonIdentity | None:
        return self._session.scalar(
            select(PersonIdentity).where(
                PersonIdentity.user_id == self._user_id,
                PersonIdentity.provider == identity.provider,
                PersonIdentity.identity_type == identity.identity_type,
                PersonIdentity.realm == identity.realm,
                PersonIdentity.canonical_value == identity.canonical_value,
                PersonIdentity.state != REJECTED_STATE,
            )
        )
