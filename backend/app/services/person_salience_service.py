"""Read-time Person salience for already known active People.

This service does not create People, attach identities, call providers, or
change proactive, Task Graph, or Assistant behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select, tuple_
from sqlalchemy.orm import Session, aliased

from app.db.models import Edge, Object, PersonIdentity, PersonIdentityEvidence
from app.domain.object_visibility import is_object_hidden_from_active_reads, object_is_active
from app.domain.person_salience import (
    MAX_ATTENTION_CANDIDATES,
    MAX_DIRECT_HITS,
    MAX_PUBLIC_HITS,
    MAX_RANKED_PEOPLE,
    MAX_SCAN_ROWS,
    MAX_TASK_CANDIDATES,
    TASK_CALENDAR_KINDS,
    USER_ATTENTION_TYPES,
    WINDOW_DAYS,
    InteractionHit,
    PersonSalience,
    attribute_communication,
    communication_identity_keys,
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
        """Rank the union of three bounded candidate sources.

        Sources are recent exact-identity hits from the communication scan,
        newest explicit confirmations then route choices, and newest active
        Person-task/calendar edges. The result is the top of that pool, not a
        slice of the oldest stored rows.
        """
        rows, scan_truncated = self._load_communication()
        index = self._index_for_messages(rows)
        hits, hit_truncated = self._attribute_rows(rows, index)
        attention_ids, attention_truncated = self._attention_candidates()
        task_ids, task_truncated = self._task_candidates()
        pool = {hit.person_id for hit in hits}
        pool.update(attention_ids)
        pool.update(task_ids)
        people = [person_id for person_id in pool if self._is_ranked_person(person_id)]
        if not people:
            return []
        attention = self._attention(people)
        linked = self._task_calendar_people(people)
        pool_truncated = (
            len(people) > MAX_RANKED_PEOPLE
            or scan_truncated
            or hit_truncated
            or attention_truncated
            or task_truncated
        )
        scored = [
            score_person(
                person_id,
                hits,
                now=self._now,
                route_choice=attention.get(person_id, (False, False))[0],
                confirmed=attention.get(person_id, (False, False))[1],
                task_calendar=person_id in linked,
                truncated=pool_truncated,
            )
            for person_id in people
        ]
        scored.sort(key=lambda item: (-item.score, str(item.person_id)))
        return scored[:MAX_RANKED_PEOPLE]

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

    def _index_for_messages(self, rows: list[Object]) -> dict[tuple[str, str, str], UUID]:
        keys: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            metadata = row.metadata_ if isinstance(row.metadata_, dict) else {}
            for key in communication_identity_keys(provider=row.provider, metadata=metadata):
                if key in seen:
                    continue
                seen.add(key)
                keys.append(key)
        if not keys:
            return {}
        matched = self._session.scalars(
            select(PersonIdentity).where(
                PersonIdentity.user_id == self._user_id,
                PersonIdentity.state != REJECTED_STATE,
                tuple_(
                    PersonIdentity.identity_type,
                    PersonIdentity.realm,
                    PersonIdentity.canonical_value,
                ).in_(keys),
            )
        )
        index: dict[tuple[str, str, str], UUID] = {}
        for row in matched:
            person = self._session.get(Object, row.person_object_id)
            if person is None or not _active_person(person):
                continue
            index[(row.identity_type, row.realm, row.canonical_value)] = row.person_object_id
        return index

    def _is_ranked_person(self, person_id: UUID) -> bool:
        person = self._session.get(Object, person_id)
        return (
            person is not None
            and person.user_id == self._user_id
            and _active_person(person)
        )

    def _attention_candidates(self) -> tuple[set[UUID], bool]:
        confirmed_first = case(
            (PersonIdentityEvidence.evidence_type == "user_confirmed", 0),
            else_=1,
        )
        best = (
            select(
                PersonIdentityEvidence.person_object_id.label("person_id"),
                confirmed_first.label("priority"),
                PersonIdentityEvidence.created_at.label("created_at"),
                PersonIdentityEvidence.id.label("evidence_id"),
            )
            .join(Object, Object.id == PersonIdentityEvidence.person_object_id)
            .where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type.in_(tuple(USER_ATTENTION_TYPES)),
                Object.user_id == self._user_id,
                Object.kind == PERSON_KIND,
                Object.state != REJECTED_STATE,
                object_is_active(),
            )
            .distinct(PersonIdentityEvidence.person_object_id)
            .order_by(
                PersonIdentityEvidence.person_object_id,
                confirmed_first,
                PersonIdentityEvidence.created_at.desc(),
                PersonIdentityEvidence.id.desc(),
            )
            .subquery()
        )
        rows = list(
            self._session.scalars(
                select(best.c.person_id)
                .order_by(best.c.priority, best.c.created_at.desc(), best.c.evidence_id.desc())
                .limit(MAX_ATTENTION_CANDIDATES + 1)
            )
        )
        truncated = len(rows) > MAX_ATTENTION_CANDIDATES
        return set(rows[:MAX_ATTENTION_CANDIDATES]), truncated

    def _task_candidates(self) -> tuple[set[UUID], bool]:
        source = aliased(Object)
        target = aliased(Object)
        person_to_work = and_(
            source.kind == PERSON_KIND,
            target.kind.in_(tuple(TASK_CALENDAR_KINDS)),
        )
        work_to_person = and_(
            target.kind == PERSON_KIND,
            source.kind.in_(tuple(TASK_CALENDAR_KINDS)),
        )
        person_id = case((source.kind == PERSON_KIND, source.id), else_=target.id)
        best = (
            select(
                person_id.label("person_id"),
                Edge.updated_at.label("updated_at"),
                Edge.created_at.label("created_at"),
                Edge.id.label("edge_id"),
            )
            .join(source, source.id == Edge.source_id)
            .join(target, target.id == Edge.target_id)
            .where(
                Edge.user_id == self._user_id,
                Edge.state != REJECTED_STATE,
                source.user_id == self._user_id,
                target.user_id == self._user_id,
                source.state != REJECTED_STATE,
                target.state != REJECTED_STATE,
                object_is_active(source),
                object_is_active(target),
                or_(person_to_work, work_to_person),
            )
            .distinct(person_id)
            .order_by(
                person_id,
                Edge.updated_at.desc(),
                Edge.created_at.desc(),
                Edge.id.desc(),
            )
            .subquery()
        )
        rows = list(
            self._session.scalars(
                select(best.c.person_id)
                .order_by(best.c.updated_at.desc(), best.c.created_at.desc(), best.c.edge_id.desc())
                .limit(MAX_TASK_CANDIDATES + 1)
            )
        )
        truncated = len(rows) > MAX_TASK_CANDIDATES
        return set(rows[:MAX_TASK_CANDIDATES]), truncated

    def _hits(
        self, identity_index: dict[tuple[str, str, str], UUID]
    ) -> tuple[list[InteractionHit], bool]:
        if not identity_index:
            return [], False
        rows, scan_truncated = self._load_communication()
        hits, hit_truncated = self._attribute_rows(rows, identity_index)
        return hits, scan_truncated or hit_truncated

    def _load_communication(self) -> tuple[list[Object], bool]:
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
                .limit(MAX_SCAN_ROWS + 1)
            )
        )
        return rows[:MAX_SCAN_ROWS], len(rows) > MAX_SCAN_ROWS

    def _attribute_rows(
        self,
        rows: list[Object],
        identity_index: dict[tuple[str, str, str], UUID],
    ) -> tuple[list[InteractionHit], bool]:
        hits: list[InteractionHit] = []
        direct_kept: dict[UUID, int] = {}
        public_kept: dict[UUID, int] = {}
        hit_truncated = False
        for row in rows:
            metadata = row.metadata_ if isinstance(row.metadata_, dict) else {}
            occurred = row.occurred_at or row.created_at
            if occurred is None:
                continue
            for hit in attribute_communication(
                provider=row.provider,
                metadata=metadata,
                occurred_at=occurred,
                identity_index=identity_index,
            ):
                if hit.exposure == "direct":
                    kept = direct_kept.get(hit.person_id, 0)
                    if kept >= MAX_DIRECT_HITS:
                        hit_truncated = True
                        continue
                    direct_kept[hit.person_id] = kept + 1
                else:
                    kept = public_kept.get(hit.person_id, 0)
                    if kept >= MAX_PUBLIC_HITS:
                        hit_truncated = True
                        continue
                    public_kept[hit.person_id] = kept + 1
                hits.append(hit)
        return hits, hit_truncated

    def _attention(self, people: list[UUID]) -> dict[UUID, tuple[bool, bool]]:
        if not people:
            return {}
        rows = self._session.execute(
            select(
                PersonIdentityEvidence.person_object_id,
                func.bool_or(PersonIdentityEvidence.evidence_type == "user_route_choice"),
                func.bool_or(PersonIdentityEvidence.evidence_type == "user_confirmed"),
            )
            .where(
                PersonIdentityEvidence.user_id == self._user_id,
                PersonIdentityEvidence.person_object_id.in_(people),
                PersonIdentityEvidence.state == "active",
                PersonIdentityEvidence.evidence_type.in_(tuple(USER_ATTENTION_TYPES)),
            )
            .group_by(PersonIdentityEvidence.person_object_id)
        )
        return {
            person_id: (bool(route_choice), bool(confirmed))
            for person_id, route_choice, confirmed in rows
        }

    def _task_calendar_people(self, people: list[UUID]) -> set[UUID]:
        if not people:
            return set()
        source = aliased(Object)
        target = aliased(Object)
        person_to_work = and_(
            source.kind == PERSON_KIND,
            target.kind.in_(tuple(TASK_CALENDAR_KINDS)),
            source.id.in_(people),
        )
        work_to_person = and_(
            target.kind == PERSON_KIND,
            source.kind.in_(tuple(TASK_CALENDAR_KINDS)),
            target.id.in_(people),
        )
        person_id = case((source.kind == PERSON_KIND, source.id), else_=target.id)
        rows = self._session.scalars(
            select(person_id)
            .select_from(Edge)
            .join(source, source.id == Edge.source_id)
            .join(target, target.id == Edge.target_id)
            .where(
                Edge.user_id == self._user_id,
                Edge.state != REJECTED_STATE,
                source.user_id == self._user_id,
                target.user_id == self._user_id,
                source.state != REJECTED_STATE,
                target.state != REJECTED_STATE,
                object_is_active(source),
                object_is_active(target),
                or_(person_to_work, work_to_person),
            )
            .distinct()
        )
        return set(rows)


def _active_person(person: Object) -> bool:
    return (
        person.kind == PERSON_KIND
        and person.state != REJECTED_STATE
        and not is_object_hidden_from_active_reads(person)
    )


def _active_person_object(obj: Object) -> bool:
    return obj.state != REJECTED_STATE and not is_object_hidden_from_active_reads(obj)
