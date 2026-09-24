from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect, select

from alembic import command
from app.db.engine import engine
from app.db.models import Object, PersonIdentity, User
from app.domain.object_visibility import tombstone_object
from app.domain.person_candidate_score import (
    AUTOMATIC_LINK_THRESHOLD,
    EXACT_IDENTIFIER,
    NAME_SIMILARITY,
    PROVIDER_PROFILE,
)
from app.domain.person_identity import normalize_email
from app.services.errors import NotFoundError, ValidationError
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import REJECTED_STATE

ROOT = Path(__file__).parents[1]
EMAIL = "olga@example.com"


def test_0049_downgrade_and_upgrade() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    command.downgrade(config, "0048")
    try:
        names = set(inspect(engine).get_table_names())
        assert "person_identity_evidence" not in names
        assert "person_identities" in names
    finally:
        command.upgrade(config, "head")
    names = set(inspect(engine).get_table_names())
    assert "person_identity_evidence" in names
    assert "person_identities" in names


def test_evidence_is_user_isolated_and_person_validated(db_session) -> None:
    owner_id, other_id = _users(db_session)
    owner = PersonEvidenceService(db_session, owner_id)
    other = PersonEvidenceService(db_session, other_id)
    people = PersonIdentityService(db_session, owner_id)
    person = people.create_person("Olga")
    note = _note(db_session, owner_id)
    identity = normalize_email(EMAIL)
    row = owner.record(
        person.id,
        identity,
        EXACT_IDENTIFIER,
        provenance_kind="provider_fact",
        provenance_key=f"source:{note.id}",
        source_object_id=note.id,
        explanation="exact sender",
    )
    assert row.user_id == owner_id
    with pytest.raises(NotFoundError):
        other.history(person.id, identity)
    with pytest.raises(NotFoundError):
        other.record(
            person.id,
            identity,
            EXACT_IDENTIFIER,
            provenance_kind="provider_fact",
            provenance_key="other",
        )
    task = _note(db_session, owner_id, kind="task")
    with pytest.raises(ValidationError):
        owner.record(
            task.id,
            identity,
            EXACT_IDENTIFIER,
            provenance_kind="provider_fact",
            provenance_key="task",
        )
    with pytest.raises(ValidationError):
        owner.record(
            person.id,
            identity,
            EXACT_IDENTIFIER,
            provenance_kind="provider_fact",
            provenance_key="secret",
            details={"access_token": "x"},
        )
    db_session.delete(note)
    db_session.flush()
    db_session.refresh(row)
    assert row.source_object_id is None
    assert row.explanation == "exact sender"


def test_scoring_policy_confirmation_rejection_and_replay(db_session) -> None:
    user_id, _other = _users(db_session)
    service = PersonEvidenceService(db_session, user_id)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga")
    other_person = people.create_person("Other Olga")
    identity = normalize_email(EMAIL)
    before = _identity_count(db_session)

    name = service.record(
        person.id,
        identity,
        NAME_SIMILARITY,
        provenance_kind="name",
        provenance_key="name:olga",
        explanation="display name overlap",
    )
    name_score = service.score(person.id, identity)
    assert name_score.resolution == "possible"
    assert name_score.resolution != "confirmed"
    assert name_score.score < AUTOMATIC_LINK_THRESHOLD
    assert name_score.score == name.weight

    route = service.record_route_choice(
        person.id,
        identity,
        "route:send-1",
        explanation="user picked this route",
    )
    route_score = service.score(person.id, identity)
    assert route.evidence_type == "user_route_choice"
    assert route_score.resolution != "confirmed"
    assert route_score.score < AUTOMATIC_LINK_THRESHOLD
    assert route_score.score > name_score.score

    exact = service.record(
        person.id,
        identity,
        EXACT_IDENTIFIER,
        provenance_kind="provider_fact",
        provenance_key="gmail:msg-1",
        explanation="exact address",
    )
    profile = service.record(
        other_person.id,
        identity,
        PROVIDER_PROFILE,
        provenance_kind="profile",
        provenance_key="profile:olga",
    )
    exact_score = service.score(person.id, identity)
    profile_score = service.score(other_person.id, identity)
    assert exact.weight > name.weight
    assert profile.weight > name.weight
    assert exact_score.score > name_score.score
    assert exact_score.resolution == "likely"
    assert profile_score.score != exact_score.score

    replay = service.record(
        person.id,
        identity,
        EXACT_IDENTIFIER,
        provenance_kind="provider_fact",
        provenance_key="gmail:msg-1",
    )
    assert replay.id == exact.id
    assert service.score(person.id, identity).score == exact_score.score

    rejected = service.record_rejection(
        person.id,
        identity,
        "reject:1",
        explanation="this is another Olga",
    )
    veto = service.score(person.id, identity)
    assert rejected.polarity == "negative"
    assert veto.resolution == "rejected"
    assert veto.score == 0
    assert veto.contradictory is True
    kinds = {item.evidence_type for item in veto.components}
    assert "user_rejected" in kinds
    assert EXACT_IDENTIFIER in kinds

    confirmed = service.record_confirmation(
        person.id,
        identity,
        "confirm:1",
        explanation="yes, this address is Olga",
    )
    assert confirmed.evidence_type == "user_confirmed"
    assert service.score(person.id, identity).resolution == "confirmed"
    history = service.history(person.id, identity)
    retracted = next(row for row in history if row.id == rejected.id)
    assert retracted.state == "retracted"
    assert retracted.superseded_by_id == confirmed.id
    assert service.score(person.id, identity).score == 100

    service.retract(confirmed.id)
    after_retract = service.score(person.id, identity)
    assert after_retract.resolution != "confirmed"
    assert after_retract.resolution != "rejected"
    assert _identity_count(db_session) == before


