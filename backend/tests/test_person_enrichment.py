from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.db.models import Object, PersonIdentity, PersonIdentityEvidence, User
from app.domain.object_visibility import tombstone_object
from app.domain.person_enrichment import (
    MAX_ENRICHMENT_CANDIDATES,
    MAX_ENRICHMENT_SCAN,
    NEEDS_CONFIRMATION,
    NEEDS_PROVIDER_LOOKUP,
)
from app.domain.person_identity import (
    normalize_email,
    normalize_mattermost_user_id,
    normalize_telegram_user_id,
)
from app.services.person_enrichment_service import PersonEnrichmentService
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PersonIdentityService
from app.services.provenance import REJECTED_STATE

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
ACCOUNT = "account-1"
SERVER = "https://chat.example"


def test_high_salience_person_ranks_ahead_of_public_only_person(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    focus = people.create_person("Olga Volkova")
    people.attach(focus.id, normalize_telegram_user_id(ACCOUNT, 7))
    incidental = people.create_person("Broadcast Colleague")
    people.attach(incidental.id, normalize_telegram_user_id(ACCOUNT, 8))
    _telegram(db_session, user_id, peer_kind="private", sender=7, peer=7, direction="inbound")
    _telegram(db_session, user_id, peer_kind="private", sender=7, peer=7, direction="outbound")
    _telegram(db_session, user_id, peer_kind="group", sender=8, peer=-100, direction="inbound")
    plan = PersonEnrichmentService(db_session, user_id, now=NOW).plan()
    order = [item.person_id for item in plan.candidates]
    assert order.index(focus.id) < order.index(incidental.id)
    focus_steps = {item.next_step for item in plan.candidates if item.person_id == focus.id}
    assert NEEDS_PROVIDER_LOOKUP in focus_steps


def test_confirmed_low_volume_person_enters_enrichment(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Quiet Olga")
    PersonEvidenceService(db_session, user_id).record_confirmation(
        person.id,
        normalize_email("quiet@example.com"),
        "confirm-quiet",
    )
    plan = PersonEnrichmentService(db_session, user_id, now=NOW).plan()
    matched = [item for item in plan.candidates if item.person_id == person.id]
    assert matched
    assert any(item.next_step == NEEDS_PROVIDER_LOOKUP for item in matched)


def test_public_unknown_author_does_not_create_person(db_session) -> None:
    user_id = _user(db_session)
    _telegram(db_session, user_id, peer_kind="group", sender=99, peer=-100, direction="inbound")
    before = _count(db_session, Object, user_id, kind="person")
    plan = PersonEnrichmentService(db_session, user_id, now=NOW).plan()
    assert _count(db_session, Object, user_id, kind="person") == before
    assert all(item.next_step != "attach_exact" for item in plan.candidates)


def test_exact_identity_records_evidence_without_duplicate_identity(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_email("olga@example.com"))
    _email(db_session, user_id, "olga@example.com")
    service = PersonEnrichmentService(db_session, user_id, now=NOW)
    service.plan()
    identities = _count(db_session, PersonIdentity, user_id)
    evidence = _count(db_session, PersonIdentityEvidence, user_id)
    service.plan()
    assert _count(db_session, PersonIdentity, user_id) == identities == 1
    assert _count(db_session, PersonIdentityEvidence, user_id) == evidence


def test_explicit_confirmation_authorizes_exact_attach(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    identity = normalize_email("olga@example.com")
    PersonEvidenceService(db_session, user_id).record_confirmation(person.id, identity, "confirm-olga")
    _email(db_session, user_id, "olga@example.com")
    plan = PersonEnrichmentService(db_session, user_id, now=NOW).plan()
    assert _count(db_session, PersonIdentity, user_id) == 1
    assert any(item.next_step == "attach_exact" and item.person_id == person.id for item in plan.candidates)
    PersonEnrichmentService(db_session, user_id, now=NOW).plan()
    assert _count(db_session, PersonIdentity, user_id) == 1


def test_name_similarity_needs_confirmation_and_does_not_attach(db_session) -> None:
    user_id = _user(db_session)
    person = PersonIdentityService(db_session, user_id).create_person("Olga Volkova")
    _chat(
        db_session,
        user_id,
        provider="mattermost",
        metadata={
            "server_url": SERVER,
            "author_display_name": "Olga Volkova",
            "channel_type": "O",
            "direction": "inbound",
        },
    )
    plan = PersonEnrichmentService(db_session, user_id, now=NOW).plan()
    assert _count(db_session, PersonIdentity, user_id) == 0
    assert any(
        item.person_id == person.id and item.next_step == NEEDS_CONFIRMATION
        for item in plan.candidates
    )


def test_identity_owned_by_another_person_fails_closed(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    owner = people.create_person("Olga Volkova")
    other = people.create_person("Other Olga")
    identity = normalize_email("olga@example.com")
    people.attach(owner.id, identity)
    PersonEvidenceService(db_session, user_id).record_confirmation(other.id, identity, "confirm-other")
    _email(db_session, user_id, "olga@example.com")
    plan = PersonEnrichmentService(db_session, user_id, now=NOW).plan()
    assert people.resolve(identity).id == owner.id
    assert _count(db_session, PersonIdentity, user_id) == 1
    assert any("identity_conflict" in item.reasons for item in plan.candidates)


def test_repeated_orchestration_is_idempotent(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_telegram_user_id(ACCOUNT, 7))
    _telegram(db_session, user_id, peer_kind="private", sender=7, peer=7, direction="inbound")
    service = PersonEnrichmentService(db_session, user_id, now=NOW)
    first = service.plan()
    evidence = _count(db_session, PersonIdentityEvidence, user_id)
    identities = _count(db_session, PersonIdentity, user_id)
    second = service.plan()
    assert _count(db_session, PersonIdentityEvidence, user_id) == evidence
    assert _count(db_session, PersonIdentity, user_id) == identities
    assert [_signature(item) for item in first.candidates] == [_signature(item) for item in second.candidates]


def test_rejected_deleted_and_cross_user_people_are_excluded(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    rejected = people.create_person("Rejected Olga")
    rejected.state = REJECTED_STATE
    deleted = people.create_person("Deleted Olga")
    tombstone_object(deleted)
    other_user = _user(db_session)
    other = PersonIdentityService(db_session, other_user).create_person("Foreign Olga")
    db_session.flush()
    plan = PersonEnrichmentService(db_session, user_id, now=NOW).plan()
    seen = {item.person_id for item in plan.candidates}
    assert rejected.id not in seen
    assert deleted.id not in seen
    assert other.id not in seen
    assert all(row.person_id not in {rejected.id, deleted.id, other.id} for row in plan.coverage)


def test_coverage_reports_known_and_missing_without_inventing_identities(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    person = people.create_person("Olga Volkova")
    people.attach(person.id, normalize_email("olga@example.com"))
    people.attach(person.id, normalize_mattermost_user_id(SERVER, "olga"))
    PersonEvidenceService(db_session, user_id).record_confirmation(
        person.id,
        normalize_email("olga@example.com"),
        "confirm-coverage",
    )
    before = _count(db_session, PersonIdentity, user_id)
    plan = PersonEnrichmentService(db_session, user_id, now=NOW).plan()
    coverage = next(row for row in plan.coverage if row.person_id == person.id)
    assert coverage.known == ("email", "mattermost")
    assert "teams" in coverage.missing
    assert "telegram" in coverage.missing
    assert _count(db_session, PersonIdentity, user_id) == before


def test_candidate_scan_is_bounded_and_truncation_is_explicit(db_session) -> None:
    user_id = _user(db_session)
    for index in range(MAX_ENRICHMENT_SCAN + 1):
        _telegram(
            db_session,
            user_id,
            peer_kind="group",
            sender=1000 + index,
            peer=-100,
            direction="inbound",
            when=NOW - timedelta(minutes=index),
        )
    plan = PersonEnrichmentService(db_session, user_id, now=NOW).plan()
    assert plan.truncated is True
    assert len(plan.candidates) <= MAX_ENRICHMENT_CANDIDATES
    assert all(len(item.source_object_ids) <= 3 for item in plan.candidates)


def test_enrichment_does_not_call_providers_or_models() -> None:
    root = Path(__file__).resolve().parents[1]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            root / "app/services/person_enrichment_service.py",
            root / "app/domain/person_enrichment.py",
        )
    )
    folded = source.casefold()
    for marker in ("openai", "httpx", "enqueue", "create_person", "embedding", "graph.microsoft"):
        assert marker not in folded


def _signature(item) -> tuple:
    identity = None if item.identity is None else item.identity.canonical_value
    return (item.person_id, item.provider, item.next_step, item.reasons, identity, item.salience_score)


def _count(db_session, model, user_id: uuid.UUID, *, kind: str | None = None) -> int:
    query = select(func.count()).select_from(model).where(model.user_id == user_id)
    if kind is not None:
        query = query.where(model.kind == kind)
    return int(db_session.scalar(query) or 0)


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Owner"))
    db_session.flush()
    return user_id


def _telegram(
    db_session,
    user_id: uuid.UUID,
    *,
    peer_kind: str,
    sender: int,
    peer: int,
    direction: str,
    when: datetime | None = None,
) -> None:
    db_session.add(
        Object(
            user_id=user_id,
            kind="chat_message",
            provider="telegram",
            title="note",
            origin="source",
            state="observed",
            occurred_at=when or NOW - timedelta(hours=1),
            metadata_={
                "transport": "mtproto",
                "account_id": ACCOUNT,
                "peer_kind": peer_kind,
                "peer_id": peer,
                "sender_peer_id": sender,
                "direction": direction,
            },
        )
    )
    db_session.flush()


def _email(db_session, user_id: uuid.UUID, sender: str) -> None:
    db_session.add(
        Object(
            user_id=user_id,
            kind="email",
            provider="gmail",
            title="mail",
            origin="source",
            state="observed",
            occurred_at=NOW - timedelta(hours=1),
            metadata_={"sender": sender, "labels": ["INBOX"]},
        )
    )
    db_session.flush()


def _chat(db_session, user_id: uuid.UUID, *, provider: str, metadata: dict) -> None:
    db_session.add(
        Object(
            user_id=user_id,
            kind="chat_message",
            provider=provider,
            title="chat",
            origin="source",
            state="observed",
            occurred_at=NOW - timedelta(hours=1),
            metadata_=metadata,
        )
    )
    db_session.flush()
