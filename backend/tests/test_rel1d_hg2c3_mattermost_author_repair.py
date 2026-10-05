"""Mattermost author repair uses stored author ids and the HG2B1 display helper."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.mattermost.errors import (
    MattermostConfigurationError,
    MattermostTransportError,
    MattermostUnauthorizedError,
)
from app.connectors.mattermost.normalize import author_human_display
from app.db.models import Job, MattermostAccount, Object, User
from app.domain.person_identity import normalize_mattermost_user_id
from app.domain.role_import_participants import participant_identities
from app.services import mattermost_author_repair_service as repair_module
from app.services.mattermost_author_repair_service import (
    AUTHOR_REPAIR_MAX_AUTHOR_IDS,
    AUTHOR_REPAIR_SCAN_LIMIT,
    MattermostAuthorRepairService,
)
from tests.test_telegram_mtproto_a3 import KEY

SERVER = "https://chat.example.com"
NOW = datetime(2026, 10, 5, 4, tzinfo=UTC)


class ProfileTransport:
    def __init__(self, profiles):
        self.profiles = profiles
        self.calls: list[list[str]] = []
        self.closed = False

    def get_users_by_ids(self, user_ids):
        self.calls.append(list(user_ids))
        return self.profiles(user_ids) if callable(self.profiles) else self.profiles

    def close(self):
        self.closed = True

    def __getattr__(self, name):
        raise AssertionError(name)


def test_repair_source_does_not_fetch_posts_or_commit() -> None:
    source = inspect.getsource(repair_module)
    assert "get_posts" not in source
    assert "sync_account" not in source
    assert ".commit(" not in source
    assert author_human_display({"username": "bob", "display_name": "Bob"}) is None
    assert author_human_display({"first_name": "Ирина", "last_name": "Сергеевна"}) == "Ирина Сергеевна"


def test_only_matching_rows_receive_the_human_display(db_session) -> None:
    user = _user(db_session)
    other = _user(db_session, "other")
    account = _account(db_session, user.id, sync_state={"history_backfill": {"covered_start_ms": 7}})
    other_account = _account(db_session, other.id, remote_user_id="other-remote", server_url=SERVER)
    valid = _post(db_session, user, account, object_id=UUID(int=10), author_id="author-1")
    hidden = _post(
        db_session, user, account, object_id=UUID(int=1), author_id="hidden-author", status="deleted"
    )
    untouched = [
        hidden,
        _post(db_session, other, other_account, object_id=UUID(int=2), author_id="author-1"),
        _post(
            db_session,
            user,
            account,
            object_id=UUID(int=3),
            author_id="author-1",
            server_url="https://other.example.com",
        ),
        _post(
            db_session,
            user,
            account,
            object_id=UUID(int=4),
            author_id="author-1",
            provider="gmail",
            kind="email",
        ),
        _post(
            db_session,
            user,
            account,
            object_id=UUID(int=5),
            author_id="author-1",
            deleted_at=NOW,
        ),
        _post(
            db_session,
            user,
            account,
            object_id=UUID(int=6),
            author_id="author-1",
            display="Уже Есть",
        ),
        _post(db_session, user, account, object_id=UUID(int=7), author_id="   "),
    ]
    before = {obj.id: _snapshot(obj) for obj in untouched}
    state_before = dict(account.sync_state)
    jobs_before = _job_count(db_session, user.id)
    transport = ProfileTransport(
        [{"id": "author-1", "display_name": "Ирина Сергеевна", "username": "ira"}]
    )

    summary = _repair(db_session, account, transport)

    assert transport.calls == [["author-1"]]
    assert transport.closed is False
    assert summary.updated == 1
    assert summary.hidden_skipped == 1
    assert summary.invalid_provenance == 1
    assert summary.provider_calls == 1
    stored = db_session.get(Object, valid.id)
    assert stored.metadata_["author_display_name"] == "Ирина Сергеевна"
    assert stored.metadata_["author_user_id"] == "author-1"
    assert stored.metadata_["author_username"] == "ira"
    assert stored.metadata_["nested"] == {"room": "alpha"}
    assert stored.metadata_["channel_id"] == "channel-1"
    assert stored.title == "legacy title"
    assert stored.body == "legacy body"
    assert stored.occurred_at == NOW
    assert stored.deleted_at is None
    assert stored.external_id == valid.external_id
    assert stored.status is None
    for obj in untouched:
        assert _snapshot(db_session.get(Object, obj.id)) == before[obj.id]
    assert dict(db_session.get(MattermostAccount, account.id).sync_state) == state_before
    assert _job_count(db_session, user.id) == jobs_before


def test_blank_author_and_empty_batch_do_not_call_the_provider(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    blank = _post(db_session, user, account, object_id=UUID(int=1), author_id="")
    missing = _post(db_session, user, account, object_id=UUID(int=2), author_id=None)
    calls = []

    def factory(_snapshot):
        calls.append("open")
        return ProfileTransport([])

    summary = MattermostAuthorRepairService(
        db_session, CredentialEncryption(KEY), factory
    ).repair_author_display(user.id, account.id)

    assert calls == []
    assert summary.provider_calls == 0
    assert summary.invalid_provenance == 2
    assert summary.unique_author_ids == 0
    assert summary.next_cursor == missing.id
    assert summary.exhausted is True
    assert "author_display_name" not in db_session.get(Object, blank.id).metadata_


def test_scan_and_author_ids_are_bounded_and_deduplicated(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    for index in range(1, 102):
        _post(
            db_session,
            user,
            account,
            object_id=UUID(int=index),
            author_id=f"author-{index}",
        )
    transport = ProfileTransport(
        lambda user_ids: [{"id": author_id, "display_name": f"Имя {author_id}", "username": "x"} for author_id in user_ids]
    )

    first = _repair(db_session, account, transport)
    assert AUTHOR_REPAIR_SCAN_LIMIT == 100
    assert AUTHOR_REPAIR_MAX_AUTHOR_IDS == 100
    assert first.candidates_scanned == 100
    assert first.unique_author_ids == 100
    assert first.provider_calls == 1
    assert len(transport.calls) == 1
    assert len(transport.calls[0]) == 100
    assert len(set(transport.calls[0])) == 100
    assert first.exhausted is False

    second = _repair(db_session, account, transport, cursor=first.next_cursor)
    assert second.candidates_scanned == 1
    assert second.unique_author_ids == 1
    assert second.exhausted is True


def test_duplicate_author_is_requested_once(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    for index in range(1, 4):
        _post(db_session, user, account, object_id=UUID(int=index), author_id="same-author")
    transport = ProfileTransport(
        [{"id": "same-author", "first_name": "Ирина", "last_name": "Сергеевна", "username": "ira"}]
    )

    summary = _repair(db_session, account, transport)

    assert transport.calls == [["same-author"]]
    assert summary.unique_author_ids == 1
    assert summary.updated == 3
    assert summary.provider_calls == 1


def test_unrequested_missing_and_non_human_profiles_do_not_mutate(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    missing = _post(db_session, user, account, object_id=UUID(int=1), author_id="missing")
    username_only = _post(db_session, user, account, object_id=UUID(int=2), author_id="username-only")
    same_name = _post(db_session, user, account, object_id=UUID(int=3), author_id="same-name")
    first_only = _post(db_session, user, account, object_id=UUID(int=4), author_id="first-only")
    last_only = _post(db_session, user, account, object_id=UUID(int=5), author_id="last-only")
    nickname = _post(db_session, user, account, object_id=UUID(int=6), author_id="nickname")
    both_names = _post(
        db_session,
        user,
        account,
        object_id=UUID(int=7),
        author_id="both-names",
        metadata_extra={"sender_note": "keep"},
    )
    distinct = _post(db_session, user, account, object_id=UUID(int=8), author_id="distinct")
    own = _post(db_session, user, account, object_id=UUID(int=9), author_id=account.remote_user_id)
    before_missing = _snapshot(missing)
    transport = ProfileTransport(
        [
            {"id": "not-requested", "display_name": "Чужой Профиль", "username": "stranger"},
            {"id": "username-only", "username": "ira", "nickname": "Ира", "email": "ira@example.com"},
            {"id": "same-name", "username": "Bob", "display_name": "bob"},
            {"id": "first-only", "username": "ira", "first_name": "Ирина"},
            {"id": "last-only", "username": "ira", "last_name": "Сергеевна"},
            {"id": "nickname", "username": "ira", "nickname": "Ира", "email": "ira@example.com"},
            {
                "id": "both-names",
                "username": "Bob",
                "display_name": "bob",
                "first_name": "Ирина",
                "last_name": "Сергеевна",
            },
            {"id": "distinct", "username": "ira", "display_name": "Ирина Сергеевна"},
            {"id": account.remote_user_id, "username": "me", "display_name": "Свой Профиль"},
        ]
    )

    summary = _repair(db_session, account, transport)

    assert summary.profile_missing == 1
    assert summary.no_human_display == 5
    assert summary.updated == 3
    assert _snapshot(db_session.get(Object, missing.id)) == before_missing
    for obj in (username_only, same_name, first_only, last_only, nickname):
        assert "author_display_name" not in db_session.get(Object, obj.id).metadata_
    both = db_session.get(Object, both_names.id)
    assert both.metadata_["author_display_name"] == "Ирина Сергеевна"
    assert both.metadata_["sender_note"] == "keep"
    assert both.metadata_["author_username"] == "ira"
    distinct_row = db_session.get(Object, distinct.id)
    assert distinct_row.metadata_["author_display_name"] == "Ирина Сергеевна"
    identities = participant_identities(distinct_row, self_identity_keys=set())
    assert [(item.canonical_value, item.display_value) for item in identities] == [
        ("distinct", "Ирина Сергеевна")
    ]
    own_row = db_session.get(Object, own.id)
    assert own_row.metadata_["author_display_name"] == "Свой Профиль"
    own_identity = normalize_mattermost_user_id(SERVER, account.remote_user_id)
    self_key = (
        own_identity.provider,
        own_identity.identity_type,
        own_identity.realm,
        own_identity.canonical_value,
    )
    assert participant_identities(own_row, self_identity_keys={self_key}) == ()
    assert summary.next_cursor == own.id

    again = _repair(db_session, account, transport, cursor=summary.next_cursor)
    assert again.provider_calls == 0
    assert again.exhausted is True
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "error",
    [
        MattermostUnauthorizedError("unauthorized"),
        MattermostTransportError("unavailable"),
        MattermostConfigurationError("not configured"),
    ],
)
def test_profile_errors_propagate_without_commit(db_session, monkeypatch, error) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    obj = _post(db_session, user, account, object_id=UUID(int=1), author_id="author-1")
    before = _snapshot(obj)

    class Failing(ProfileTransport):
        def get_users_by_ids(self, user_ids):
            raise error

    def fail_commit():
        raise AssertionError("commit")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(type(error)):
        _repair(db_session, account, Failing([]))
    assert _snapshot(db_session.get(Object, obj.id)) == before


def test_owned_http_transport_is_closed(db_session, monkeypatch) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    _post(db_session, user, account, object_id=UUID(int=1), author_id="author-1")
    closed = {}

    class Recording:
        def __init__(self, base_url, access_token, http_client=None):
            self.base_url = base_url
            self.access_token = access_token

        def get_users_by_ids(self, user_ids):
            return [{"id": "author-1", "display_name": "Ирина Сергеевна", "username": "ira"}]

        def close(self):
            closed["url"] = self.base_url
            closed["token"] = self.access_token

        def __getattr__(self, name):
            raise AssertionError(name)

    monkeypatch.setattr(repair_module, "MattermostHttpTransport", Recording)
    summary = MattermostAuthorRepairService(db_session, CredentialEncryption(KEY)).repair_author_display(
        user.id, account.id
    )
    assert summary.updated == 1
    assert summary.provider_calls == 1
    assert closed["url"] == SERVER
    assert closed["token"] == "mattermost-token"


def _repair(db_session, account, transport, cursor=None):
    def factory(_snapshot):
        return transport

    return MattermostAuthorRepairService(
        db_session, CredentialEncryption(KEY), factory
    ).repair_author_display(account.user_id, account.id, cursor=cursor)


def _user(db_session, name: str = "mm-user") -> User:
    user = User(display_name=name)
    db_session.add(user)
    db_session.flush()
    return user


def _account(db_session, user_id, *, remote_user_id="self-user", server_url=SERVER, sync_state=None):
    account = MattermostAccount(
        user_id=user_id,
        server_url=server_url,
        remote_user_id=remote_user_id,
        username="me",
        access_token_encrypted=CredentialEncryption(KEY).encrypt("mattermost-token"),
        sync_state=sync_state or {"channels": {"c1": {"edit_sweep_watermark_ms": 9}}},
    )
    db_session.add(account)
    db_session.flush()
    return account


def _post(
    db_session,
    user,
    account,
    *,
    object_id: UUID,
    author_id: str | None,
    server_url: str = SERVER,
    provider: str = "mattermost",
    kind: str = "chat_message",
    display: str | None = None,
    deleted_at: datetime | None = None,
    status: str | None = None,
    metadata_extra: dict | None = None,
) -> Object:
    metadata = {
        "server_url": server_url,
        "account_id": str(account.id),
        "channel_id": "channel-1",
        "author_username": "ira",
        "nested": {"room": "alpha"},
        "post_id": f"post-{object_id.int}",
    }
    if author_id is not None:
        metadata["author_user_id"] = author_id
    if display is not None:
        metadata["author_display_name"] = display
    if metadata_extra:
        metadata.update(metadata_extra)
    obj = Object(
        id=object_id,
        user_id=user.id,
        kind=kind,
        provider=provider,
        external_id=f"{server_url}|post-{object_id.int}",
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


def _job_count(db_session, user_id) -> int:
    return int(
        db_session.scalar(select(func.count()).select_from(Job).where(Job.user_id == user_id)) or 0
    )
