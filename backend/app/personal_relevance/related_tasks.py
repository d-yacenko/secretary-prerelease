"""Bounded confirmed Task actor context for Personal Relevance evidence.

Selection is a factual union of explicit actor links. It does not rank Tasks
by role text, due date, or actor role.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Edge, Object
from app.domain.object_visibility import object_is_active
from app.domain.task_lifecycle import TERMINAL_TASK_STATUSES_FOR_READS
from app.domain.task_relations import DELEGATED_TO, INVOLVES, REQUESTED_BY, WAITING_ON
from app.personal_relevance.models import (
    PERSONAL_RELEVANCE_MAX_RELATED_TASKS_PER_OBJECT,
    PERSONAL_RELEVANCE_MAX_TITLE_CHARS,
    RelatedActiveTaskEvidence,
    RelatedTaskActorEvidence,
)
from app.services.provenance import CONFIRMED_STATE

ACTOR_ROLE_ORDER = (REQUESTED_BY, DELEGATED_TO, WAITING_ON, INVOLVES)
_CANDIDATE_LIMIT = PERSONAL_RELEVANCE_MAX_RELATED_TASKS_PER_OBJECT + 1


@dataclass(frozen=True)
class RelatedTaskIndex:
    tasks_by_person: dict[UUID, frozenset[UUID]]
    tasks: dict[UUID, Object]
    links: dict[UUID, frozenset[tuple[UUID, str]]]

    @classmethod
    def empty(cls) -> RelatedTaskIndex:
        return cls(tasks_by_person={}, tasks={}, links={})


def load_related_task_index(
    session: Session,
    user_id: UUID,
    person_ids: Sequence[UUID],
) -> RelatedTaskIndex:
    unique = list(dict.fromkeys(person_ids))
    if not unique:
        return RelatedTaskIndex.empty()
    qualifying = (
        select(Edge.target_id.label("person_id"), Object.id.label("task_id"))
        .join(Object, Object.id == Edge.source_id)
        .where(*_task_actor_filters(user_id, unique))
        .group_by(Edge.target_id, Object.id)
        .subquery()
    )
    ranked = select(
        qualifying.c.person_id,
        qualifying.c.task_id,
        func.row_number()
        .over(partition_by=qualifying.c.person_id, order_by=qualifying.c.task_id.asc())
        .label("rn"),
    ).subquery()
    kept_tasks = (
        select(ranked.c.task_id)
        .where(ranked.c.rn <= _CANDIDATE_LIMIT)
        .distinct()
    )
    rows = session.execute(
        select(Edge, Object)
        .prefix_with("/* rel1b_related_tasks */")
        .join(Object, Object.id == Edge.source_id)
        .where(
            *_task_actor_filters(user_id, unique),
            Edge.source_id.in_(kept_tasks),
        )
    ).all()
    tasks_by_person: dict[UUID, set[UUID]] = {}
    tasks: dict[UUID, Object] = {}
    links: dict[UUID, set[tuple[UUID, str]]] = {}
    for edge, task in rows:
        tasks_by_person.setdefault(edge.target_id, set()).add(task.id)
        tasks[task.id] = task
        links.setdefault(task.id, set()).add((edge.target_id, edge.type))
    return RelatedTaskIndex(
        tasks_by_person={key: frozenset(value) for key, value in tasks_by_person.items()},
        tasks=tasks,
        links={key: frozenset(value) for key, value in links.items()},
    )


def related_tasks_for_people(
    index: RelatedTaskIndex,
    person_ids: Sequence[UUID],
) -> tuple[tuple[RelatedActiveTaskEvidence, ...], bool]:
    grounded = list(dict.fromkeys(person_ids))
    grounded_set = set(grounded)
    candidate: set[UUID] = set()
    truncated = False
    for person_id in grounded:
        found = index.tasks_by_person.get(person_id, frozenset())
        if len(found) > PERSONAL_RELEVANCE_MAX_RELATED_TASKS_PER_OBJECT:
            truncated = True
        candidate.update(found)
    ordered = sorted(candidate, key=lambda item: item.bytes)
    if len(ordered) > PERSONAL_RELEVANCE_MAX_RELATED_TASKS_PER_OBJECT:
        truncated = True
    kept = ordered[:PERSONAL_RELEVANCE_MAX_RELATED_TASKS_PER_OBJECT]
    evidence: list[RelatedActiveTaskEvidence] = []
    for task_id in kept:
        task = index.tasks[task_id]
        actor_links = tuple(
            RelatedTaskActorEvidence(person_id=person_id, actor_role=role)
            for person_id, role in sorted(
                (
                    item
                    for item in index.links.get(task_id, ())
                    if item[0] in grounded_set and item[1] in ACTOR_ROLE_ORDER
                ),
                key=lambda item: (item[0].bytes, ACTOR_ROLE_ORDER.index(item[1])),
            )
        )
        evidence.append(
            RelatedActiveTaskEvidence(
                task_id=task.id,
                title=(task.title or "")[:PERSONAL_RELEVANCE_MAX_TITLE_CHARS],
                status=task.status,
                start_at=task.start_at,
                due_at=task.due_at,
                planned_start_at=task.planned_start_at,
                planned_end_at=task.planned_end_at,
                actor_links=actor_links,
            )
        )
    return tuple(evidence), truncated


def _task_actor_filters(user_id: UUID, person_ids: Sequence[UUID]) -> tuple:
    return (
        Edge.user_id == user_id,
        Edge.type.in_(ACTOR_ROLE_ORDER),
        Edge.state == CONFIRMED_STATE,
        Edge.target_id.in_(list(person_ids)),
        Object.user_id == user_id,
        Object.kind == "task",
        Object.state == CONFIRMED_STATE,
        object_is_active(),
        or_(Object.status.is_(None), Object.status.notin_(tuple(TERMINAL_TASK_STATUSES_FOR_READS))),
    )
