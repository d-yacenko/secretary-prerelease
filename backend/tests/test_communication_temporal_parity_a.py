"""Communication Temporal Parity A — provider identity and boundaries."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.connectors.teams.normalize import normalize_teams_message
from app.connectors.telegram.normalize import normalize_telegram_business_message
from app.services.temporal_signals_service import object_is_temporal_source_eligible
from app.services.user_participation_evidence_service import (
    ParticipationIdentity,
    current_user_participation,
)

TELEGRAM_USER_ID = "5000000000"
TELEGRAM_REMOTE_ID = "6000000000"
TEAMS_USER_ID = "22222222-2222-2222-2222-222222222222"
TEAMS_REMOTE_ID = "33333333-3333-3333-3333-333333333333"
TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _object(
    *,
    provider: str,
    kind: str = "chat_message",
    origin: str = "source",
    metadata: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        provider=provider,
        kind=kind,
        origin=origin,
        state="observed",
        status=None,
        deleted_at=None,
        metadata_=metadata or {},
    )


def _identity() -> ParticipationIdentity:
    return ParticipationIdentity(
        emails=frozenset(),
        mattermost_user_ids=frozenset(),
        mattermost_usernames=frozenset(),
        has_google_account=False,
        has_yandex_calendar_account=False,
        telegram_user_ids=frozenset({TELEGRAM_USER_ID}),
        teams_user_ids=frozenset({TEAMS_USER_ID}),
    )


def _telegram_message(*, from_id: str | None) -> dict:
    message = {
        "message_id": 10,
        "date": 1_700_000_000,
        "business_connection_id": "bc-1",
        "chat": {"id": TELEGRAM_REMOTE_ID, "type": "private"},
        "text": "завтра в 10:00",
    }
    if from_id is not None:
        message["from"] = {"id": from_id, "username": "ignored"}
    return message


def _teams_message(*, from_id: str | None) -> dict:
    message = {
        "id": "message-1",
        "messageType": "message",
        "createdDateTime": "2026-09-16T08:00:00Z",
        "body": {"contentType": "text", "content": "завтра в 10:00"},
    }
    if from_id is not None:
        message["from"] = {"user": {"id": from_id, "displayName": "ignored"}}
    return message


def test_temporal_eligibility_adds_only_telegram_and_teams_chat_sources() -> None:
    for provider in ("gmail", "yandex_mail", "mattermost", "telegram", "teams"):
        assert object_is_temporal_source_eligible(_object(provider=provider)) is True

    for obj in (
        _object(provider="google_calendar", kind="event"),
        _object(provider="yandex_calendar", kind="event"),
        _object(provider="telegram", kind="task"),
        _object(provider="teams", kind="file"),
        _object(provider="telegram", origin="user"),
    ):
        assert object_is_temporal_source_eligible(obj) is False


def test_telegram_participation_uses_normalized_provider_identity() -> None:
    identity = _identity()
    inbound = normalize_telegram_business_message(
        message=_telegram_message(from_id=TELEGRAM_REMOTE_ID),
        account_id=uuid4(),
        business_connection_id="bc-1",
        business_user_id=TELEGRAM_USER_ID,
    )
    outbound = normalize_telegram_business_message(
        message=_telegram_message(from_id=TELEGRAM_USER_ID),
        account_id=uuid4(),
        business_connection_id="bc-1",
        business_user_id=TELEGRAM_USER_ID,
    )
    assert inbound is not None and outbound is not None
    assert inbound["metadata"]["direction"] == "inbound"
    assert outbound["metadata"]["direction"] == "outbound"
    assert current_user_participation(_object(provider="telegram", metadata=inbound["metadata"]), identity).roles == (
        "direct_recipient",
    )
    assert current_user_participation(_object(provider="telegram", metadata=outbound["metadata"]), identity).roles == (
        "sender",
    )

    unknown_identity = dict(inbound["metadata"])
    unknown_identity["business_user_id"] = "7000000000"
    assert current_user_participation(
        _object(provider="telegram", metadata=unknown_identity), identity
    ).roles == ()
    missing_sender = dict(inbound["metadata"])
    missing_sender["from_user_id"] = None
    assert current_user_participation(
        _object(provider="telegram", metadata=missing_sender), identity
    ).roles == ()


def test_teams_participation_uses_normalized_provider_identity() -> None:
    identity = _identity()
    inbound = normalize_teams_message(
        message=_teams_message(from_id=TEAMS_REMOTE_ID),
        account_id=uuid4(),
        tenant_id=TENANT_ID,
        microsoft_user_id=TEAMS_USER_ID,
        chat_id="chat-1",
        chat_type="oneOnOne",
        chat_display_title="ignored",
    )
    outbound_sender = TEAMS_USER_ID.upper()
    outbound = normalize_teams_message(
        message=_teams_message(from_id=outbound_sender),
        account_id=uuid4(),
        tenant_id=TENANT_ID,
        microsoft_user_id=TEAMS_USER_ID,
        chat_id="chat-1",
        chat_type="oneOnOne",
        chat_display_title="ignored",
    )
    assert inbound is not None and outbound is not None
    assert inbound["metadata"]["direction"] == "inbound"
    assert outbound["metadata"]["direction"] == "outbound"
    assert outbound["metadata"]["sender_id"] == outbound_sender
    assert current_user_participation(_object(provider="teams", metadata=inbound["metadata"]), identity).roles == (
        "direct_recipient",
    )
    assert current_user_participation(_object(provider="teams", metadata=outbound["metadata"]), identity).roles == (
        "sender",
    )

    unknown_identity = dict(inbound["metadata"])
    unknown_identity["teams_user_id"] = "44444444-4444-4444-4444-444444444444"
    assert current_user_participation(
        _object(provider="teams", metadata=unknown_identity), identity
    ).roles == ()
    missing_sender = dict(inbound["metadata"])
    missing_sender["sender_id"] = None
    assert current_user_participation(
        _object(provider="teams", metadata=missing_sender), identity
    ).roles == ()

    self_sender_inbound = dict(outbound["metadata"])
    self_sender_inbound["direction"] = "inbound"
    assert current_user_participation(
        _object(provider="teams", metadata=self_sender_inbound), identity
    ).roles == ()
    foreign_sender_outbound = dict(inbound["metadata"])
    foreign_sender_outbound["direction"] = "outbound"
    assert current_user_participation(
        _object(provider="teams", metadata=foreign_sender_outbound), identity
    ).roles == ()


@pytest.mark.parametrize("provider", ["telegram", "teams"])
def test_missing_current_user_identity_fails_closed(provider: str) -> None:
    metadata = {
        "direction": "inbound",
        "from_user_id": TELEGRAM_REMOTE_ID,
        "business_user_id": TELEGRAM_USER_ID,
    }
    if provider == "teams":
        metadata = {
            "direction": "inbound",
            "sender_id": TEAMS_REMOTE_ID,
            "teams_user_id": TEAMS_USER_ID,
        }
    empty_identity = ParticipationIdentity(
        emails=frozenset(),
        mattermost_user_ids=frozenset(),
        mattermost_usernames=frozenset(),
        has_google_account=False,
        has_yandex_calendar_account=False,
    )
    assert current_user_participation(
        _object(provider=provider, metadata=metadata), empty_identity
    ).roles == ()
