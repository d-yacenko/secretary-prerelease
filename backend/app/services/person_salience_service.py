"""Read-time Person salience for already known active People.

This service does not create People, attach identities, call providers, or
change proactive, Task Graph, or Assistant behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Edge, Object, PersonIdentity, PersonIdentityEvidence
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.person_salience import (
    MAX_COMMUNICATION_ROWS,
    MAX_GRAPH_EDGES,
    MAX_RANKED_PEOPLE,
    TASK_CALENDAR_KINDS,
    USER_ATTENTION_TYPES,
    WINDOW_DAYS,
    InteractionHit,
    PersonSalience,
    attribute_communication,
    empty_salience,
    score_person,
)
from app.services.errors import NotFoundError
from app.services.person_identity_service import PERSON_KIND
from app.services.provenance import REJECTED_STATE

_COMMUNICATION_KINDS = ("email", "chat_message")


class PersonSalienceService:
    def __init__(self, session: Session, user_id: UUID, *, now: datetime | None = None) -> None:
        self._session = session
        self._user_id = user_id
        self._now = now or datetime.now(UTC)

    def evaluate(self, person_id: UUID) -> PersonSalience:
        person = self._session.get(Object, person_id)
        if person is None or person.user_id != self._user_id or person.kind != PERSON_KIND:
            raise NotFoundError("person", person_id)
        if not _active_person(person):
            return empty_salience(person_id, eligible=False)
        index = self._identity_index([person_id])
        hits, truncated = self._hits(index)
        attention = self._attention([person_id])
        linked = self._task_calendar_people([person_id])
        route_choice, confirmed = attention.get(person_id, (False, False))
        return score_person(
            person_id,
            hits,
            now=self._now,
            route_choice=route_choice,
            confirmed=confirmed,
            task_calendar=person_id in linked,
            truncated=truncated,
        )

    def rank(self) -> list[PersonSalience]:
        people = self._active_people()
        if not people:
            return []
        index = self._identity_index(people)
        hits, truncated = self._hits(index)
        attention = self._attention(people)
        linked = self._task_calendar_people(people)
        scored = [
            score_person(
                person_id,
                hits,
                now=self._now,
                route_choice=attention.get(person_id, (False, False))[0],
                confirmed=attention.get(person_id, (False, False))[1],
                task_calendar=person_id in linked,
                truncated=truncated,
            )
            for person_id in people
        ]
        scored.sort(key=lambda item: (-item.score, str(item.person_id)))
        return scored[:MAX_RANKED_PEOPLE]

    def _active_people(self) -> list[UUID]:
        rows = self._session.scalars(
            select(Object)
            .where(
                Object.user_id == self._user_id,
                Object.kind == PERSON_KIND,
                Object.state != REJECTED_STATE,
                object_is_active(),
            )
            .order_by(Object.created_at, Object.id)
            .limit(MAX_RANKED_PEOPLE)
        )
        return [row.id for row in rows]

    def _identity_index(self, people: list[UUID]) -> dict[tuple[str, str, str], UUID]:
        rows = self._session.scalars(
            select(PersonIdentity).where(
                PersonIdentity.user_id == self._user_id,
                PersonIdentity.person_object_id.in_(people),
                PersonIdentity.state != REJECTED_STATE,
            )
        )
        index: dict[tuple[str, str, str], UUID] = {}
        for row in rows:
            person = self._session.get(Object, row.person_object_id)
            if person is None or not _active_person(person):
                continue
            index[(row.identity_type, row.realm, row.canonical_value)] = row.person_object_id
        return index

    def _hits(
        self, identity_index: dict[tuple[str, str, str], UUID]
    ) -> tuple[list[InteractionHit], bool]:
        if not identity_index:
            return [], False
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
                .limit(MAX_COMMUNICATION_ROWS + 1)
            )
        )
        truncated = len(rows) > MAX_COMMUNICATION_ROWS
        hits: list[InteractionHit] = []
        for row in rows[:MAX_COMMUNICATION_ROWS]:
            metadata = row.metadata_ if isinstance(row.metadata_, dict) else {}
            occurred = row.occurred_at or row.created_at
            if occurred is None:
                continue
            hits.extend(
                attribute_communication(
                    provider=row.provider,
                    metadata=metadata,
                    occurred_at=occurred,
                    identity_index=identity_index,
                )
            )
        return hits, truncated

    def _attention(self, people: list[UUID]) -> dict[UUID, tuple[bool, bool]]:
        rows = self._session.scalars(
            select(PersonIdentityEvidence)
            .where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id.in_(people),
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type.in_(tuple(USER_ATTENTION_TYPES)),
            )
            .limit(MAX_COMMUNICATION_ROWS)
        )
        found: dict[UUID, tuple[bool, bool]] = {}
        for row in rows:
            route, confirmed = found.get(row.person_object_id, (False, False))
            if row.evidence_type == "user_route_choice":
                route = True
            if row.evidence_type == "user_confirmed":
                confirmed = True
            found[row.person_object_id] = (route, confirmed)
        return found

    def _task_calendar_people(self, people: list[UUID]) -> set[UUID]:
        rows = list(
            self._session.scalars(
                select(Edge)
                .where(
                    Edge.user_id == self._user_id,
                    Edge.state != REJECTED_STATE,
                    or_(Edge.source_id.in_(people), Edge.target_id.in_(people)),
                )
                .limit(MAX_GRAPH_EDGES + 1)
            )
        )
        linked: set[UUID] = set()
        for edge in rows[:MAX_GRAPH_EDGES]:
            for person_id, other_id in (
                (edge.source_id, edge.target_id),
                (edge.target_id, edge.source_id),
            ):
                if person_id not in people:
                    continue
                other = self._session.get(Object, other_id)
                if other is None or other.user_id != self._user_id:
                    continue
                if other.kind not in TASK_CALENDAR_KINDS or not _active_person_object(other):
                    continue
                linked.add(person_id)
        return linked


def _active_person(person: Object) -> bool:
    return (
        person.kind == PERSON_KIND
        and person.state != REJECTED_STATE
        and not is_object_hidden_from_active_reads(person)
    )


def _active_person_object(obj: Object) -> bool:
    return obj.state != REJECTED_STATE and not is_object_hidden_from_active_reads(obj)
