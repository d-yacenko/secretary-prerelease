"""Explicit reversible Person consolidation."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.api.schemas import EdgeCreate, ObjectCreate
from app.db.models import (
    Edge,
    Object,
    PersonIdentity,
    PersonIdentityEvidence,
    PersonRoleAssignment,
    PersonRoleTerm,
    User,
)
from app.domain.object_visibility import is_object_hidden_from_active_reads, tombstone_object
from app.domain.person_candidate_score import USER_CONFIRMED
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
from app.services.person_role_service import MAX_ACTIVE_ASSIGNMENTS, PersonRoleService
from app.services.provenance import (
    AGENT_ORIGIN,
    CONFIRMED_STATE,
    PROPOSED_STATE,
    REJECTED_STATE,
    USER_ORIGIN,
)
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
    original = evidence.record_confirmation(
        duplicate.id, email, "ledger-1", explanation="secret body"
    )
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
    counts, _truncated = PersonAssistantService(
        db_session, BOOTSTRAP_USER_ID
    ).count_attributable_communications([survivor.id, duplicate.id])
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
    TaskRelationService(db_session, BOOTSTRAP_USER_ID).add_actor(
        task.id, duplicate.id, REQUESTED_BY
    )
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


def test_divergent_task_roles_block_merge(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    _people(db_session).attach(duplicate.id, normalize_email("ada@example.com"))
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    service = _merge(db_session)
    before = _identity_owners(db_session)
    cases = [
        ("Confirmed", INVOLVES, {"state": CONFIRMED_STATE}, {"state": PROPOSED_STATE}),
        ("Proposed", INVOLVES, {"state": PROPOSED_STATE}, {"state": CONFIRMED_STATE}),
        ("Confidence", WAITING_ON, {"confidence": 0.2}, {"confidence": 0.9}),
        ("Origin", DELEGATED_TO, {"origin": USER_ORIGIN}, {"origin": AGENT_ORIGIN}),
    ]
    for title, role, duplicate_kwargs, survivor_kwargs in cases:
        task = _task(db_session, title)
        relations.add_actor(task.id, duplicate.id, role, **duplicate_kwargs)
        relations.add_actor(task.id, survivor.id, role, **survivor_kwargs)
        preview = service.preview(survivor.id, duplicate.id)
        assert preview["can_merge"] is False
        assert "different task role" in preview["blockers"][0]
        assert _identity_owners(db_session) == before
        with pytest.raises(ValidationError, match="different task role"):
            service.apply(survivor.id, duplicate.id)
        assert duplicate.deleted_at is None
        _reject_actor(db_session, task.id, duplicate.id)
        _reject_actor(db_session, task.id, survivor.id)

    equivalent = _task(db_session, "Same")
    relations.add_actor(
        equivalent.id,
        duplicate.id,
        INVOLVES,
        origin=USER_ORIGIN,
        state=CONFIRMED_STATE,
        confidence=0.5,
    )
    relations.add_actor(
        equivalent.id,
        survivor.id,
        INVOLVES,
        origin=USER_ORIGIN,
        state=CONFIRMED_STATE,
        confidence=0.5,
    )
    preview = service.preview(survivor.id, duplicate.id)
    assert preview["can_merge"] is True
    service.apply(survivor.id, duplicate.id)
    assert (
        len(
            list(
                db_session.scalars(
                    select(Edge).where(
                        Edge.source_id == equivalent.id,
                        Edge.target_id == survivor.id,
                        Edge.type == INVOLVES,
                        Edge.state != REJECTED_STATE,
                    )
                )
            )
        )
        == 1
    )


def test_inactive_task_actor_blocks_merge(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    email = normalize_email("ada@example.com")
    _people(db_session).attach(duplicate.id, email)
    relations = TaskRelationService(db_session, BOOTSTRAP_USER_ID)
    hidden = _task(db_session, "Hidden")
    relations.add_actor(hidden.id, duplicate.id, REQUESTED_BY)
    tombstone_object(hidden)
    service = _merge(db_session)
    preview = service.preview(survivor.id, duplicate.id)
    assert preview["can_merge"] is False
    assert "not on an active task" in preview["blockers"][0]
    with pytest.raises(ValidationError, match="not on an active task"):
        service.apply(survivor.id, duplicate.id)
    assert duplicate.deleted_at is None
    assert _people(db_session).resolve(email).id == duplicate.id

    hidden_edge = _active_edge(db_session, hidden.id, duplicate.id, REQUESTED_BY)
    assert hidden_edge is not None
    hidden_edge.state = REJECTED_STATE
    db_session.flush()
    rejected = _task(db_session, "Rejected")
    relations.add_actor(rejected.id, duplicate.id, REQUESTED_BY)
    rejected.state = REJECTED_STATE
    db_session.flush()
    preview = service.preview(survivor.id, duplicate.id)
    assert preview["can_merge"] is False
    with pytest.raises(ValidationError, match="not on an active task"):
        service.apply(survivor.id, duplicate.id)
    assert duplicate.deleted_at is None
    assert _active_edge(db_session, rejected.id, duplicate.id, REQUESTED_BY) is not None


def test_actor_copy_preserves_fact_and_failure_rolls_back(db_session, monkeypatch) -> None:
    survivor, duplicate = _pair(db_session)
    email = normalize_email("ada@example.com")
    _people(db_session).attach(duplicate.id, email)
    task = _task(db_session, "Exact")
    TaskRelationService(db_session, BOOTSTRAP_USER_ID).add_actor(
        task.id,
        duplicate.id,
        INVOLVES,
        origin=AGENT_ORIGIN,
        state=PROPOSED_STATE,
        confidence=0.4,
    )
    service = _merge(db_session)

    def fail_copy(*_args, **_kwargs):
        raise ValidationError("copy failed")

    monkeypatch.setattr(service._tasks, "add_actor", fail_copy)
    with pytest.raises(ValidationError, match="copy failed"):
        service.apply(survivor.id, duplicate.id)
    assert duplicate.deleted_at is None
    assert _people(db_session).resolve(email).id == duplicate.id
    assert _active_edge(db_session, task.id, survivor.id, INVOLVES) is None

    monkeypatch.undo()
    service.apply(survivor.id, duplicate.id)
    copied = _active_edge(db_session, task.id, survivor.id, INVOLVES)
    assert copied is not None
    assert copied.state == PROPOSED_STATE
    assert copied.origin == AGENT_ORIGIN
    assert float(copied.confidence) == 0.4


def test_non_equivalent_evidence_blocks_and_equivalent_evidence_is_reused(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    email = normalize_email("ada@example.com")
    _people(db_session).attach(duplicate.id, email)
    source = _email(db_session, "ada@example.com")
    other = _email(db_session, "ada@example.com")
    duplicate_row = _evidence(db_session, duplicate.id, email, source.id, "same-key")
    survivor_row = _evidence(db_session, survivor.id, email, source.id, "same-key")
    service = _merge(db_session)
    before = _identity_owners(db_session)

    survivor_row.weight = duplicate_row.weight + 1
    db_session.flush()
    _assert_evidence_blocked(db_session, service, survivor, duplicate, before)

    survivor_row.weight = duplicate_row.weight
    survivor_row.provenance_kind = "other_kind"
    db_session.flush()
    _assert_evidence_blocked(db_session, service, survivor, duplicate, before)

    survivor_row.provenance_kind = duplicate_row.provenance_kind
    survivor_row.source_object_id = other.id
    db_session.flush()
    _assert_evidence_blocked(db_session, service, survivor, duplicate, before)

    survivor_row.source_object_id = source.id
    survivor_row.explanation = "different"
    db_session.flush()
    _assert_evidence_blocked(db_session, service, survivor, duplicate, before)

    survivor_row.explanation = duplicate_row.explanation
    survivor_row.details = {"note": "different"}
    db_session.flush()
    _assert_evidence_blocked(db_session, service, survivor, duplicate, before)

    survivor_row.details = dict(duplicate_row.details or {})
    db_session.flush()
    preview = service.preview(survivor.id, duplicate.id)
    assert preview["can_merge"] is True
    assert _identity_owners(db_session) == before
    service.apply(survivor.id, duplicate.id)
    kept = list(
        db_session.scalars(
            select(PersonIdentityEvidence).where(
                PersonIdentityEvidence.person_object_id == survivor.id,
                PersonIdentityEvidence.provenance_key == "same-key",
                PersonIdentityEvidence.state == "active",
            )
        )
    )
    assert [row.id for row in kept] == [survivor_row.id]


def test_tombstoned_confirmation_does_not_conflict_survivor(db_session) -> None:
    people = _people(db_session)
    survivor = people.create_person("Ada")
    duplicate = people.create_person("Other Ada")
    identity = normalize_email("ada@example.com", display_value="Ada")
    people.attach(duplicate.id, identity)
    evidence = PersonEvidenceService(db_session, BOOTSTRAP_USER_ID)
    evidence.record_confirmation(duplicate.id, identity, "user:duplicate")
    evidence.record_confirmation(survivor.id, identity, "user:survivor")
    workspace = PersonGraphWorkspaceService(db_session, BOOTSTRAP_USER_ID)
    before = _card(workspace, duplicate.id)
    assert before["identity_conflict"] is True
    service = _merge(db_session)
    service.apply(survivor.id, duplicate.id)
    historical = db_session.scalar(
        select(PersonIdentityEvidence).where(
            PersonIdentityEvidence.person_object_id == duplicate.id,
            PersonIdentityEvidence.evidence_type == USER_CONFIRMED,
            PersonIdentityEvidence.state == "active",
            PersonIdentityEvidence.provenance_key == "user:duplicate",
        )
    )
    assert historical is not None
    after = _card(workspace, survivor.id)
    assert after["identity_conflict"] is False
    known = [row for row in after["identities"] if row["canonical_value"] == "ada@example.com"]
    assert len(known) == 1
    assert known[0]["state"] == "effective"
    service.undo(survivor.id, duplicate.id)
    restored = _card(workspace, duplicate.id)
    assert restored["identity_conflict"] is True


def test_duplicate_only_role_survives_merge(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    roles = PersonRoleService(db_session, BOOTSTRAP_USER_ID)
    original = roles.assign(duplicate.id, "директор", "Arenadata")
    original.source_object_id = duplicate.id
    db_session.flush()
    terms_before = db_session.scalar(select(func.count()).select_from(PersonRoleTerm))
    _merge(db_session).apply(survivor.id, duplicate.id)
    assert db_session.scalar(select(func.count()).select_from(PersonRoleTerm)) == terms_before
    db_session.refresh(original)
    assert original.person_object_id == duplicate.id
    assert original.state == "active"
    assert is_object_hidden_from_active_reads(duplicate)
    card = _card(PersonGraphWorkspaceService(db_session, BOOTSTRAP_USER_ID), survivor.id)
    shown = card["role_assignments"]
    assert len(shown) == 1
    assert shown[0]["person_id"] == survivor.id
    assert shown[0]["role_display_text"] == "директор"
    assert shown[0]["context"] == "Arenadata"
    copied = db_session.get(PersonRoleAssignment, shown[0]["id"])
    assert copied.role_term_id == original.role_term_id
    assert copied.source_object_id == duplicate.id
    assert copied.origin == original.origin
    assert copied.provenance_kind == original.provenance_kind
    assert copied.provenance_key == original.provenance_key


def test_overlapping_role_is_not_duplicated_and_contexts_stay_distinct(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    roles = PersonRoleService(db_session, BOOTSTRAP_USER_ID)
    kept = roles.assign(survivor.id, "директор", "Arenadata")
    roles.assign(duplicate.id, "ДИРЕКТОР", " arenadata ")
    roles.assign(duplicate.id, "директор", "МГУ")
    before = _active_role_count(db_session, survivor.id)
    _merge(db_session).apply(survivor.id, duplicate.id)
    rows = _active_role_rows(db_session, survivor.id)
    assert len(rows) == before + 1
    assert kept.id in {row.id for row in rows}
    assert {(row.role_term_id, row.context_key) for row in rows} == {
        (kept.role_term_id, kept.context_key),
        (kept.role_term_id, "мгу"),
    }
    audit = duplicate.metadata_[AUDIT_KEY]
    assert len(audit["role_assignments"]) == 1
    assert audit["preexisting_role_keys"] == [
        {"role_term_id": str(kept.role_term_id), "context_key": kept.context_key}
    ]


def test_role_cap_blocks_merge_before_mutation(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    roles = PersonRoleService(db_session, BOOTSTRAP_USER_ID)
    for index in range(MAX_ACTIVE_ASSIGNMENTS):
        roles.assign(survivor.id, f"роль {index}")
    roles.assign(duplicate.id, "ещё одна роль")
    owners = _identity_owners(db_session)
    preview = _merge(db_session).preview(survivor.id, duplicate.id)
    assert preview["can_merge"] is False
    assert preview["blockers"] == ["merge would exceed the active role assignment cap"]
    with pytest.raises(ValidationError, match="active role assignment cap"):
        _merge(db_session).apply(survivor.id, duplicate.id)
    assert duplicate.deleted_at is None
    assert _identity_owners(db_session) == owners
    assert _active_role_count(db_session, survivor.id) == MAX_ACTIVE_ASSIGNMENTS
    assert _active_role_count(db_session, duplicate.id) == 1


def test_undo_retracts_only_merge_created_roles(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    roles = PersonRoleService(db_session, BOOTSTRAP_USER_ID)
    kept = roles.assign(survivor.id, "директор", "Arenadata")
    original = roles.assign(duplicate.id, "директор", "Arenadata")
    extra = roles.assign(duplicate.id, "студент")
    _merge(db_session).apply(survivor.id, duplicate.id)
    created_id = uuid.UUID(duplicate.metadata_[AUDIT_KEY]["role_assignments"][0]["id"])
    assert created_id != extra.id
    _merge(db_session).undo(survivor.id, duplicate.id)
    created = db_session.get(PersonRoleAssignment, created_id)
    assert created.state == "retracted"
    assert created.retracted_at is not None
    db_session.refresh(kept)
    db_session.refresh(original)
    assert kept.state == "active"
    assert original.state == "active"
    assert not is_object_hidden_from_active_reads(duplicate)
    restored = _card(PersonGraphWorkspaceService(db_session, BOOTSTRAP_USER_ID), duplicate.id)
    assert [item["role_display_text"] for item in restored["role_assignments"]] == [
        "директор",
        "студент",
    ]


def test_undo_fails_when_merge_created_role_was_retracted(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    roles = PersonRoleService(db_session, BOOTSTRAP_USER_ID)
    roles.assign(duplicate.id, "директор", "Arenadata")
    _merge(db_session).apply(survivor.id, duplicate.id)
    created_id = uuid.UUID(duplicate.metadata_[AUDIT_KEY]["role_assignments"][0]["id"])
    roles.retract(survivor.id, created_id)
    with pytest.raises(ValidationError, match="cannot be undone"):
        _merge(db_session).undo(survivor.id, duplicate.id)
    assert is_object_hidden_from_active_reads(duplicate)
    assert db_session.get(PersonRoleAssignment, created_id).state == "retracted"


def test_repeated_merge_does_not_copy_roles_again(db_session) -> None:
    survivor, duplicate = _pair(db_session)
    PersonRoleService(db_session, BOOTSTRAP_USER_ID).assign(duplicate.id, "директор")
    _merge(db_session).apply(survivor.id, duplicate.id)
    count = _active_role_count(db_session, survivor.id)
    again = _merge(db_session).apply(survivor.id, duplicate.id)
    assert again["idempotent"] is True
    assert _active_role_count(db_session, survivor.id) == count


def _card(workspace: PersonGraphWorkspaceService, person_id) -> dict:
    result = workspace.get_workspace(root_id=person_id)
    return next(item for item in result.people if item["person_id"] == person_id)


def _assert_evidence_blocked(db_session, service, survivor, duplicate, before) -> None:
    preview = service.preview(survivor.id, duplicate.id)
    assert preview["can_merge"] is False
    assert "different identity evidence" in preview["blockers"][0]
    assert _identity_owners(db_session) == before
    with pytest.raises(ValidationError, match="different identity evidence"):
        service.apply(survivor.id, duplicate.id)
    assert duplicate.deleted_at is None


def _evidence(db_session, person_id, identity, source_id, key) -> PersonIdentityEvidence:
    return PersonEvidenceService(db_session, BOOTSTRAP_USER_ID).record(
        person_id,
        identity,
        USER_CONFIRMED,
        provenance_kind="user_feedback",
        provenance_key=key,
        source_object_id=source_id,
        explanation="kept",
        details={"note": "same"},
    )


def _reject_actor(db_session, task_id, person_id) -> None:
    edge = (
        _active_edge(db_session, task_id, person_id, INVOLVES)
        or _active_edge(db_session, task_id, person_id, WAITING_ON)
        or _active_edge(db_session, task_id, person_id, DELEGATED_TO)
        or _active_edge(db_session, task_id, person_id, REQUESTED_BY)
    )
    assert edge is not None
    TaskRelationService(db_session, BOOTSTRAP_USER_ID).remove_actor(task_id, edge.id)


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
    rows = db_session.scalars(select(PersonIdentity).where(PersonIdentity.state != REJECTED_STATE))
    return {(row.person_object_id, row.canonical_value) for row in rows}


def _active_role_rows(db_session, person_id) -> list[PersonRoleAssignment]:
    return list(
        db_session.scalars(
            select(PersonRoleAssignment).where(
                PersonRoleAssignment.person_object_id == person_id,
                PersonRoleAssignment.state == "active",
            )
        )
    )


def _active_role_count(db_session, person_id) -> int:
    return len(_active_role_rows(db_session, person_id))


def _active_edge(db_session, task_id, person_id, role) -> Edge | None:
    return db_session.scalar(
        select(Edge).where(
            Edge.source_id == task_id,
            Edge.target_id == person_id,
            Edge.type == role,
            Edge.state != REJECTED_STATE,
        )
    )