def test_candidates_do_not_attach_or_merge(db_session) -> None:
    user_id, _other = _users(db_session)
    people = PersonIdentityService(db_session, user_id)
    service = PersonEvidenceService(db_session, user_id)
    olga = people.create_person("Olga Volkova")
    namesake = people.create_person("Olga")
    identity = normalize_email(EMAIL, display_value="Olga Volkova")
    people.attach(olga.id, identity)
    before = _identity_count(db_session)
    candidates = service.propose_candidates(identity, "Olga Volkova")
    reasons = {item.person_id: item.reason for item in candidates}
    assert reasons[olga.id] == "exact_identifier"
    assert reasons[namesake.id] == "name_similarity"
    assert _identity_count(db_session) == before
    source = Path(__file__).parents[1].joinpath(
        "app/services/person_evidence_service.py"
    ).read_text(encoding="utf-8")
    scoring = Path(__file__).parents[1].joinpath(
        "app/domain/person_candidate_score.py"
    ).read_text(encoding="utf-8")
    assert ".attach(" not in source
    assert "openai" not in scoring.casefold()


def test_linked_identity_must_belong_to_the_target_person(db_session) -> None:
    user_id, _other = _users(db_session)
    people = PersonIdentityService(db_session, user_id)
    evidence = PersonEvidenceService(db_session, user_id)
    person_a = people.create_person("Olga A")
    person_b = people.create_person("Olga B")
    identity = normalize_email(EMAIL)
    foreign = people.attach(person_b.id, identity)
    with pytest.raises(ValidationError):
        evidence.record(
            person_a.id,
            identity,
            EXACT_IDENTIFIER,
            provenance_kind="provider_fact",
            provenance_key="foreign-link",
            person_identity_id=foreign.id,
        )
    people.detach(foreign.id)
    with pytest.raises(ValidationError):
        evidence.record(
            person_b.id,
            identity,
            EXACT_IDENTIFIER,
            provenance_kind="provider_fact",
            provenance_key="rejected-link",
            person_identity_id=foreign.id,
        )
    owned = people.attach(person_a.id, identity)
    row = evidence.record(
        person_a.id,
        identity,
        EXACT_IDENTIFIER,
        provenance_kind="provider_fact",
        provenance_key="owned-link",
        person_identity_id=owned.id,
    )
    assert row.person_identity_id == owned.id
    people.detach(owned.id)
    history = evidence.history(person_a.id, identity)
    assert [item.id for item in history] == [row.id]
    assert history[0].state == "active"
    with pytest.raises(ValidationError):
        evidence.record(
            person_a.id,
            identity,
            EXACT_IDENTIFIER,
            provenance_kind="provider_fact",
            provenance_key="relink-rejected",
            person_identity_id=owned.id,
        )


def test_inactive_people_and_identities_are_not_candidates(db_session) -> None:
    user_id, _other = _users(db_session)
    people = PersonIdentityService(db_session, user_id)
    evidence = PersonEvidenceService(db_session, user_id)
    rejected = people.create_person("Rejected Olga")
    hidden = people.create_person("Olga Hidden")
    carrier = people.create_person("Alex")
    visible = people.create_person("Olga Volkova")
    rejected_identity = normalize_email(EMAIL)
    people.attach(rejected.id, rejected_identity)
    rejected.state = REJECTED_STATE
    hidden_identity = normalize_email("hidden@example.com")
    people.attach(hidden.id, hidden_identity)
    tombstone_object(hidden)
    alias = normalize_email("alias@example.com", display_value="Olga Volkova")
    detached = people.attach(carrier.id, alias)
    people.detach(detached.id)
    db_session.flush()
    before = _identity_count(db_session)

    assert people.resolve(rejected_identity) is None
    assert people.resolve(hidden_identity) is None
    assert evidence.propose_candidates(rejected_identity, "Rejected Olga") == []
    assert evidence.propose_candidates(hidden_identity, "Olga Hidden") == []
    names = {item.person_id for item in evidence.propose_candidates(None, "Olga Volkova")}
    assert names == {visible.id}
    assert carrier.id not in names
    assert _identity_count(db_session) == before


def _users(db_session) -> tuple[uuid.UUID, uuid.UUID]:
    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    db_session.add(User(id=owner_id, display_name="Owner"))
    db_session.add(User(id=other_id, display_name="Other"))
    db_session.flush()
    return owner_id, other_id


def _note(db_session, user_id: uuid.UUID, *, kind: str = "email") -> Object:
    note = Object(
        user_id=user_id,
        kind=kind,
        title="note",
        origin="source",
        state="observed",
    )
    db_session.add(note)
    db_session.flush()
    return note


def _identity_count(db_session) -> int:
    return len(list(db_session.scalars(select(PersonIdentity))))
