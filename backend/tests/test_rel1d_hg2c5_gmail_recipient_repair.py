"""Gmail recipient repair adds only missing HG2B2 named participants."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.connectors.google.errors import (
    GoogleApiError,
    GoogleConfigurationError,
    GoogleConnectorError,
    GoogleOAuthError,
)
from app.connectors.google.gmail_normalize import (
    gmail_structured_recipients,
    normalize_gmail_message,
)
from app.db.models import GoogleAccount, Job, Object, User
from app.domain.person_identity import normalize_email
from app.domain.role_import_participants import participant_identities
from app.services import gmail_recipient_repair_service as repair_module
from app.services.gmail_recipient_repair_service import (
    RECIPIENT_REPAIR_MAX_LOOKUPS,
    RECIPIENT_REPAIR_SCAN_LIMIT,
    GmailRecipientRepairService,
)

_ACCOUNT_EMAIL = object()
EMAIL = "owner@gmail.example"
OTHER_EMAIL = "other@gmail.example"
TOKEN = "ready-access-token"
NOW = datetime(2026, 10, 5, 17, tzinfo=UTC)
TO = 'Ирина Сергеевна <irina@example.com>, "Doe, John" <john@example.com>, bare@example.com'
CC = "  Анна\tПетрова  <anna@example.com>, bare-cc@example.com"
LEGACY_TO = ["irina@example.com", "Doe", "John", "bare@example.com"]
LEGACY_CC = ["anna@example.com", "bare-cc@example.com"]
NAMED_TO = [
    {"address": "irina@example.com", "display_name": "Ирина Сергеевна"},
    {"address": "john@example.com", "display_name": "Doe, John"},
]
NAMED_CC = [{"address": "anna@example.com", "display_name": "Анна Петрова"}]


class MessageTransport:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, str, str]] = []

    def get_message(self, access_token, user_id, message_id):
        self.calls.append((access_token, user_id, message_id))
        return self.handler(access_token, user_id, message_id)

    def __getattr__(self, name):
        raise AssertionError(name)


def test_repair_source_has_no_sync_or_token_refresh_path() -> None:
    source = inspect.getsource(repair_module)
    for banned in (
        "GoogleTokenManager",
        "get_valid_access_token",
        "list_message",
        "history",
        "attachment",
        "send_message",
        "gmail_sync",
        ".commit(",
        ".rollback(",
    ):
        assert banned not in source


def test_shared_helper_matches_ordinary_gmail_normalization() -> None:
    message = _provider_message("hg2b2", to=TO, cc=CC)
    normalized = normalize_gmail_message(message)
    assert gmail_structured_recipients(message) == (
        normalized["metadata"]["to_participants"],
        normalized["metadata"]["cc_participants"],
    )
    assert normalized["metadata"]["recipients"] == LEGACY_TO
    assert normalized["metadata"]["cc"] == LEGACY_CC
    bare = _provider_message("bare", to="bare@example.com", cc="  <bare-cc@example.com>")
    assert gmail_structured_recipients(bare) == ([], [])


def test_only_matching_account_rows_are_repaired(db_session) -> None:
    user = _user(db_session)
    other = _user(db_session, "other")
    account = _account(db_session, user.id)
    other_account = _account(db_session, user.id, email=OTHER_EMAIL)
    valid = _mail(db_session, user, account, object_id=UUID(int=10), message_id="m-10")
    hidden = _mail(
        db_session, user, account, object_id=UUID(int=1), message_id="m-1", status="deleted"
    )
    blank = _mail(db_session, user, account, object_id=UUID(int=8), message_id="")
    untouched = [
        hidden,
        _mail(db_session, other, other_account, object_id=UUID(int=2), message_id="m-2"),
        _mail(
            db_session,
            user,
            account,
            object_id=UUID(int=3),
            message_id="m-3",
            source_account_email=_ACCOUNT_EMAIL,
        ),
        _mail(
            db_session,
            user,
            other_account,
            object_id=UUID(int=4),
            message_id="m-4",
        ),
        _mail(
            db_session,
            user,
            account,
            object_id=UUID(int=5),
            message_id="m-5",
            provider="yandex_mail",
        ),
        _mail(
            db_session,
            user,
            account,
            object_id=UUID(int=6),
            message_id="m-6",
            kind="chat_message",
        ),
        _mail(
            db_session,
            user,
            account,
            object_id=UUID(int=7),
            message_id="m-7",
            deleted_at=NOW,
        ),
        blank,
        _mail(
            db_session,
            user,
            account,
            object_id=UUID(int=9),
            message_id="m-9",
            external_id="not-m-9",
        ),
    ]
    before = {obj.id: _snapshot(obj) for obj in untouched}
    account_before = _account_snapshot(account)
    jobs_before = _job_count(db_session, user.id)
    transport = MessageTransport(
        lambda _token, _user_id, message_id: _provider_message(message_id, to=TO, cc=CC)
    )

    summary = _repair(db_session, user.id, account, transport)

    assert transport.calls == [(TOKEN, "me", "m-10")]
    assert summary.candidates_scanned == 4
    assert summary.provider_calls == 1
    assert summary.updated == 1
    assert summary.hidden_skipped == 1
    assert summary.invalid_provenance == 2
    assert summary.exhausted is True
    stored = db_session.get(Object, valid.id)
    assert stored.metadata_["to_participants"] == NAMED_TO
    assert stored.metadata_["cc_participants"] == NAMED_CC
    assert stored.metadata_["recipients"] == LEGACY_TO
    assert stored.metadata_["cc"] == LEGACY_CC
    assert stored.metadata_["sender"] == "other@example.com"
    assert stored.metadata_["source_account_email"] == EMAIL
    assert stored.metadata_["nested"] == {"keep": True}
    assert _content(stored) == _content(valid)
    assert _account_snapshot(account) == account_before
    assert _job_count(db_session, user.id) == jobs_before
    for obj in untouched:
        assert _snapshot(db_session.get(Object, obj.id)) == before[obj.id]


def test_existing_structured_keys_are_not_fetched_or_overwritten(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    both = _mail(
        db_session,
        user,
        account,
        object_id=UUID(int=1),
        message_id="both",
        to_participants=[{"address": "kept-to@example.com", "display_name": "Старый To"}],
        cc_participants=[{"address": "kept-cc@example.com", "display_name": "Старый Cc"}],
    )
    kept_to = _mail(
        db_session,
        user,
        account,
        object_id=UUID(int=2),
        message_id="kept-to",
        to_participants=[{"address": "kept-to@example.com", "display_name": "Старый To"}],
    )
    before_both = _snapshot(both)
    transport = MessageTransport(
        lambda _token, _user_id, message_id: _provider_message(message_id, to=TO, cc=CC)
    )

    summary = _repair(db_session, user.id, account, transport)

    assert transport.calls == [(TOKEN, "me", "kept-to")]
    assert summary.already_structured == 1
    assert summary.updated == 1
    assert _snapshot(db_session.get(Object, both.id)) == before_both
    stored = db_session.get(Object, kept_to.id)
    assert stored.metadata_["to_participants"] == [
        {"address": "kept-to@example.com", "display_name": "Старый To"}
    ]
    assert stored.metadata_["cc_participants"] == NAMED_CC
    assert stored.metadata_["recipients"] == LEGACY_TO


def test_named_fields_fill_only_when_missing(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    only_to = _mail(db_session, user, account, object_id=UUID(int=1), message_id="only-to")
    only_cc = _mail(db_session, user, account, object_id=UUID(int=2), message_id="only-cc")
    both = _mail(db_session, user, account, object_id=UUID(int=3), message_id="both")
    bare = _mail(db_session, user, account, object_id=UUID(int=4), message_id="bare")

    def payload(_token, _user_id, message_id):
        if message_id == "only-to":
            return _provider_message(message_id, to=TO, cc="bare-cc@example.com")
        if message_id == "only-cc":
            return _provider_message(message_id, to="bare@example.com", cc=CC)
        if message_id == "bare":
            return _provider_message(message_id, to="bare@example.com", cc="bare-cc@example.com")
        return _provider_message(message_id, to=TO, cc=CC)

    summary = _repair(db_session, user.id, account, MessageTransport(payload))

    assert summary.updated == 3
    assert summary.no_named_recipients == 1
    to_row = db_session.get(Object, only_to.id)
    cc_row = db_session.get(Object, only_cc.id)
    both_row = db_session.get(Object, both.id)
    bare_row = db_session.get(Object, bare.id)
    assert to_row.metadata_["to_participants"] == NAMED_TO
    assert "cc_participants" not in to_row.metadata_
    assert "to_participants" not in cc_row.metadata_
    assert cc_row.metadata_["cc_participants"] == NAMED_CC
    assert both_row.metadata_["to_participants"] == NAMED_TO
    assert both_row.metadata_["cc_participants"] == NAMED_CC
    assert "to_participants" not in bare_row.metadata_
    assert "cc_participants" not in bare_row.metadata_
    assert bare_row.metadata_["recipients"] == LEGACY_TO


def test_repaired_names_qualify_and_self_is_filtered(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    mail = _mail(db_session, user, account, object_id=UUID(int=1), message_id="self")
    own_to = f'Owner Name <{EMAIL}>, Ирина Сергеевна <irina@example.com>'
    assert participant_identities(mail, self_identity_keys=set()) == ()

    summary = _repair(
        db_session,
        user.id,
        account,
        MessageTransport(
            lambda _token, _user_id, message_id: _provider_message(message_id, to=own_to, cc=CC)
        ),
    )

    stored = db_session.get(Object, mail.id)
    assert summary.updated == 1
    identity = normalize_email(account.email)
    self_key = (
        identity.provider,
        identity.identity_type,
        identity.realm,
        identity.canonical_value,
    )
    visible = participant_identities(stored, self_identity_keys=set())
    filtered = participant_identities(stored, self_identity_keys={self_key})
    assert EMAIL.casefold() in {item.canonical_value for item in visible}
    assert EMAIL.casefold() not in {item.canonical_value for item in filtered}
    assert "irina@example.com" in {item.canonical_value for item in filtered}
    assert "anna@example.com" in {item.canonical_value for item in filtered}


def test_scan_stops_at_one_hundred_rows(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    for index in range(1, 121):
        _mail(db_session, user, account, object_id=UUID(int=index), message_id="")
    transport = MessageTransport(
        lambda _token, _user_id, message_id: _provider_message(message_id)
    )

    summary = _repair(db_session, user.id, account, transport)

    assert summary.candidates_scanned == RECIPIENT_REPAIR_SCAN_LIMIT
    assert summary.provider_calls == 0
    assert summary.invalid_provenance == 100
    assert summary.next_cursor == UUID(int=100)
    assert summary.exhausted is False
    again = _repair(db_session, user.id, account, transport, cursor=summary.next_cursor)
    assert again.candidates_scanned == 20
    assert again.exhausted is True
    assert transport.calls == []


def test_provider_calls_stop_at_twenty(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    for index in range(1, 26):
        _mail(db_session, user, account, object_id=UUID(int=index), message_id=f"m-{index}")
    transport = MessageTransport(
        lambda _token, _user_id, message_id: _provider_message(message_id, to=TO, cc=CC)
    )

    summary = _repair(db_session, user.id, account, transport)

    assert summary.provider_calls == RECIPIENT_REPAIR_MAX_LOOKUPS
    assert summary.updated == 20
    assert summary.next_cursor == UUID(int=20)
    assert summary.exhausted is False
    assert [call[2] for call in transport.calls] == [f"m-{index}" for index in range(1, 21)]
    assert "to_participants" not in db_session.get(Object, UUID(int=21)).metadata_
    again = _repair(db_session, user.id, account, transport, cursor=summary.next_cursor)
    assert again.provider_calls == 5
    assert again.updated == 5
    assert again.exhausted is True


def test_bad_rows_advance_the_cursor(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    invalid = _mail(db_session, user, account, object_id=UUID(int=1), message_id="")
    structured = _mail(
        db_session,
        user,
        account,
        object_id=UUID(int=2),
        message_id="structured",
        to_participants=[{"address": "a@example.com", "display_name": "А"}],
        cc_participants=[{"address": "b@example.com", "display_name": "Б"}],
    )
    missing = _mail(db_session, user, account, object_id=UUID(int=3), message_id="missing")
    unnamed = _mail(db_session, user, account, object_id=UUID(int=4), message_id="unnamed")
    mismatch = _mail(db_session, user, account, object_id=UUID(int=5), message_id="mismatch")
    good = _mail(db_session, user, account, object_id=UUID(int=6), message_id="good")

    def payload(_token, _user_id, message_id):
        if message_id == "missing":
            raise GoogleApiError("gone", operation="get_message", status_code=404)
        if message_id == "unnamed":
            return _provider_message(message_id, to="bare@example.com", cc="bare-cc@example.com")
        if message_id == "mismatch":
            return _provider_message("other-id", to=TO, cc=CC)
        return _provider_message(message_id, to=TO, cc=CC)

    transport = MessageTransport(payload)
    summary = _repair(db_session, user.id, account, transport)

    assert summary.invalid_provenance == 1
    assert summary.already_structured == 1
    assert summary.provider_missing == 1
    assert summary.no_named_recipients == 1
    assert summary.message_mismatch == 1
    assert summary.updated == 1
    assert summary.next_cursor == good.id
    assert [call[2] for call in transport.calls] == ["missing", "unnamed", "mismatch", "good"]
    assert "to_participants" not in db_session.get(Object, invalid.id).metadata_
    assert db_session.get(Object, structured.id).metadata_["to_participants"][0]["address"] == (
        "a@example.com"
    )
    assert "to_participants" not in db_session.get(Object, missing.id).metadata_
    assert "to_participants" not in db_session.get(Object, unnamed.id).metadata_
    assert "to_participants" not in db_session.get(Object, mismatch.id).metadata_
    assert db_session.get(Object, good.id).metadata_["to_participants"] == NAMED_TO
    again = _repair(db_session, user.id, account, transport, cursor=summary.next_cursor)
    assert again.provider_calls == 0
    assert again.exhausted is True


def test_non_dict_payload_does_not_mutate(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    mail = _mail(db_session, user, account, object_id=UUID(int=1), message_id="m-1")
    before = _snapshot(mail)
    transport = MessageTransport(lambda _token, _user_id, _message_id: ["not-a-dict"])

    summary = _repair(db_session, user.id, account, transport)

    assert summary.message_mismatch == 1
    assert summary.updated == 0
    assert summary.next_cursor == mail.id
    assert _snapshot(db_session.get(Object, mail.id)) == before


def test_missing_account_raises(db_session) -> None:
    user = _user(db_session)
    with pytest.raises(GoogleConnectorError):
        GmailRecipientRepairService(db_session).repair_named_recipients(
            user.id,
            UUID(int=9),
            MessageTransport(lambda _token, _user_id, _message_id: {}),
            TOKEN,
        )


@pytest.mark.parametrize(
    "error",
    [
        GoogleApiError("unavailable", operation="get_message", status_code=503, retryable=True),
        GoogleOAuthError("unauthorized", status_code=401),
        GoogleConfigurationError("not configured"),
    ],
)
def test_non_404_errors_propagate_without_commit(db_session, monkeypatch, error) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    mail = _mail(db_session, user, account, object_id=UUID(int=1), message_id="m-1")
    before = _snapshot(mail)
    account_before = _account_snapshot(account)

    class Failing(MessageTransport):
        def get_message(self, access_token, user_id, message_id):
            raise error

    def fail_commit():
        raise AssertionError("commit")

    def fail_rollback():
        raise AssertionError("rollback")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", fail_rollback)
    with pytest.raises(type(error)):
        _repair(db_session, user.id, account, Failing(lambda *_args: {}))
    assert _snapshot(db_session.get(Object, mail.id)) == before
    assert _account_snapshot(account) == account_before


def _repair(db_session, user_id, account, transport, cursor=None):
    return GmailRecipientRepairService(db_session).repair_named_recipients(
        user_id,
        account.id,
        transport,
        TOKEN,
        cursor=cursor,
    )


def _user(db_session, name: str = "gmail-user") -> User:
    user = User(display_name=name)
    db_session.add(user)
    db_session.flush()
    return user


def _account(db_session, user_id, *, email=EMAIL) -> GoogleAccount:
    account = GoogleAccount(
        user_id=user_id,
        email=email,
        scopes=["gmail"],
        access_token_encrypted="stored-access",
        refresh_token_encrypted="stored-refresh",
        token_expiry=NOW,
        gmail_sync_state={"history": {"start_history_id": "44"}},
    )
    db_session.add(account)
    db_session.flush()
    return account


def _mail(
    db_session,
    user,
    account,
    *,
    object_id: UUID,
    message_id: str,
    source_account_email: str | None | object = None,
    external_id: str | None = None,
    provider: str = "gmail",
    kind: str = "email",
    deleted_at: datetime | None = None,
    status: str | None = None,
    to_participants: list | None = None,
    cc_participants: list | None = None,
) -> Object:
    metadata = {
        "message_id": message_id,
        "thread_id": f"thread-{message_id or object_id.int}",
        "sender": "other@example.com",
        "recipients": list(LEGACY_TO),
        "cc": list(LEGACY_CC),
        "subject": "Hello",
        "timestamp": "2026-10-05T17:00:00+00:00",
        "headers": {"message-id": "<m@example.com>"},
        "labels": ["INBOX"],
        "nested": {"keep": True},
    }
    if source_account_email is None:
        metadata["source_account_email"] = account.email
    elif source_account_email is not _ACCOUNT_EMAIL:
        metadata["source_account_email"] = source_account_email
    if to_participants is not None:
        metadata["to_participants"] = to_participants
    if cc_participants is not None:
        metadata["cc_participants"] = cc_participants
    if external_id is None and message_id.strip():
        external_id = message_id
    obj = Object(
        id=object_id,
        user_id=user.id,
        kind=kind,
        provider=provider,
        external_id=external_id,
        origin="source",
        state="observed",
        title="legacy title",
        body="legacy body",
        metadata_=metadata,
        occurred_at=NOW,
        deleted_at=deleted_at,
        status=status,
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def _provider_message(message_id: str, *, to: str = TO, cc: str = CC) -> dict:
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "other@example.com"},
                {"name": "To", "value": to},
                {"name": "Cc", "value": cc},
                {"name": "Subject", "value": "Hello"},
            ],
        },
    }


def _snapshot(obj: Object) -> dict:
    return {
        "title": obj.title,
        "body": obj.body,
        "occurred_at": obj.occurred_at,
        "deleted_at": obj.deleted_at,
        "external_id": obj.external_id,
        "status": obj.status,
        "metadata": dict(obj.metadata_ or {}),
    }


def _content(obj: Object) -> dict:
    snapshot = _snapshot(obj)
    snapshot.pop("metadata")
    return snapshot


def _account_snapshot(account: GoogleAccount) -> dict:
    return {
        "email": account.email,
        "access_token_encrypted": account.access_token_encrypted,
        "refresh_token_encrypted": account.refresh_token_encrypted,
        "token_expiry": account.token_expiry,
        "gmail_sync_state": dict(account.gmail_sync_state),
        "scopes": list(account.scopes),
    }


def _job_count(db_session, user_id) -> int:
    return int(
        db_session.scalar(select(func.count()).select_from(Job).where(Job.user_id == user_id)) or 0
    )
