"""Yandex recipient repair adds only missing HG2B2 names for the current INBOX UID."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.connectors.yandex.constants import DEFAULT_MAIL_FOLDER
from app.connectors.yandex.errors import YandexConnectorError, YandexImapError
from app.connectors.yandex.mail_normalize import (
    build_external_id,
    normalize_imap_message,
    yandex_structured_recipients,
)
from app.db.models import Job, Object, User, YandexMailAccount
from app.domain.person_identity import normalize_email
from app.domain.role_import_participants import participant_identities
from app.services import yandex_mail_recipient_repair_service as repair_module
from app.services.yandex_mail_recipient_repair_service import (
    RECIPIENT_REPAIR_MAX_FETCHES,
    RECIPIENT_REPAIR_SCAN_LIMIT,
    YandexMailRecipientRepairService,
)

EMAIL = "owner@yandex.example"
OTHER_EMAIL = "other@yandex.example"
NOW = datetime(2026, 10, 5, 18, tzinfo=UTC)
UIDVALIDITY = 7
TO = 'Ирина Сергеевна <irina@example.com>, "Doe, John" <john@example.com>, bare@example.com'
CC = "  Анна\tПетрова  <anna@example.com>, bare-cc@example.com"
LEGACY_TO = ["irina@example.com", "john@example.com", "bare@example.com"]
LEGACY_CC = ["anna@example.com", "bare-cc@example.com"]
NAMED_TO = [
    {"address": "irina@example.com", "display_name": "Ирина Сергеевна"},
    {"address": "john@example.com", "display_name": "Doe, John"},
]
NAMED_CC = [{"address": "anna@example.com", "display_name": "Анна Петрова"}]
_OMIT = object()


class FolderTransport:
    def __init__(self, uidvalidity, messages):
        self.uidvalidity = uidvalidity
        self.messages = messages
        self.selects: list[str] = []
        self.fetches: list[tuple[str, int]] = []

    def select_folder(self, folder):
        self.selects.append(folder)
        if isinstance(self.uidvalidity, Exception):
            raise self.uidvalidity
        return self.uidvalidity

    def fetch_message(self, folder, uid):
        self.fetches.append((folder, uid))
        value = self.messages(folder, uid) if callable(self.messages) else self.messages[uid]
        if isinstance(value, Exception):
            raise value
        return value

    def __getattr__(self, name):
        raise AssertionError(name)


def test_repair_source_has_no_sync_or_credential_path() -> None:
    source = inspect.getsource(repair_module)
    for banned in (
        "ImaplibTransport",
        "search_uids",
        "list_mailboxes",
        "fetch_internaldate",
        "app_password",
        ".commit(",
        ".rollback(",
        "provider_missing",
    ):
        assert banned not in source


def test_shared_helper_matches_ordinary_yandex_normalization() -> None:
    raw = _rfc822(TO, CC)
    normalized = normalize_imap_message(raw, DEFAULT_MAIL_FOLDER, 42, UIDVALIDITY)
    parsed = message_from_bytes(raw, policy=policy.default)
    assert yandex_structured_recipients(parsed) == (
        normalized["metadata"]["to_participants"],
        normalized["metadata"]["cc_participants"],
    )
    assert normalized["metadata"]["recipients"] == LEGACY_TO
    assert normalized["metadata"]["cc"] == LEGACY_CC
    bare = message_from_bytes(
        _rfc822("bare@example.com", "  <bare-cc@example.com>"),
        policy=policy.default,
    )
    assert yandex_structured_recipients(bare) == ([], [])


def test_rows_outside_provenance_make_no_provider_call(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    transport = FolderTransport(UIDVALIDITY, {})
    summary = _repair(db_session, user.id, account, transport)
    assert summary.folder_select_calls == 0
    assert summary.message_fetches == 0
    assert summary.current_uidvalidity is None
    assert summary.exhausted is True

    _mail(
        db_session,
        user,
        account,
        object_id=UUID(int=1),
        uid=1,
        to_participants=list(NAMED_TO),
        cc_participants=list(NAMED_CC),
    )
    _mail(db_session, user, account, object_id=UUID(int=2), uid=2, folder="Sent")
    _mail(db_session, user, account, object_id=UUID(int=3), uid=3, source_account_email=_OMIT)
    again = _repair(db_session, user.id, account, transport)
    assert transport.selects == []
    assert transport.fetches == []
    assert again.folder_select_calls == 0
    assert again.message_fetches == 0


def test_only_current_inbox_rows_are_repaired(db_session) -> None:
    user = _user(db_session)
    other = _user(db_session, "other")
    account = _account(db_session, user.id)
    other_account = _account(db_session, user.id, email=OTHER_EMAIL)
    valid = _mail(db_session, user, account, object_id=UUID(int=10), uid=10)
    hidden = _mail(db_session, user, account, object_id=UUID(int=1), uid=1, status="deleted")
    stale = _mail(
        db_session,
        user,
        account,
        object_id=UUID(int=8),
        uid=8,
        uidvalidity=6,
        message_id="same-id",
    )
    untouched = [
        hidden,
        _mail(db_session, other, other_account, object_id=UUID(int=2), uid=2),
        _mail(db_session, user, account, object_id=UUID(int=3), uid=3, source_account_email=_OMIT),
        _mail(db_session, user, other_account, object_id=UUID(int=4), uid=4),
        _mail(db_session, user, account, object_id=UUID(int=5), uid=5, provider="gmail"),
        _mail(db_session, user, account, object_id=UUID(int=6), uid=6, kind="chat_message"),
        _mail(db_session, user, account, object_id=UUID(int=7), uid=7, deleted_at=NOW),
        stale,
        _mail(db_session, user, account, object_id=UUID(int=9), uid=9, folder="Sent"),
        _mail(
            db_session,
            user,
            account,
            object_id=UUID(int=11),
            uid=11,
            to_participants=list(NAMED_TO),
            cc_participants=[{"address": "kept@example.com", "display_name": "Уже Есть"}],
        ),
    ]
    before = {obj.id: _snapshot(obj) for obj in untouched}
    account_before = _account_snapshot(account)
    jobs_before = _job_count(db_session, user.id)
    transport = FolderTransport(UIDVALIDITY, _messages(TO, CC))

    summary = _repair(db_session, user.id, account, transport)

    assert transport.selects == [DEFAULT_MAIL_FOLDER]
    assert transport.fetches == [(DEFAULT_MAIL_FOLDER, 10)]
    assert summary.folder_select_calls == 1
    assert summary.message_fetches == 1
    assert summary.updated == 1
    assert summary.hidden_skipped == 1
    assert summary.uidvalidity_mismatch == 1
    assert summary.current_uidvalidity == UIDVALIDITY
    assert summary.exhausted is True
    stored = db_session.get(Object, valid.id)
    assert stored.metadata_["to_participants"] == NAMED_TO
    assert stored.metadata_["cc_participants"] == NAMED_CC
    assert stored.metadata_["recipients"] == LEGACY_TO
    assert stored.metadata_["cc"] == LEGACY_CC
    assert stored.metadata_["sender"] == "other@example.com"
    assert stored.metadata_["message_id"] == "same-id"
    assert stored.metadata_["folder"] == DEFAULT_MAIL_FOLDER
    assert stored.metadata_["imap_uid"] == 10
    assert stored.metadata_["imap_uidvalidity"] == UIDVALIDITY
    assert stored.metadata_["source_account_email"] == EMAIL
    assert stored.metadata_["nested"] == {"keep": True}
    assert _content(stored) == _content(valid)
    assert db_session.get(Object, stale.id).metadata_["message_id"] == "same-id"
    assert "to_participants" not in db_session.get(Object, stale.id).metadata_
    assert _account_snapshot(account) == account_before
    assert _job_count(db_session, user.id) == jobs_before
    for obj in untouched:
        assert _snapshot(db_session.get(Object, obj.id)) == before[obj.id]


def test_invalid_uid_and_external_id_skip_fetch(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    rows = [
        _mail(db_session, user, account, object_id=UUID(int=1), uid=True),
        _mail(db_session, user, account, object_id=UUID(int=2), uid=0),
        _mail(db_session, user, account, object_id=UUID(int=3), uid="5"),
        _mail(db_session, user, account, object_id=UUID(int=4), uid=4, uidvalidity=True),
        _mail(db_session, user, account, object_id=UUID(int=5), uid=5, uidvalidity=0),
        _mail(db_session, user, account, object_id=UUID(int=6), uid=6, external_id="inbox:7:99"),
    ]
    before = {obj.id: _snapshot(obj) for obj in rows}
    transport = FolderTransport(UIDVALIDITY, _messages(TO, CC))

    summary = _repair(db_session, user.id, account, transport)

    assert transport.selects == [DEFAULT_MAIL_FOLDER]
    assert transport.fetches == []
    assert summary.message_fetches == 0
    assert summary.invalid_provenance == 6
    assert summary.uidvalidity_mismatch == 0
    assert summary.next_cursor == UUID(int=6)
    for obj in rows:
        assert _snapshot(db_session.get(Object, obj.id)) == before[obj.id]


def test_named_fields_fill_only_when_missing(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    only_to = _mail(db_session, user, account, object_id=UUID(int=1), uid=1)
    only_cc = _mail(db_session, user, account, object_id=UUID(int=2), uid=2)
    both = _mail(db_session, user, account, object_id=UUID(int=3), uid=3)
    bare = _mail(db_session, user, account, object_id=UUID(int=4), uid=4)
    kept = _mail(
        db_session,
        user,
        account,
        object_id=UUID(int=5),
        uid=5,
        to_participants=[{"address": "kept-to@example.com", "display_name": "Старый To"}],
    )

    def messages(_folder, uid):
        if uid == 1:
            return _rfc822(TO, "bare-cc@example.com")
        if uid == 2:
            return _rfc822("bare@example.com", CC)
        if uid == 4:
            return _rfc822("bare@example.com", "bare-cc@example.com")
        return _rfc822(TO, CC)

    summary = _repair(db_session, user.id, account, FolderTransport(UIDVALIDITY, messages))

    assert summary.updated == 4
    assert summary.no_named_recipients == 1
    assert summary.folder_select_calls == 1
    to_row = db_session.get(Object, only_to.id)
    cc_row = db_session.get(Object, only_cc.id)
    both_row = db_session.get(Object, both.id)
    bare_row = db_session.get(Object, bare.id)
    kept_row = db_session.get(Object, kept.id)
    assert to_row.metadata_["to_participants"] == NAMED_TO
    assert "cc_participants" not in to_row.metadata_
    assert "to_participants" not in cc_row.metadata_
    assert cc_row.metadata_["cc_participants"] == NAMED_CC
    assert both_row.metadata_["to_participants"] == NAMED_TO
    assert both_row.metadata_["cc_participants"] == NAMED_CC
    assert "to_participants" not in bare_row.metadata_
    assert bare_row.metadata_["recipients"] == LEGACY_TO
    assert kept_row.metadata_["to_participants"] == [
        {"address": "kept-to@example.com", "display_name": "Старый To"}
    ]
    assert kept_row.metadata_["cc_participants"] == NAMED_CC
    assert kept_row.metadata_["recipients"] == LEGACY_TO


def test_repaired_names_qualify_and_self_is_filtered(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    mail = _mail(db_session, user, account, object_id=UUID(int=1), uid=1)
    own_to = f"Owner Name <{EMAIL}>, Ирина Сергеевна <irina@example.com>"
    assert participant_identities(mail, self_identity_keys=set()) == ()

    summary = _repair(
        db_session,
        user.id,
        account,
        FolderTransport(UIDVALIDITY, lambda _folder, _uid: _rfc822(own_to, CC)),
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
        _mail(db_session, user, account, object_id=UUID(int=index), uid=0)
    transport = FolderTransport(UIDVALIDITY, _messages(TO, CC))

    summary = _repair(db_session, user.id, account, transport)

    assert summary.candidates_scanned == RECIPIENT_REPAIR_SCAN_LIMIT
    assert summary.folder_select_calls == 1
    assert summary.message_fetches == 0
    assert summary.next_cursor == UUID(int=100)
    assert summary.exhausted is False
    again = _repair(db_session, user.id, account, transport, cursor=summary.next_cursor)
    assert again.candidates_scanned == 20
    assert again.folder_select_calls == 1
    assert again.message_fetches == 0
    assert again.exhausted is True
    assert transport.fetches == []
    assert transport.selects == [DEFAULT_MAIL_FOLDER, DEFAULT_MAIL_FOLDER]


def test_fetches_stop_at_twenty(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    for index in range(1, 26):
        _mail(db_session, user, account, object_id=UUID(int=index), uid=index)
    transport = FolderTransport(UIDVALIDITY, _messages(TO, CC))

    summary = _repair(db_session, user.id, account, transport)

    assert summary.message_fetches == RECIPIENT_REPAIR_MAX_FETCHES
    assert summary.updated == 20
    assert summary.folder_select_calls == 1
    assert summary.next_cursor == UUID(int=20)
    assert summary.exhausted is False
    assert transport.fetches == [(DEFAULT_MAIL_FOLDER, index) for index in range(1, 21)]
    assert "to_participants" not in db_session.get(Object, UUID(int=21)).metadata_
    again = _repair(db_session, user.id, account, transport, cursor=summary.next_cursor)
    assert again.message_fetches == 5
    assert again.updated == 5
    assert again.folder_select_calls == 1
    assert again.exhausted is True


def test_bad_rows_advance_the_cursor(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    invalid = _mail(db_session, user, account, object_id=UUID(int=1), uid=0)
    stale = _mail(db_session, user, account, object_id=UUID(int=2), uid=2, uidvalidity=6)
    malformed = _mail(db_session, user, account, object_id=UUID(int=3), uid=3)
    unnamed = _mail(db_session, user, account, object_id=UUID(int=4), uid=4)
    good = _mail(db_session, user, account, object_id=UUID(int=5), uid=5)

    def messages(_folder, uid):
        if uid == 3:
            return b""
        if uid == 4:
            return _rfc822("bare@example.com", "bare-cc@example.com")
        return _rfc822(TO, CC)

    transport = FolderTransport(UIDVALIDITY, messages)
    summary = _repair(db_session, user.id, account, transport)

    assert summary.invalid_provenance == 1
    assert summary.uidvalidity_mismatch == 1
    assert summary.message_malformed == 1
    assert summary.no_named_recipients == 1
    assert summary.updated == 1
    assert summary.next_cursor == good.id
    assert transport.fetches == [
        (DEFAULT_MAIL_FOLDER, 3),
        (DEFAULT_MAIL_FOLDER, 4),
        (DEFAULT_MAIL_FOLDER, 5),
    ]
    assert "to_participants" not in db_session.get(Object, invalid.id).metadata_
    assert "to_participants" not in db_session.get(Object, stale.id).metadata_
    assert "to_participants" not in db_session.get(Object, malformed.id).metadata_
    assert "to_participants" not in db_session.get(Object, unnamed.id).metadata_
    assert db_session.get(Object, good.id).metadata_["to_participants"] == NAMED_TO
    again = _repair(db_session, user.id, account, transport, cursor=summary.next_cursor)
    assert again.message_fetches == 0
    assert again.folder_select_calls == 0
    assert again.exhausted is True


def test_non_bytes_payload_does_not_mutate(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    mail = _mail(db_session, user, account, object_id=UUID(int=1), uid=1)
    before = _snapshot(mail)
    transport = FolderTransport(UIDVALIDITY, lambda _folder, _uid: None)

    summary = _repair(db_session, user.id, account, transport)

    assert summary.message_malformed == 1
    assert summary.updated == 0
    assert _snapshot(db_session.get(Object, mail.id)) == before


def test_missing_account_raises(db_session) -> None:
    user = _user(db_session)
    with pytest.raises(YandexConnectorError):
        YandexMailRecipientRepairService(db_session).repair_named_recipients(
            user.id,
            UUID(int=9),
            FolderTransport(UIDVALIDITY, {}),
        )


def test_select_error_propagates_without_mutation(db_session, monkeypatch) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    mail = _mail(db_session, user, account, object_id=UUID(int=1), uid=1)
    before = _snapshot(mail)
    account_before = _account_snapshot(account)
    _forbid_transaction(db_session, monkeypatch)
    transport = FolderTransport(YandexImapError("select failed"), _messages(TO, CC))

    with pytest.raises(YandexImapError):
        _repair(db_session, user.id, account, transport)
    assert transport.fetches == []
    assert _snapshot(db_session.get(Object, mail.id)) == before
    assert _account_snapshot(account) == account_before


def test_fetch_error_propagates_without_classification(db_session, monkeypatch) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    mail = _mail(db_session, user, account, object_id=UUID(int=1), uid=1)
    before = _snapshot(mail)
    account_before = _account_snapshot(account)
    _forbid_transaction(db_session, monkeypatch)
    transport = FolderTransport(UIDVALIDITY, lambda _folder, _uid: YandexImapError("fetch failed"))

    with pytest.raises(YandexImapError):
        _repair(db_session, user.id, account, transport)
    assert transport.selects == [DEFAULT_MAIL_FOLDER]
    assert transport.fetches == [(DEFAULT_MAIL_FOLDER, 1)]
    assert _snapshot(db_session.get(Object, mail.id)) == before
    assert _account_snapshot(account) == account_before


def _forbid_transaction(db_session, monkeypatch) -> None:
    def fail_commit():
        raise AssertionError("commit")

    def fail_rollback():
        raise AssertionError("rollback")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", fail_rollback)


def _repair(db_session, user_id, account, transport, cursor=None):
    return YandexMailRecipientRepairService(db_session).repair_named_recipients(
        user_id,
        account.id,
        transport,
        cursor=cursor,
    )


def _user(db_session, name: str = "yandex-user") -> User:
    user = User(display_name=name)
    db_session.add(user)
    db_session.flush()
    return user


def _account(db_session, user_id, *, email=EMAIL) -> YandexMailAccount:
    account = YandexMailAccount(
        user_id=user_id,
        email=email,
        app_password_encrypted="enc-secret",
        sync_state={
            "inbox_uidvalidity": UIDVALIDITY,
            "inbox_last_uid": 100,
            "history_backfill": {"inbox_uidvalidity": UIDVALIDITY, "covered": True},
        },
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
    uid: object,
    uidvalidity: object = UIDVALIDITY,
    folder: str = DEFAULT_MAIL_FOLDER,
    source_account_email: object = None,
    external_id: str | None = None,
    provider: str = "yandex_mail",
    kind: str = "email",
    deleted_at: datetime | None = None,
    status: str | None = None,
    message_id: str = "same-id",
    to_participants: list | None = None,
    cc_participants: list | None = None,
) -> Object:
    metadata = {
        "folder": folder,
        "imap_uid": uid,
        "imap_uidvalidity": uidvalidity,
        "message_id": message_id,
        "sender": "other@example.com",
        "recipients": list(LEGACY_TO),
        "cc": list(LEGACY_CC),
        "subject": "Hello",
        "timestamp": "2026-10-05T18:00:00+00:00",
        "headers": {"message-id": "<m@example.com>"},
        "nested": {"keep": True},
    }
    if source_account_email is None:
        metadata["source_account_email"] = account.email
    elif source_account_email is not _OMIT:
        metadata["source_account_email"] = source_account_email
    if to_participants is not None:
        metadata["to_participants"] = to_participants
    if cc_participants is not None:
        metadata["cc_participants"] = cc_participants
    if (
        external_id is None
        and isinstance(uid, int)
        and not isinstance(uid, bool)
        and uid > 0
        and isinstance(uidvalidity, int)
        and not isinstance(uidvalidity, bool)
        and uidvalidity > 0
    ):
        external_id = build_external_id(DEFAULT_MAIL_FOLDER, uidvalidity, uid)
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


def _rfc822(to: str, cc: str | None) -> bytes:
    message = EmailMessage(policy=policy.default)
    message["Subject"] = "Hello"
    message["From"] = "other@example.com"
    message["To"] = to
    if cc is not None:
        message["Cc"] = cc
    message["Date"] = "Thu, 01 Oct 2026 12:00:00 +0000"
    message["Message-ID"] = "<m@example.com>"
    message.set_content("Hello")
    return message.as_bytes()


def _messages(to: str, cc: str):
    raw = _rfc822(to, cc)

    def fetch(_folder, _uid):
        return raw

    return fetch


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


def _account_snapshot(account: YandexMailAccount) -> dict:
    return {
        "email": account.email,
        "app_password_encrypted": account.app_password_encrypted,
        "imap_host": account.imap_host,
        "imap_port": account.imap_port,
        "sync_state": dict(account.sync_state),
    }


def _job_count(db_session, user_id) -> int:
    return int(
        db_session.scalar(select(func.count()).select_from(Job).where(Job.user_id == user_id)) or 0
    )
