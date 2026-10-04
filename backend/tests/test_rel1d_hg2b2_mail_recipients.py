"""Named To/Cc stays additive. Bare recipient lists stay bare."""

from __future__ import annotations

from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage

import pytest

from app.connectors.google.gmail_normalize import normalize_gmail_message
from app.connectors.yandex.mail_normalize import normalize_imap_message
from app.db.models import GoogleAccount, Object
from app.domain.role_import_participants import participant_identities
from app.services.person_promotion_service import PersonPromotionService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_rel1d_role_import_participants import _mail, _user

_TO = 'Ирина Сергеевна <irina@example.com>, "Doe, John" <john@example.com>, bare@example.com'
_CC = '  Анна\tПетрова  <anna@example.com>, bare-cc@example.com'
_NAMED_TO = [
    {"address": "irina@example.com", "display_name": "Ирина Сергеевна"},
    {"address": "john@example.com", "display_name": "Doe, John"},
]
_NAMED_CC = [{"address": "anna@example.com", "display_name": "Анна Петрова"}]


def _gmail(to: str, cc: str | None = None, sender: str = "other@example.com") -> dict:
    headers = [
        {"name": "Subject", "value": "Hello"},
        {"name": "From", "value": sender},
        {"name": "To", "value": to},
    ]
    if cc is not None:
        headers.append({"name": "Cc", "value": cc})
    return normalize_gmail_message(
        {
            "id": "hg2b2",
            "threadId": "thread-hg2b2",
            "labelIds": ["INBOX"],
            "internalDate": "1724846400000",
            "payload": {
                "mimeType": "text/plain",
                "headers": headers,
                "body": {"data": "SGVsbG8="},
            },
        }
    )


def _yandex(to: str, cc: str | None = None, sender: str = "other@example.com") -> dict:
    message = EmailMessage(policy=policy.default)
    message["Subject"] = "Hello"
    message["From"] = sender
    message["To"] = to
    if cc is not None:
        message["Cc"] = cc
    message["Date"] = "Thu, 01 Oct 2026 12:00:00 +0000"
    message.set_content("Hello")
    return normalize_imap_message(message.as_bytes(), folder="INBOX", uid=1, uidvalidity=1)


def _source(normalized: dict) -> Object:
    return _object(normalized["metadata"], provider=normalized["provider"])


def _object(metadata: dict, provider: str = "gmail") -> Object:
    return Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        provider=provider,
        title="Hello",
        origin="source",
        state="observed",
        occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
        metadata_=metadata,
    )


def test_gmail_keeps_bare_lists_and_adds_named_participants() -> None:
    metadata = _gmail(_TO, _CC)["metadata"]
    assert metadata["recipients"] == ["irina@example.com", "Doe", "John", "bare@example.com"]
    assert metadata["cc"] == ["anna@example.com", "bare-cc@example.com"]
    assert metadata["to_participants"] == _NAMED_TO
    assert metadata["cc_participants"] == _NAMED_CC
    assert metadata["sender"] == "other@example.com"
    assert set(metadata["to_participants"][0]) == {"address", "display_name"}


def test_yandex_keeps_bare_lists_and_adds_named_participants() -> None:
    metadata = _yandex(_TO, _CC)["metadata"]
    assert metadata["recipients"] == ["irina@example.com", "john@example.com", "bare@example.com"]
    assert metadata["cc"] == ["anna@example.com", "bare-cc@example.com"]
    assert metadata["to_participants"] == _NAMED_TO
    assert metadata["cc_participants"] == _NAMED_CC
    assert metadata["sender"] == "other@example.com"


@pytest.mark.parametrize("normalize", [_gmail, _yandex])
def test_bare_addresses_and_empty_display_add_no_structured_participant(normalize) -> None:
    metadata = normalize("bare@example.com", "  <bare-cc@example.com>")["metadata"]
    assert metadata["recipients"] == ["bare@example.com"]
    assert "bare-cc@example.com" in metadata["cc"]
    assert "to_participants" not in metadata
    assert "cc_participants" not in metadata


@pytest.mark.parametrize("normalize", [_gmail, _yandex])
def test_named_sender_header_is_unchanged(normalize) -> None:
    sender = "Ирина Сергеевна <irina@example.com>"
    normalized = normalize("bare@example.com", sender=sender)
    assert normalized["metadata"]["sender"] == sender
    identities = participant_identities(_source(normalized), self_identity_keys=set())
    assert [item.canonical_value for item in identities] == ["irina@example.com"]
    assert identities[0].display_value == "Ирина Сергеевна"


def test_parser_uses_named_to_and_cc_and_ignores_bare_and_malformed() -> None:
    source = _object(
        {
            "sender": "other@example.com",
            "recipients": ["bare@example.com", "Ирина Сергеевна <legacy@example.com>"],
            "cc": ["bare-cc@example.com"],
            "to_participants": [
                {"address": "irina@example.com", "display_name": "  Ирина   Сергеевна "},
                "not-a-mapping",
                {"address": "bad", "display_name": "Нет Адреса"},
                {"address": "empty-name@example.com", "display_name": "   "},
                {"display_name": "Нет Почты"},
            ],
            "cc_participants": [
                {"address": "anna@example.com", "display_name": "Анна Петрова"},
            ],
            "headers": {"reply-to": "Ответ <reply@example.com>"},
        }
    )
    identities = participant_identities(source, self_identity_keys=set())
    assert [(item.canonical_value, item.display_value) for item in identities] == [
        ("legacy@example.com", "Ирина Сергеевна"),
        ("reply@example.com", "Ответ"),
        ("irina@example.com", "Ирина Сергеевна"),
        ("anna@example.com", "Анна Петрова"),
    ]


def test_sender_and_named_to_of_the_same_address_deduplicate() -> None:
    source = _object(
        {
            "sender": "Ирина Сергеевна <irina@example.com>",
            "to_participants": [
                {"address": "irina@example.com", "display_name": "Ирина Сергеевна"},
            ],
            "cc_participants": [
                {"address": "Irina@example.com", "display_name": "Ирина Сергеевна"},
            ],
        }
    )
    identities = participant_identities(source, self_identity_keys=set())
    assert [item.canonical_value for item in identities] == ["irina@example.com"]


def test_own_named_to_stays_out_of_role_import(db_session) -> None:
    user = _user(db_session)
    db_session.add(
        GoogleAccount(user_id=user.id, email="hg2b2-self@gmail.example", scopes=["gmail"])
    )
    db_session.flush()
    _mail(
        db_session,
        user_id=user.id,
        provider="gmail",
        sender="other@example.com",
        metadata={
            "sender": "other@example.com",
            "recipients": ["hg2b2-self@gmail.example"],
            "to_participants": [
                {"address": "hg2b2-self@gmail.example", "display_name": "HG2B2 Себя"},
            ],
        },
    )
    _mail(
        db_session,
        user_id=user.id,
        provider="gmail",
        sender="other@example.com",
        metadata={
            "sender": "other@example.com",
            "to_participants": [
                {"address": "hg2b2-other@example.com", "display_name": "HG2B2 Другая"},
            ],
        },
    )
    displays = {
        item.display_value
        for item in PersonPromotionService(db_session, user.id).eligible_role_import_participants()
    }
    assert "HG2B2 Себя" not in displays
    assert "HG2B2 Другая" in displays
