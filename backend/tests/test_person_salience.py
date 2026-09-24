from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import Edge, Object, User
from app.domain.object_visibility import tombstone_object
from app.domain.person_identity import (
    normalize_email,
    normalize_mattermost_user_id,
    normalize_teams_user_id,
    normalize_telegram_user_id,
)
from app.domain.person_salience import (
    FOCUS_MIN,
    MAX_ATTENTION_CANDIDATES,
    MAX_COMMUNICATION_ROWS,
    MAX_IDENTITY_ROWS,
    MAX_RANKED_PEOPLE,
    MAX_TASK_CANDIDATES,
)
from app.services.errors import NotFoundError
from app.services.person_evidence_service import PersonEvidenceService
from app.services.person_identity_service import PersonIdentityService
from app.services.person_salience_service import PersonSalienceService
from app.services.provenance import REJECTED_STATE

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
ACCOUNT = "account-1"


def test_unknown_senders_do_not_create_people(db_session) -> None:
    user_id = _user(db_session)
    _telegram(db_session, user_id, peer_kind="group", sender=99, peer=-100, direction="inbound")
    before = _person_count(db_session, user_id)
    ranked = PersonSalienceService(db_session, user_id, now=NOW).rank()
    assert ranked == []
    assert _person_count(db_session, user_id) == before


