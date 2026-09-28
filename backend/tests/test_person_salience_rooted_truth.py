"""Rooted salience uses the communication truth bound; overview rank does not."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Object, User
from app.domain.person_assistant import MAX_PERSON_SCAN_ROWS
from app.domain.person_identity import normalize_email
from app.domain.person_salience import MAX_SCAN_ROWS
from app.services.graph_service import GraphService
from app.services.person_graph_workspace_service import PersonGraphWorkspaceService
from app.services.person_identity_service import PersonIdentityService
from app.services.person_salience_service import PersonSalienceService
from app.services.provenance import CONFIRMED_STATE, USER_ORIGIN

COMM = ("directness", "reciprocity", "frequency", "recency", "public_exposure")


def test_rooted_salience_includes_rows_through_the_communication_bound(db_session) -> None:
    assert MAX_SCAN_ROWS == 200
    assert MAX_PERSON_SCAN_ROWS == 400
    row_200 = _rooted(db_session, newer=199)
    row_201 = _rooted(db_session, newer=200)
    row_400 = _rooted(db_session, newer=399)
    row_401 = _rooted(db_session, newer=400)
    inside_but_truncated = _rooted(db_session, newer=399, older=1)

    assert row_200["directness"] > 0
    assert row_200["truncated"] is False
    assert row_200["count"] == 1
    assert row_201["directness"] > 0
    assert row_201["truncated"] is False
    assert row_201["count"] == 1
    assert row_400["directness"] > 0
    assert row_400["truncated"] is False
    assert row_400["count"] == 1
    assert row_401["directness"] == 0
    assert all(row_401[name] == 0 for name in COMM)
    assert row_401["truncated"] is True
    assert row_401["count"] == 0
    assert inside_but_truncated["directness"] > 0
    assert inside_but_truncated["truncated"] is True
    assert inside_but_truncated["count"] == 1


def test_overview_rank_stays_on_the_200_row_scan(db_session) -> None:
    visible = _person_with_mail(db_session, newer=199)
    hidden = _person_with_mail(db_session, newer=200)
    visible_rank = PersonSalienceService(db_session, visible[0]).rank()
    hidden_rank = PersonSalienceService(db_session, hidden[0]).rank()
    generic = PersonSalienceService(db_session, hidden[0]).evaluate(hidden[1].id)
    rooted = PersonSalienceService(db_session, hidden[0]).evaluate_rooted(hidden[1].id)
    assert visible[1].id in {item.person_id for item in visible_rank}
    assert (
        _value(next(item for item in visible_rank if item.person_id == visible[1].id), "directness")
        > 0
    )
    assert hidden[1].id not in {item.person_id for item in hidden_rank}
    assert _value(generic, "directness") == 0
    assert generic.row_limit == MAX_SCAN_ROWS
    assert _value(rooted, "directness") > 0
    assert rooted.row_limit == MAX_PERSON_SCAN_ROWS


def test_yandex_attribution_is_unchanged_on_the_rooted_scan(db_session) -> None:
    inbox = _single(
        db_session, {"folder": "inbox", "sender": "ada@example.com", "to": "me@example.com"}
    )
    several = _single(
        db_session,
        {
            "folder": "inbox",
            "sender": "ada@example.com",
            "to": ["me@example.com", "other@example.com"],
        },
    )
    archive = _single(
        db_session,
        {"folder": "Archive", "sender": "ada@example.com", "to": "me@example.com"},
    )
    assert inbox["directness"] > 0
    assert inbox["count"] == 1
    assert several["directness"] == 0
    assert several["public_exposure"] > 0
    assert several["count"] == 1
    assert archive["count"] == 0
    assert all(archive[name] == 0 for name in COMM)


def test_task_calendar_still_requires_an_explicit_edge(db_session) -> None:
    mentioned = _work(db_session, linked=False)
    linked = _work(db_session, linked=True)
    assert mentioned["task_calendar"] == 0
    assert mentioned["involvement"] == []
    assert linked["task_calendar"] == 16
    assert len(linked["involvement"]) == 1


def _rooted(db_session, *, newer: int, older: int = 0) -> dict:
    user_id, person = _person_with_mail(db_session, newer=newer, older=older)
    card = _card(db_session, user_id, person.id)
    service = PersonSalienceService(db_session, user_id)
    rooted = service.evaluate_rooted(person.id)
    assert card["truncated"] is rooted.truncated
    assert card["directness"] == _value(rooted, "directness")
    return card


def _person_with_mail(db_session, *, newer: int, older: int = 0):
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Ada")
    PersonIdentityService(db_session, user_id).attach(person.id, normalize_email("ada@example.com"))
    now = datetime.now(UTC)
    base = now - timedelta(hours=3)
    for index in range(newer):
        _mail(
            db_session,
            user_id,
            when=base + timedelta(seconds=newer - index),
            metadata={
                "folder": "inbox",
                "sender": f"noise-{index}@example.com",
                "to": "me@example.com",
            },
        )
    _mail(
        db_session,
        user_id,
        when=base - timedelta(minutes=5),
        metadata={"folder": "inbox", "sender": "ada@example.com", "to": "me@example.com"},
    )
    for index in range(older):
        _mail(
            db_session,
            user_id,
            when=base - timedelta(hours=2, seconds=index + 1),
            metadata={
                "folder": "inbox",
                "sender": f"old-{index}@example.com",
                "to": "me@example.com",
            },
        )
    return user_id, person


def _single(db_session, metadata: dict) -> dict:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Ada")
    PersonIdentityService(db_session, user_id).attach(person.id, normalize_email("ada@example.com"))
    _mail(db_session, user_id, when=datetime.now(UTC) - timedelta(hours=1), metadata=metadata)
    return _card(db_session, user_id, person.id)


def _work(db_session, *, linked: bool) -> dict:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Ada")
    PersonIdentityService(db_session, user_id).attach(person.id, normalize_email("ada@example.com"))
    graph = GraphService(db_session, user_id)
    task = graph.create_object(
        ObjectCreate(
            kind="task",
            title="mail ada@example.com",
            body="ada@example.com",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
            status="open",
        )
    )
    if linked:
        graph.create_edge(
            EdgeCreate(
                source_id=task.id,
                target_id=person.id,
                type="involves",
                origin=USER_ORIGIN,
                state=CONFIRMED_STATE,
            )
        )
    return _card(db_session, user_id, person.id)


def _card(db_session, user_id, person_id) -> dict:
    rooted = PersonGraphWorkspaceService(db_session, user_id).get_workspace(root_id=person_id)
    person = next(item for item in rooted.people if item["person_id"] == person_id)
    values = {item["name"]: item["value"] for item in person["salience"]["components"]}
    return {
        "count": person["recent_communication_count"],
        "truncated": person["salience"]["truncated"],
        "involvement": person["task_involvement"],
        **{name: values.get(name, 0) for name in (*COMM, "task_calendar")},
    }


def _value(salience, name: str) -> int:
    return next(item.value for item in salience.components if item.name == name)


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Rooted salience"))
    db_session.flush()
    return user_id


def _mail(db_session, user_id, *, when: datetime, metadata: dict) -> None:
    db_session.add(
        Object(
            user_id=user_id,
            kind="email",
            provider="yandex_mail",
            title="note",
            origin="source",
            state="observed",
            occurred_at=when,
            metadata_=metadata,
        )
    )
    db_session.flush()
