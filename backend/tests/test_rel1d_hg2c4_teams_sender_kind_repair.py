"""Teams sender-kind repair refetches one stored message and writes only the kind."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.connectors.teams.errors import (
    TeamsConfigurationError,
    TeamsConnectorError,
    TeamsRateLimitedError,
    TeamsReconnectRequiredError,
    TeamsSyncError,
)
from app.connectors.teams.normalize import build_external_id
from app.db.models import Job, Object, TeamsAccount, TeamsSubscription, User
from app.domain.person_identity import normalize_teams_user_id
from app.domain.role_import_participants import participant_identities
from app.services import teams_sender_kind_repair_service as repair_module
from app.services.teams_sender_kind_repair_service import (
    SENDER_KIND_REPAIR_MAX_LOOKUPS,
    SENDER_KIND_REPAIR_MAX_PER_CHAT,
    SENDER_KIND_REPAIR_SCAN_LIMIT,
    TeamsSenderKindRepairService,
)

TENANT = "11111111-1111-4111-8111-111111111111"
MS_USER = "22222222-2222-4222-8222-222222222222"
SENDER = "33333333-3333-4333-8333-333333333333"
OTHER_SENDER = "44444444-4444-4444-8444-444444444444"
OTHER_TENANT = "55555555-5555-4555-8555-555555555555"
OTHER_MS_USER = "66666666-6666-4666-8666-666666666666"
NOW = datetime(2026, 10, 5, 15, tzinfo=UTC)
CHAT = "19:room@thread.v2"


class ChatTransport:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, str]] = []

    def get_chat_message(self, chat_id, message_id):
        self.calls.append((chat_id, message_id))
        return self.handler(chat_id, message_id)

    def __getattr__(self, name):
        raise AssertionError(name)


def test_repair_source_has_no_token_sync_or_materializer_path() -> None:
    source = inspect.getsource(repair_module)
    for banned in (
        "TeamsTokenService",
        "acquire_access_token",
        "upsert_message",
        "sync_account",
        "list_chats",
        "list_chat_messages",
        "oauth",
        ".commit(",
        ".rollback(",
    ):
        assert banned not in source


def test_only_matching_inbound_rows_are_repaired(db_session) -> None:
    user = _user(db_session)
    other = _user(db_session, "other")
    account = _account(db_session, user.id)
    other_account = _account(
        db_session,
        other.id,
        tenant_id=OTHER_TENANT,
        microsoft_user_id=OTHER_MS_USER,
    )
    subscription = _subscription(db_session, account, user.id)
    valid = _message(db_session, user, account, object_id=UUID(int=10))
    hidden = _message(db_session, user, account, object_id=UUID(int=1), status="deleted")
    blank = _message(
        db_session, user, account, object_id=UUID(int=8), chat_id="   ", display="Пусто"
    )
    untouched = [
        hidden,
        _message(db_session, other, other_account, object_id=UUID(int=2)),
        _message(
            db_session,
            user,
            account,
            object_id=UUID(int=3),
            tenant_id=OTHER_TENANT,
        ),
        _message(
            db_session,
            user,
            account,
            object_id=UUID(int=4),
            teams_user_id=OTHER_MS_USER,
        ),
        _message(db_session, user, account, object_id=UUID(int=5), direction="outbound"),
        _message(
            db_session,
            user,
            account,
            object_id=UUID(int=6),
            provider="gmail",
            kind="email",
        ),
        _message(db_session, user, account, object_id=UUID(int=7), deleted_at=NOW),
        blank,
        _message(db_session, user, account, object_id=UUID(int=9), sender_kind="user"),
    ]
    before = {obj.id: _snapshot(obj) for obj in untouched}
    account_before = _account_snapshot(account)
    subscription_before = _subscription_snapshot(subscription)
    jobs_before = _job_count(db_session, user.id)
    subscriptions_before = _subscription_count(db_session, account.id)
    transport = ChatTransport(lambda chat_id, message_id: _user_payload(chat_id, message_id))

    summary = _repair(db_session, user.id, account, transport)

    assert transport.calls == [(CHAT, "m-10")]
    assert summary.candidates_scanned == 3
    assert summary.provider_calls == 1
    assert summary.updated == 1
    assert summary.hidden_skipped == 1
    assert summary.invalid_provenance == 1
    assert summary.exhausted is True
    stored = db_session.get(Object, valid.id)
    assert stored.metadata_["sender_kind"] == "user"
    assert stored.metadata_["sender_id"] == SENDER
    assert stored.metadata_["sender_display_name"] == "Ирина Сергеева"
    assert stored.metadata_["direction"] == "inbound"
    assert stored.metadata_["nested"] == {"keep": True}
    assert _content(stored) == _content(valid)
    assert participant_identities(stored, self_identity_keys=set())[0].display_value == (
        "Ирина Сергеева"
    )
    for obj in untouched:
        assert _snapshot(db_session.get(Object, obj.id)) == before[obj.id]
    assert _account_snapshot(account) == account_before
    assert _subscription_snapshot(db_session.get(TeamsSubscription, subscription.id)) == (
        subscription_before
    )
    assert _subscription_count(db_session, account.id) == subscriptions_before
    assert _job_count(db_session, user.id) == jobs_before


def test_user_and_application_write_only_sender_kind(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    person = _message(db_session, user, account, object_id=UUID(int=1), sender_id=SENDER.upper())
    app = _message(
        db_session,
        user,
        account,
        object_id=UUID(int=2),
        chat_id="19:app@thread.v2",
        display="Бот Команд",
    )
    before_person = _content(person)
    before_app = _content(app)

    def payload(chat_id, message_id):
        if chat_id == CHAT:
            return _user_payload(chat_id, message_id, sender_id=SENDER, display="Другое Имя")
        return _application_payload(chat_id, message_id, display="Другой Бот")

    summary = _repair(db_session, user.id, account, ChatTransport(payload))

    assert summary.updated == 2
    person_row = db_session.get(Object, person.id)
    app_row = db_session.get(Object, app.id)
    assert person_row.metadata_["sender_kind"] == "user"
    assert app_row.metadata_["sender_kind"] == "application"
    assert person_row.metadata_["sender_display_name"] == "Ирина Сергеева"
    assert person_row.metadata_["sender_id"] == SENDER.upper()
    assert app_row.metadata_["sender_display_name"] == "Бот Команд"
    assert _content(person_row) == before_person
    assert _content(app_row) == before_app
    assert participant_identities(person_row, self_identity_keys=set()) != ()
    assert participant_identities(app_row, self_identity_keys=set()) == ()


def test_self_identity_stays_excluded_after_user_kind(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    own = _message(
        db_session,
        user,
        account,
        object_id=UUID(int=1),
        sender_id=MS_USER,
        display="Свой Профиль",
    )
    before = participant_identities(own, self_identity_keys=set())
    assert before == ()

    summary = _repair(
        db_session,
        user.id,
        account,
        ChatTransport(lambda chat_id, message_id: _user_payload(chat_id, message_id, MS_USER)),
    )

    stored = db_session.get(Object, own.id)
    assert summary.updated == 1
    assert stored.metadata_["sender_kind"] == "user"
    identity = normalize_teams_user_id(account.tenant_id, account.microsoft_user_id)
    self_key = (
        identity.provider,
        identity.identity_type,
        identity.realm,
        identity.canonical_value,
    )
    assert participant_identities(stored, self_identity_keys=set()) != ()
    assert participant_identities(stored, self_identity_keys={self_key}) == ()


def test_invalid_provenance_and_external_id_skip_the_provider(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    rows = [
        _message(db_session, user, account, object_id=UUID(int=1), chat_id=""),
        _message(db_session, user, account, object_id=UUID(int=2), message_id=""),
        _message(db_session, user, account, object_id=UUID(int=3), sender_id=""),
        _message(db_session, user, account, object_id=UUID(int=4), display="  "),
        _message(db_session, user, account, object_id=UUID(int=5), external_id="not-the-graph-id"),
    ]
    before = {obj.id: _snapshot(obj) for obj in rows}
    transport = ChatTransport(lambda chat_id, message_id: _user_payload(chat_id, message_id))

    summary = _repair(db_session, user.id, account, transport)

    assert transport.calls == []
    assert summary.provider_calls == 0
    assert summary.invalid_provenance == 5
    assert summary.updated == 0
    assert summary.next_cursor == UUID(int=5)
    assert summary.exhausted is True
    for obj in rows:
        assert _snapshot(db_session.get(Object, obj.id)) == before[obj.id]


def test_scan_stops_at_one_hundred_rows(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    for index in range(1, 121):
        _message(db_session, user, account, object_id=UUID(int=index), chat_id="")
    transport = ChatTransport(lambda chat_id, message_id: _user_payload(chat_id, message_id))

    summary = _repair(db_session, user.id, account, transport)

    assert summary.candidates_scanned == SENDER_KIND_REPAIR_SCAN_LIMIT
    assert summary.provider_calls == 0
    assert summary.next_cursor == UUID(int=100)
    assert summary.exhausted is False
    again = _repair(db_session, user.id, account, transport, cursor=summary.next_cursor)
    assert again.candidates_scanned == 20
    assert again.provider_calls == 0
    assert again.exhausted is True
    assert transport.calls == []


def test_provider_calls_stop_at_twenty(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    for index in range(1, 26):
        _message(
            db_session,
            user,
            account,
            object_id=UUID(int=index),
            chat_id=f"19:chat-{index}@thread.v2",
        )
    transport = ChatTransport(lambda chat_id, message_id: _user_payload(chat_id, message_id))

    summary = _repair(db_session, user.id, account, transport)

    assert summary.provider_calls == SENDER_KIND_REPAIR_MAX_LOOKUPS
    assert summary.updated == 20
    assert summary.candidates_scanned == 20
    assert summary.next_cursor == UUID(int=20)
    assert summary.exhausted is False
    assert len(transport.calls) == 20
    assert db_session.get(Object, UUID(int=21)).metadata_.get("sender_kind") is None
    again = _repair(db_session, user.id, account, transport, cursor=summary.next_cursor)
    assert again.provider_calls == 5
    assert again.updated == 5
    assert again.exhausted is True


def test_calls_per_chat_stop_at_five(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    for index in range(1, 9):
        _message(db_session, user, account, object_id=UUID(int=index), message_id=f"m-{index}")
    transport = ChatTransport(lambda chat_id, message_id: _user_payload(chat_id, message_id))

    summary = _repair(db_session, user.id, account, transport)

    assert summary.provider_calls == SENDER_KIND_REPAIR_MAX_PER_CHAT
    assert summary.updated == 5
    assert summary.next_cursor == UUID(int=5)
    assert summary.exhausted is False
    assert transport.calls == [(CHAT, f"m-{index}") for index in range(1, 6)]
    again = _repair(db_session, user.id, account, transport, cursor=summary.next_cursor)
    assert again.provider_calls == 3
    assert again.updated == 3
    assert again.exhausted is True


def test_bad_fetches_advance_the_cursor(db_session) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    missing_chat = _message(db_session, user, account, object_id=UUID(int=1), chat_id="")
    unknown = _message(db_session, user, account, object_id=UUID(int=2), message_id="unknown")
    mismatch = _message(db_session, user, account, object_id=UUID(int=3), message_id="mismatch")
    good = _message(db_session, user, account, object_id=UUID(int=4), message_id="good")

    def payload(chat_id, message_id):
        if message_id == "unknown":
            return {"id": message_id, "chatId": chat_id, "from": {"device": {"id": SENDER}}}
        if message_id == "mismatch":
            return _user_payload(chat_id, message_id, sender_id=OTHER_SENDER, display="Ирина Сергеева")
        return _user_payload(chat_id, message_id)

    transport = ChatTransport(payload)
    summary = _repair(db_session, user.id, account, transport)

    assert summary.invalid_provenance == 1
    assert summary.fetched_without_kind == 1
    assert summary.identity_mismatch == 1
    assert summary.updated == 1
    assert summary.next_cursor == good.id
    assert transport.calls == [(CHAT, "unknown"), (CHAT, "mismatch"), (CHAT, "good")]
    assert db_session.get(Object, missing_chat.id).metadata_.get("sender_kind") is None
    assert db_session.get(Object, unknown.id).metadata_.get("sender_kind") is None
    assert db_session.get(Object, mismatch.id).metadata_["sender_display_name"] == "Ирина Сергеева"
    assert db_session.get(Object, mismatch.id).metadata_.get("sender_kind") is None
    assert db_session.get(Object, good.id).metadata_["sender_kind"] == "user"
    again = _repair(db_session, user.id, account, transport, cursor=summary.next_cursor)
    assert again.provider_calls == 0
    assert again.exhausted is True
    assert len(transport.calls) == 3


@pytest.mark.parametrize(
    ("payload", "counter"),
    [
        (lambda chat_id, message_id: ["not-a-dict"], "identity_mismatch"),
        (lambda chat_id, message_id: {"id": "other", "chatId": chat_id}, "identity_mismatch"),
        (
            lambda chat_id, message_id: {
                "id": message_id,
                "chatId": "19:other@thread.v2",
            },
            "identity_mismatch",
        ),
        (
            lambda chat_id, message_id: {
                "id": message_id,
                "chatId": chat_id,
                "deletedDateTime": "2026-10-05T00:00:00Z",
            },
            "identity_mismatch",
        ),
        (
            lambda chat_id, message_id: {
                "id": message_id,
                "chatId": chat_id,
                "messageType": "systemEventMessage",
            },
            "identity_mismatch",
        ),
        (lambda chat_id, message_id: {"id": message_id, "chatId": chat_id}, "fetched_without_kind"),
    ],
)
def test_closed_fetch_failures_do_not_mutate(db_session, payload, counter) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    obj = _message(db_session, user, account, object_id=UUID(int=1))
    before = _snapshot(obj)
    transport = ChatTransport(payload)

    summary = _repair(db_session, user.id, account, transport)

    assert transport.calls == [(CHAT, "m-1")]
    assert getattr(summary, counter) == 1
    assert summary.updated == 0
    assert summary.next_cursor == obj.id
    assert _snapshot(db_session.get(Object, obj.id)) == before


def test_missing_account_raises(db_session) -> None:
    user = _user(db_session)
    with pytest.raises(TeamsConnectorError):
        TeamsSenderKindRepairService(db_session).repair_sender_kind(
            user.id,
            UUID(int=9),
            ChatTransport(lambda chat_id, message_id: {}),
        )


@pytest.mark.parametrize(
    "error",
    [
        TeamsConfigurationError("not configured"),
        TeamsRateLimitedError("slow down", retry_after_seconds=3),
        TeamsReconnectRequiredError("reconnect"),
        TeamsSyncError("graph failed"),
    ],
)
def test_provider_errors_propagate_without_commit(db_session, monkeypatch, error) -> None:
    user = _user(db_session)
    account = _account(db_session, user.id)
    obj = _message(db_session, user, account, object_id=UUID(int=1))
    before = _snapshot(obj)
    account_before = _account_snapshot(account)

    class Failing(ChatTransport):
        def get_chat_message(self, chat_id, message_id):
            raise error

    def fail_commit():
        raise AssertionError("commit")

    def fail_rollback():
        raise AssertionError("rollback")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", fail_rollback)
    with pytest.raises(type(error)):
        _repair(db_session, user.id, account, Failing(lambda chat_id, message_id: {}))
    assert _snapshot(db_session.get(Object, obj.id)) == before
    assert _account_snapshot(account) == account_before


def _repair(db_session, user_id, account, transport, cursor=None):
    return TeamsSenderKindRepairService(db_session).repair_sender_kind(
        user_id,
        account.id,
        transport,
        cursor=cursor,
    )


def _user(db_session, name: str = "teams-user") -> User:
    user = User(display_name=name)
    db_session.add(user)
    db_session.flush()
    return user


def _account(
    db_session,
    user_id,
    *,
    tenant_id=TENANT,
    microsoft_user_id=MS_USER,
) -> TeamsAccount:
    account = TeamsAccount(
        user_id=user_id,
        tenant_id=tenant_id,
        microsoft_user_id=microsoft_user_id,
        auth_status="active",
        access_token_encrypted="access-token",
        refresh_token_encrypted="refresh-token",
        scopes=["Chat.Read"],
        sync_state={"chats": {CHAT: {"last_created_at": "2026-01-01T00:00:00+00:00"}}},
    )
    db_session.add(account)
    db_session.flush()
    return account


def _subscription(db_session, account, user_id) -> TeamsSubscription:
    row = TeamsSubscription(
        account_id=account.id,
        user_id=user_id,
        subscription_id="sub-1",
        resource=f"/users/{MS_USER}/chats/getAllMessages",
        expires_at=NOW,
        client_state_encrypted="state",
        status="active",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _message(
    db_session,
    user,
    account,
    *,
    object_id: UUID,
    chat_id: str = CHAT,
    message_id: str | None = None,
    sender_id: str = SENDER,
    display: str = "Ирина Сергеева",
    direction: str = "inbound",
    tenant_id: str | None = None,
    teams_user_id: str | None = None,
    sender_kind: str | None = None,
    external_id: str | None = None,
    provider: str = "teams",
    kind: str = "chat_message",
    deleted_at: datetime | None = None,
    status: str | None = None,
) -> Object:
    message_id = f"m-{object_id.int}" if message_id is None else message_id
    tenant = account.tenant_id if tenant_id is None else tenant_id
    teams_user = account.microsoft_user_id if teams_user_id is None else teams_user_id
    metadata = {
        "account_id": str(account.id),
        "tenant_id": tenant,
        "teams_user_id": teams_user,
        "direction": direction,
        "sender_id": sender_id,
        "sender_display_name": display,
        "chat_id": chat_id,
        "message_id": message_id,
        "nested": {"keep": True},
        "chat_type": "group",
    }
    if sender_kind is not None:
        metadata["sender_kind"] = sender_kind
    if external_id is None and chat_id.strip() and message_id.strip():
        external_id = build_external_id(account.tenant_id, account.microsoft_user_id, chat_id, message_id)
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


def _user_payload(chat_id, message_id, sender_id=SENDER, display="Fetched Name"):
    return {
        "id": message_id,
        "chatId": chat_id,
        "messageType": "message",
        "from": {"user": {"id": sender_id, "displayName": display}},
    }


def _application_payload(chat_id, message_id, sender_id=SENDER, display="Fetched Bot"):
    return {
        "id": message_id,
        "chatId": chat_id,
        "from": {"application": {"id": sender_id, "displayName": display}},
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


def _account_snapshot(account: TeamsAccount) -> dict:
    return {
        "auth_status": account.auth_status,
        "access_token_encrypted": account.access_token_encrypted,
        "refresh_token_encrypted": account.refresh_token_encrypted,
        "scopes": list(account.scopes),
        "sync_state": dict(account.sync_state),
    }


def _subscription_snapshot(row: TeamsSubscription) -> dict:
    return {
        "subscription_id": row.subscription_id,
        "resource": row.resource,
        "expires_at": row.expires_at,
        "status": row.status,
        "client_state_encrypted": row.client_state_encrypted,
    }


def _job_count(db_session, user_id) -> int:
    return int(
        db_session.scalar(select(func.count()).select_from(Job).where(Job.user_id == user_id)) or 0
    )


def _subscription_count(db_session, account_id) -> int:
    return int(
        db_session.scalar(
            select(func.count())
            .select_from(TeamsSubscription)
            .where(TeamsSubscription.account_id == account_id)
        )
        or 0
    )