def test_direct_reciprocal_outranks_public_noise(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    direct = people.create_person("Olga")
    noisy = people.create_person("Channel Author")
    people.attach(direct.id, normalize_telegram_user_id(ACCOUNT, 42))
    people.attach(noisy.id, normalize_telegram_user_id(ACCOUNT, 77))
    _telegram(db_session, user_id, peer_kind="private", sender=42, peer=42, direction="inbound")
    _telegram(
        db_session,
        user_id,
        peer_kind="private",
        sender=1,
        peer=42,
        direction="outbound",
    )
    _telegram(db_session, user_id, peer_kind="group", sender=77, peer=-50, direction="inbound")
    for _ in range(12):
        _telegram(db_session, user_id, peer_kind="group", sender=77, peer=-50, direction="inbound")
    service = PersonSalienceService(db_session, user_id, now=NOW)
    direct_score = service.evaluate(direct.id)
    noisy_score = service.evaluate(noisy.id)
    assert _value(direct_score, "directness") > _value(noisy_score, "directness")
    assert _value(direct_score, "reciprocity") > _value(noisy_score, "reciprocity")
    assert direct_score.score > noisy_score.score
    assert noisy_score.tier != "focus"
    assert next(item.person_id for item in service.rank()) == direct.id


def test_one_way_recency_frequency_attention_and_tasks(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    evidence = PersonEvidenceService(db_session, user_id)
    reciprocal = people.create_person("Reciprocal")
    one_way = people.create_person("One way")
    recent = people.create_person("Recent")
    older = people.create_person("Older")
    attended = people.create_person("Attended")
    linked = people.create_person("Linked")
    identity = normalize_email("olga@example.com")
    people.attach(reciprocal.id, normalize_telegram_user_id(ACCOUNT, 10))
    people.attach(one_way.id, normalize_telegram_user_id(ACCOUNT, 11))
    people.attach(recent.id, normalize_telegram_user_id(ACCOUNT, 12))
    people.attach(older.id, normalize_telegram_user_id(ACCOUNT, 13))
    people.attach(attended.id, identity)
    people.attach(linked.id, normalize_email("linked@example.com"))
    _telegram(db_session, user_id, peer_kind="private", sender=10, peer=10, direction="inbound")
    _telegram(db_session, user_id, peer_kind="private", sender=1, peer=10, direction="outbound")
    _telegram(db_session, user_id, peer_kind="private", sender=11, peer=11, direction="inbound")
    _telegram(
        db_session,
        user_id,
        peer_kind="private",
        sender=12,
        peer=12,
        direction="inbound",
        when=NOW - timedelta(days=1),
    )
    _telegram(
        db_session,
        user_id,
        peer_kind="private",
        sender=13,
        peer=13,
        direction="inbound",
        when=NOW - timedelta(days=40),
    )
    service = PersonSalienceService(db_session, user_id, now=NOW)
    assert service.evaluate(reciprocal.id).score > service.evaluate(one_way.id).score
    assert service.evaluate(recent.id).score > service.evaluate(older.id).score
    cap_user = _user(db_session)
    cap_people = PersonIdentityService(db_session, cap_user)
    capped = cap_people.create_person("Capped")
    cap_people.attach(capped.id, normalize_telegram_user_id(ACCOUNT, 14))
    for _ in range(8):
        _telegram(
            db_session,
            cap_user,
            peer_kind="private",
            sender=14,
            peer=14,
            direction="inbound",
        )
    eight = PersonSalienceService(db_session, cap_user, now=NOW).evaluate(capped.id)
    for _ in range(4):
        _telegram(
            db_session,
            cap_user,
            peer_kind="private",
            sender=14,
            peer=14,
            direction="inbound",
        )
    many = PersonSalienceService(db_session, cap_user, now=NOW).evaluate(capped.id)
    assert many.score == eight.score
    assert _value(many, "frequency") == 16
    assert many.truncated is True
    assert eight.truncated is False
    bare = service.evaluate(attended.id)
    evidence.record_route_choice(attended.id, identity, "route:1")
    routed = service.evaluate(attended.id)
    assert routed.score == bare.score + 8
    assert routed.tier != "focus"
    evidence.record_confirmation(attended.id, identity, "confirm:1")
    confirmed = service.evaluate(attended.id)
    assert _value(confirmed, "user_attention") == 28
    assert confirmed.score < FOCUS_MIN
    assert confirmed.claims_object_importance is False
    task = Object(
        user_id=user_id,
        kind="task",
        title="Reply",
        origin="user",
        state="confirmed",
    )
    db_session.add(task)
    db_session.flush()
    db_session.add(
        Edge(
            user_id=user_id,
            source_id=linked.id,
            target_id=task.id,
            type="related_to",
            origin="user",
            state="confirmed",
        )
    )
    db_session.flush()
    linked_score = service.evaluate(linked.id)
    assert _value(linked_score, "task_calendar") == 16
    assert linked_score.claims_object_importance is False


def test_inactive_people_cross_user_and_bounds(db_session) -> None:
    user_id = _user(db_session)
    other_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    other_people = PersonIdentityService(db_session, other_id)
    active = people.create_person("Olga")
    rejected = people.create_person("Rejected")
    hidden = people.create_person("Hidden")
    identity = normalize_telegram_user_id(ACCOUNT, 42)
    owned = people.attach(active.id, identity)
    people.attach(rejected.id, normalize_telegram_user_id(ACCOUNT, 43))
    people.attach(hidden.id, normalize_telegram_user_id(ACCOUNT, 44))
    other = other_people.create_person("Other Olga")
    other_people.attach(other.id, identity)
    _telegram(db_session, user_id, peer_kind="private", sender=42, peer=42, direction="inbound")
    _telegram(db_session, other_id, peer_kind="private", sender=42, peer=42, direction="inbound")
    _telegram(db_session, user_id, peer_kind="private", sender=43, peer=43, direction="inbound")
    service = PersonSalienceService(db_session, user_id, now=NOW)
    seen = service.evaluate(active.id).score
    people.detach(owned.id)
    assert service.evaluate(active.id).score == 0
    people.attach(active.id, identity)
    assert service.evaluate(active.id).score == seen
    rejected.state = REJECTED_STATE
    tombstone_object(hidden)
    db_session.flush()
    assert service.evaluate(rejected.id).eligible is False
    assert service.evaluate(rejected.id).score == 0
    assert service.evaluate(hidden.id).eligible is False
    ranked = {item.person_id for item in service.rank()}
    assert rejected.id not in ranked
    assert hidden.id not in ranked
    assert other.id not in ranked
    with pytest.raises(NotFoundError):
        service.evaluate(other.id)
    quiet = PersonSalienceService(db_session, other_id, now=NOW)
    assert quiet.evaluate(other.id).truncated is False
    assert service.evaluate(active.id).window_days == 90
    assert service.evaluate(active.id).row_limit == MAX_COMMUNICATION_ROWS
    source = Path(__file__).parents[1].joinpath(
        "app/services/person_salience_service.py"
    ).read_text(encoding="utf-8")
    assert "create_person" not in source
    assert "openai" not in source.casefold()
    assert "enqueue" not in source


def test_email_direction_does_not_invent_reciprocity(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    sender = people.create_person("Ada")
    colleague = people.create_person("Bea")
    people.attach(sender.id, normalize_email("ada@example.com"))
    people.attach(colleague.id, normalize_email("bea@example.com"))
    _email(
        db_session,
        user_id,
        provider="gmail",
        metadata={
            "labels": ["INBOX"],
            "sender": "Ada <ada@example.com>",
            "recipients": ["user@example.com", "bea@example.com"],
        },
    )
    service = PersonSalienceService(db_session, user_id, now=NOW)
    assert _value(service.evaluate(colleague.id), "reciprocity") == 0
    assert _value(service.evaluate(colleague.id), "directness") == 0
    assert _value(service.evaluate(sender.id), "directness") == 0
    _email(
        db_session,
        user_id,
        provider="gmail",
        metadata={
            "labels": ["SENT"],
            "sender": "user@example.com",
            "recipients": ["bea@example.com"],
        },
    )
    outbound = service.evaluate(colleague.id)
    assert _value(outbound, "directness") > 0
    assert _value(outbound, "reciprocity") == 0
    _email(
        db_session,
        user_id,
        provider="yandex_mail",
        metadata={
            "folder": "INBOX",
            "sender": "bea@example.com",
            "recipients": ["user@example.com"],
        },
    )
    reciprocal = service.evaluate(colleague.id)
    assert _value(reciprocal, "reciprocity") > 0
    before = reciprocal.score
    _email(
        db_session,
        user_id,
        provider="gmail",
        metadata={
            "labels": ["SENT", "INBOX"],
            "sender": "bea@example.com",
            "recipients": ["user@example.com"],
        },
    )
    _email(
        db_session,
        user_id,
        provider="yandex_mail",
        metadata={
            "folder": "Archive",
            "sender": "user@example.com",
            "recipients": ["bea@example.com"],
        },
    )
    assert service.evaluate(colleague.id).score == before
    _email(
        db_session,
        user_id,
        provider="gmail",
        metadata={
            "labels": ["SENT"],
            "sender": "user@example.com",
            "recipients": ["bea@example.com"],
            "cc": ["ada@example.com"],
        },
    )
    group = service.evaluate(colleague.id)
    assert _value(group, "directness") == _value(reciprocal, "directness")
    assert _value(group, "public_exposure") > 0


def test_noise_does_not_starve_direct_salience_or_ranking(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    for index in range(MAX_RANKED_PEOPLE):
        people.create_person(f"Empty {index}")
    direct = people.create_person("Direct")
    people.attach(direct.id, normalize_telegram_user_id(ACCOUNT, 42))
    _telegram(
        db_session,
        user_id,
        peer_kind="private",
        sender=42,
        peer=42,
        direction="inbound",
        when=NOW - timedelta(hours=3),
    )
    _telegram(
        db_session,
        user_id,
        peer_kind="private",
        sender=1,
        peer=42,
        direction="outbound",
        when=NOW - timedelta(hours=2),
    )
    for _ in range(50):
        _telegram(
            db_session,
            user_id,
            peer_kind="group",
            sender=99,
            peer=-100,
            direction="inbound",
            when=NOW - timedelta(minutes=5),
        )
    service = PersonSalienceService(db_session, user_id, now=NOW)
    score = service.evaluate(direct.id)
    assert _value(score, "directness") > 0
    assert _value(score, "reciprocity") > 0
    ranked = service.rank()
    assert direct.id in {item.person_id for item in ranked}
    assert next(item.person_id for item in ranked) == direct.id


def test_ranking_pool_keeps_newer_relevant_people(db_session) -> None:
    user_id = _user(db_session)
    other_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    other_people = PersonIdentityService(db_session, other_id)
    evidence = PersonEvidenceService(db_session, user_id)
    for index in range(MAX_IDENTITY_ROWS + 1):
        older = people.create_person(f"Old identity {index}")
        people.attach(older.id, normalize_email(f"old-{index}@example.com"))
    direct = people.create_person("New direct")
    people.attach(direct.id, normalize_telegram_user_id(ACCOUNT, 42))
    _telegram(db_session, user_id, peer_kind="private", sender=42, peer=42, direction="inbound")
    service = PersonSalienceService(db_session, user_id, now=NOW)
    assert direct.id in {item.person_id for item in service.rank()}

    for index in range(MAX_ATTENTION_CANDIDATES + 1):
        person = people.create_person(f"Old route {index}")
        identity = normalize_email(f"route-{index}@example.com")
        people.attach(person.id, identity)
        evidence.record_route_choice(person.id, identity, f"route:{index}")
    confirmed = people.create_person("New confirmation")
    confirmed_identity = normalize_email("confirmed@example.com")
    people.attach(confirmed.id, confirmed_identity)
    evidence.record_confirmation(confirmed.id, confirmed_identity, "confirm:new")
    rejected = people.create_person("Rejected confirmation")
    rejected_identity = normalize_email("rejected@example.com")
    people.attach(rejected.id, rejected_identity)
    evidence.record_confirmation(rejected.id, rejected_identity, "confirm:rejected")
    rejected.state = REJECTED_STATE
    other = other_people.create_person("Other confirmation")
    other_identity = normalize_email("other@example.com")
    other_people.attach(other.id, other_identity)
    PersonEvidenceService(db_session, other_id).record_confirmation(
        other.id, other_identity, "confirm:other"
    )
    db_session.flush()
    ranked_ids = [item.person_id for item in service.rank()]
    assert confirmed.id in ranked_ids
    assert rejected.id not in ranked_ids
    assert other.id not in ranked_ids
    assert ranked_ids == [item.person_id for item in service.rank()]
    assert len(ranked_ids) <= MAX_RANKED_PEOPLE

    note = Object(
        user_id=user_id,
        kind="email",
        title="unrelated",
        origin="source",
        state="observed",
    )
    task = Object(
        user_id=user_id,
        kind="task",
        title="Do",
        origin="user",
        state="confirmed",
    )
    db_session.add_all([note, task])
    db_session.flush()
    for index in range(MAX_TASK_CANDIDATES + 5):
        holder = people.create_person(f"Unrelated edge {index}")
        db_session.add(
            Edge(
                user_id=user_id,
                source_id=holder.id,
                target_id=note.id,
                type="related_to",
                origin="user",
                state="confirmed",
            )
        )
    linked = people.create_person("New task link")
    db_session.add(
        Edge(
            user_id=user_id,
            source_id=linked.id,
            target_id=task.id,
            type="related_to",
            origin="user",
            state="confirmed",
        )
    )
    db_session.flush()
    assert linked.id in {item.person_id for item in service.rank()}


def test_teams_and_mattermost_fail_closed_without_outbound_facts(db_session) -> None:
    user_id = _user(db_session)
    people = PersonIdentityService(db_session, user_id)
    human = people.create_person("Teams Human")
    bot = people.create_person("Teams Bot")
    teammate = people.create_person("Mattermost")
    tenant = "11111111-1111-1111-1111-111111111111"
    teams_user = "22222222-2222-2222-2222-222222222222"
    people.attach(human.id, normalize_teams_user_id(tenant, teams_user))
    people.attach(bot.id, normalize_teams_user_id(tenant, "33333333-3333-3333-3333-333333333333"))
    people.attach(
        teammate.id,
        normalize_mattermost_user_id("https://chat.example.com", "mm-user-1"),
    )
    _chat(
        db_session,
        user_id,
        provider="teams",
        metadata={
            "sender_kind": "application",
            "tenant_id": tenant,
            "sender_id": teams_user,
            "chat_type": "oneOnOne",
            "direction": "inbound",
        },
    )
    _chat(
        db_session,
        user_id,
        provider="teams",
        metadata={
            "sender_kind": "user",
            "tenant_id": tenant,
            "sender_id": teams_user,
            "chat_type": "oneOnOne",
            "direction": "outbound",
        },
    )
    service = PersonSalienceService(db_session, user_id, now=NOW)
    assert service.evaluate(human.id).score == 0
    assert service.evaluate(bot.id).score == 0
    _chat(
        db_session,
        user_id,
        provider="teams",
        metadata={
            "sender_kind": "user",
            "tenant_id": tenant,
            "sender_id": teams_user,
            "chat_type": "group",
            "direction": "inbound",
        },
    )
    grouped = service.evaluate(human.id)
    assert _value(grouped, "directness") == 0
    assert _value(grouped, "public_exposure") > 0
    _chat(
        db_session,
        user_id,
        provider="mattermost",
        metadata={
            "server_url": "https://chat.example.com",
            "author_user_id": "mm-user-1",
            "channel_type": "D",
        },
    )
    _chat(
        db_session,
        user_id,
        provider="mattermost",
        metadata={
            "server_url": "https://chat.example.com",
            "author_user_id": "mm-user-1",
            "channel_type": "O",
        },
    )
    mattermost = service.evaluate(teammate.id)
    assert _value(mattermost, "directness") > 0
    assert _value(mattermost, "reciprocity") == 0
    assert _value(mattermost, "public_exposure") > 0


def _value(score, name: str) -> int:
    return next(item.value for item in score.components if item.name == name)


def _user(db_session) -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="Owner"))
    db_session.flush()
    return user_id


def _person_count(db_session, user_id: uuid.UUID) -> int:
    return int(
        db_session.scalar(
            select(func.count()).select_from(Object).where(
                Object.user_id == user_id,
                Object.kind == "person",
            )
        )
        or 0
    )


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


def _email(db_session, user_id: uuid.UUID, *, provider: str, metadata: dict) -> None:
    db_session.add(
        Object(
            user_id=user_id,
            kind="email",
            provider=provider,
            title="mail",
            origin="source",
            state="observed",
            occurred_at=NOW - timedelta(hours=1),
            metadata_=metadata,
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
