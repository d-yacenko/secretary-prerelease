"""Explicit reversible Person consolidation."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import Edge, Object, PersonIdentity, PersonIdentityEvidence, User
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.domain.person_identity import normalize_email, normalize_telegram_user_id
from app.domain.task_relations import DELEGATED_TO, INVOLVES, REQUESTED_BY, WAITING_ON
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.graph_service import GraphService
from app.services.object_bookmark_service import ObjectBookmarkService
from app.services.person_assistant_service import PersonAssistantService
from app.services.person_consolidation_service import (
    AUDIT_KEY,
    PersonConsolidationService,
)
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_graph_workspace_service import PersonGraphWorkspaceService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import CONFIRMED_STATE, REJECTED_STATE, USER_ORIGIN
from app.services.task_relation_service import TaskRelationService
from app.users.bootstrap import BOOTSTRAP_USER_ID

NOW = datetime(2026, 9, 29, 8, tzinfo=UTC)


def test_preview_is_read_only_and_rejects_bad_pairs(db_session) -> None:
    people = _people(db_session)
    survivor = people.create_person("Ada")
    duplicate = people.create_person("Opaque")
    people.attach(duplicate.id, normalize_email("ada@example.com", display_value="Ada"))
    before_identities = _identity_owners(db_session)
    service = _merge(db_session)
    preview = service.preview(survivor.id, duplicate.id)
    assert preview["can_merge"] is True
    assert preview["survivor"]["title"] == "Ada"
    assert preview["duplicate"]["title"] == "Opaque"
    assert preview["identity_count"] == 1
    assert preview["identities"][0]["canonical_value"] == "ada@example.com"
    assert duplicate.deleted_at is None
    assert _identity_owners(db_session) == before_identities
    with pytest.raises(ValidationError, match="two different"):
        service.preview(survivor.id, survivor.id)
    other = User(id=uuid.uuid4(), display_name="Other")
    db_session.add(other)
    db_session.flush()
    foreign = PersonIdentityService(db_session, other.id).create_person("Foreign")
    with pytest.raises(NotFoundError):
        service.preview(survivor.id, foreign.id)


def test_unsupported_edge_blocks_merge(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    _people(db_session).attach(duplicate.id, normalize_email("ada@example.com"))
    task = _task(db_session, "Note")
    GraphService(db_session, BOOTSTRAP_USER_ID).create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=duplicate.id,
            type="references",
            origin=USER_ORIGIN,
            state=CONFIRMED_STATE,
        )
    )
    preview = _merge(db_session).preview(survivor.id, duplicate.id)
    assert preview["can_merge"] is False
    assert preview["blockers"] == ["duplicate has an unsupported graph edge"]
    with pytest.raises(ValidationError, match="unsupported"):
        _merge(db_session).apply(survivor.id, duplicate.id)
    assert duplicate.deleted_at is None
    assert _people(db_session).list_identities(duplicate.id)


def test_identities_evidence_and_actor_roles_move_together(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    email = normalize_email("ada@example.com", display_value="Ada Mail")
    telegram = normalize_telegram_user_id("acct", "42", display_value="Ada TG")
    people = _people(db_session)
    people.attach(duplicate.id, email)
    people.attach(duplicate.id, telegram)
    evidence = PersonEvidenceService(db_session, BOOTSTRAP_USER_ID)
    original = evidence.record_confirmation(duplicate.id, email, "ledger-1", explanation="secret body")
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    roles = {
        REQUESTED_BY: _task(db_session, "Asked"),
        DELEGATED_TO: _task(db_session, "Delegated"),
        WAITING_ON: _task(db_session, "Waiting"),
        INVOLVES: _task(db_session, "Involved"),
    }
    for role, task in roles.items():
        relations.add_actor(task.id, duplicate.id, role)
    same = _task(db_session, "Already")
    relations.add_actor(same.id, duplicate.id, INVOLVES)
    relations.add_actor(same.id, survivor.id, INVOLVES)
    ObjectBookmarkService(db_session, BOOTSTRAP_USER_ID).upsert(duplicate.id, "blue")
    _email(db_session, "ada@example.com")

    result = _merge(db_session).apply(survivor.id, duplicate.id)
    assert result["idempotent"] is False
    assert is_object_hidden_from_active_reads(duplicate)
    assert survivor.title == "Ada"
    assert not _people(db_session).list_identities(duplicate.id)
    moved = {
        (row.provider, row.canonical_value, row.display_value)
        for row in _people(db_session).list_identities(survivor.id)
    }
    assert ("email", "ada@example.com", "Ada Mail") in moved
    assert ("telegram_mtproto", telegram.canonical_value, "Ada TG") in moved
    db_session.refresh(original)
    assert original.state == "active"
    assert original.person_object_id == duplicate.id
    copied = db_session.scalar(
        select(PersonIdentityEvidence).where(
            PersonIdentityEvidence.person_object_id == survivor.id,
            PersonIdentityEvidence.provenance_key == "ledger-1",
            PersonIdentityEvidence.state == "active",
        )
    )
    assert copied is not None
    assert copied.explanation == "secret body"
    assert copied.evidence_type == original.evidence_type
    for role, task in roles.items():
        assert _active_edge(db_session, task.id, survivor.id, role) is not None
        assert _active_edge(db_session, task.id, duplicate.id, role) is not None
    assert (
        len(
            list(
                db_session.scalars(
                    select(Edge).where(
                        Edge.source_id == same.id,
                        Edge.target_id == survivor.id,
                        Edge.type == INVOLVES,
                        Edge.state != REJECTED_STATE,
                    )
                )
            )
        )
        == 1
    )
    assert not db_session.scalars(
        select(Edge.id).where(
            Edge.target_id == survivor.id,
            Edge.type.in_(("references", "depends_on", "part_of", "related_to")),
            Edge.state != REJECTED_STATE,
        )
    ).all()
    audit = duplicate.metadata_[AUDIT_KEY]
    encoded = json.dumps(audit)
    assert "secret body" not in encoded
    assert audit["survivor_id"] == str(survivor.id)
    assert audit["bookmark"] == {"present": True, "color": "blue"}
    assert len(encoded) < 8000
    counts, _truncated = PersonAssistantService(db_session, BOOTSTRAP_USER_ID).count_attributable_communications(
        [survivor.id, duplicate.id]
    )
    assert counts[survivor.id] == 1
    assert counts[duplicate.id] == 0
    visible = {
        person.id
        for person in PersonGraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)._people_page(
            exclude=set(),
            limit=20,
        )
    }
    assert duplicate.id not in visible
    assert survivor.id in visible
    again = _merge(db_session).apply(survivor.id, duplicate.id)
    assert again["idempotent"] is True
    other = _people(db_session).create_person("Third")
    with pytest.raises(ConflictError, match="already merged"):
        _merge(db_session).apply(other.id, duplicate.id)


def test_conflict_aborts_without_partial_merge(db_session, monkeypatch) -> None:
    survivor, duplicate = _pair(db_session)
    _people(db_session).attach(duplicate.id, normalize_email("ada@example.com"))
    _people(db_session).attach(
        duplicate.id,
        normalize_telegram_user_id("acct", "42", display_value="Ada"),
    )
    original = PersonIdentityService.reassign
    calls = {"n": 0}

    def fail_second(self, identity_id, person_id):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ConflictError("person_identity_conflict")
        return original(self, identity_id, person_id)

    monkeypatch.setattr(PersonIdentityService, "reassign", fail_second)
    with pytest.raises(ConflictError):
        _merge(db_session).apply(survivor.id, duplicate.id)
    assert duplicate.deleted_at is None
    assert len(_people(db_session).list_identities(duplicate.id)) == 2
    assert _people(db_session).list_identities(survivor.id) == []


def test_undo_restores_only_merge_created_rows(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    email = normalize_email("ada@example.com", display_value="Ada")
    _people(db_session).attach(duplicate.id, email)
    PersonEvidenceService(db_session, BOOTSTRAP_USER_ID).record_confirmation(
        duplicate.id, email, "ledger-1"
    )
    task = _task(db_session, "Asked")
    TaskRelationService(db_session, BOOTSTRAP_USER_ID).add_actor(task.id, duplicate.id, REQUESTED_BY)
    kept = _task(db_session, "Kept")
    kept_edge, _created = TaskRelationService(db_session, BOOTSTRAP_USER_ID).add_actor(
        kept.id, survivor.id, DELEGATED_TO
    )
    ObjectBookmarkService(db_session, BOOTSTRAP_USER_ID).upsert(duplicate.id, "green")
    _merge(db_session).apply(survivor.id, duplicate.id)
    history = PersonGraphWorkspaceService(db_session, BOOTSTRAP_USER_ID).get_workspace(
        root_id=survivor.id
    )
    card = next(item for item in history.people if item["person_id"] == survivor.id)
    assert card["consolidations"][0]["duplicate_title"] == "Opaque"
    assert card["consolidations"][0]["undo_available"] is True

    undone = _merge(db_session).undo(survivor.id, duplicate.id)
    assert undone["idempotent"] is False
    assert not is_object_hidden_from_active_reads(duplicate)
    assert _people(db_session).resolve(email).id == duplicate.id
    assert _active_edge(db_session, task.id, duplicate.id, REQUESTED_BY) is not None
    assert _active_edge(db_session, task.id, survivor.id, REQUESTED_BY) is None
    assert _active_edge(db_session, kept.id, survivor.id, DELEGATED_TO).id == kept_edge.id
    copied = db_session.scalar(
        select(PersonIdentityEvidence).where(
            PersonIdentityEvidence.person_object_id == survivor.id,
            PersonIdentityEvidence.provenance_key == "ledger-1",
        )
    )
    assert copied.state == "retracted"
    historical = db_session.scalar(
        select(PersonIdentityEvidence).where(
            PersonIdentityEvidence.person_object_id == duplicate.id,
            PersonIdentityEvidence.provenance_key == "ledger-1",
        )
    )
    assert historical.state == "active"
    assert ObjectBookmarkService(db_session, BOOTSTRAP_USER_ID).list_by_objects([duplicate.id])
    repeated = _merge(db_session).undo(survivor.id, duplicate.id)
    assert repeated["idempotent"] is True
    assert _people(db_session).resolve(email).id == duplicate.id


def test_diverged_undo_leaves_the_merge_in_place(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    email = normalize_email("ada@example.com", display_value="Ada")
    _people(db_session).attach(duplicate.id, email)
    _merge(db_session).apply(survivor.id, duplicate.id)
    PersonEvidenceService(db_session, BOOTSTRAP_USER_ID).record_confirmation(
        survivor.id, email, "later-user-choice"
    )
    db_session.flush()
    with pytest.raises(ValidationError, match="cannot be undone"):
        _merge(db_session).undo(survivor.id, duplicate.id)
    assert is_object_hidden_from_active_reads(duplicate)
    assert _people(db_session).resolve(email).id == survivor.id


def _pair(db_session) -> tuple[Object, Object]:
    people = _people(db_session)
    return people.create_person("Ada"), people.create_person("Opaque")


def _people(db_session) -> PersonIdentityService:
    return PersonIdentityService(db_session, BOOTSTRAP_USER_ID)


def _merge(db_session) -> PersonConsolidationService:
    return PersonConsolidationService(db_session, BOOTSTRAP_USER_ID)


def _task(db_session, title: str) -> Object:
    return GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(kind="task", title=title, origin=USER_ORIGIN, state=CONFIRMED_STATE)
    )


def _email(db_session, sender: str) -> Object:
    message = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        provider="gmail",
        title="Hello",
        body="secret body",
        origin="source",
        state="observed",
        occurred_at=NOW,
        metadata_={"sender": sender, "labels": ["INBOX"]},
    )
    db_session.add(message)
    db_session.flush()
    return message


def _identity_owners(db_session) -> set[tuple]:
    rows = db_session.scalars(
        select(PersonIdentity).where(PersonIdentity.state != REJECTED_STATE)
    )
    return {(row.person_object_id, row.canonical_value) for row in rows}


def _active_edge(db_session, task_id, person_id, role) -> Edge | None:
    return db_session.scalar(
        select(Edge).where(
            Edge.source_id == task_id,
            Edge.target_id == person_id,
            Edge.type == role,
            Edge.state != REJECTED_STATE,
        )
    )
