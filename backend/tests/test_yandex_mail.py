import imaplib
import uuid
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.yandex.constants import DEFAULT_MAIL_FOLDER
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.connectors.yandex.errors import YandexConnectorError, YandexImapError
from app.connectors.yandex.imap_transport import (
    FakeImapTransport,
    ImaplibTransport,
    incremental_uids_from_search_result,
    read_uidvalidity_from_response,
)
from app.connectors.yandex.mail_normalize import build_external_id, normalize_imap_message
from app.connectors.yandex.mail_sync import build_yandex_mail_sync_service
from app.db.models import Object, User, YandexMailAccount
from app.main import app
from app.users.bootstrap import BOOTSTRAP_USER_ID


def utcnow() -> datetime:
    return datetime.now(UTC)


def _build_raw_email(
    subject: str = "Yandex test",
    body: str = "Hello from Yandex",
    message_id: str = "<msg@yandex.test>",
) -> bytes:
    msg = EmailMessage(policy=policy.default)
    msg["Subject"] = subject
    msg["From"] = "sender@yandex.ru"
    msg["To"] = "user@yandex.ru"
    msg["Message-ID"] = message_id
    msg["Date"] = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg.set_content(body)
    return msg.as_bytes()


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def client(db_session, auth_headers):
    from tests.conftest import AuthTestClient

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


class FakeImaplibForUidValidity:
    def select(self, folder: str, readonly: bool = True) -> tuple[str, list[bytes]]:
        return "OK", [b"42"]

    def response(self, code: str) -> tuple[str, list[bytes]]:
        if code == "UIDVALIDITY":
            return "UIDVALIDITY", [b"98765"]
        return "NO", [b""]


def test_read_uidvalidity_uses_response_code_not_select_message_count() -> None:
    uidvalidity = read_uidvalidity_from_response(FakeImaplibForUidValidity())
    assert uidvalidity == 98765


def test_read_uidvalidity_raises_when_response_is_none() -> None:
    class BrokenImap:
        def response(self, code: str) -> None:
            return None

    with pytest.raises(YandexImapError, match="UIDVALIDITY response missing"):
        read_uidvalidity_from_response(BrokenImap())


def test_read_uidvalidity_raises_when_response_code_wrong() -> None:
    class BrokenImap:
        def response(self, code: str) -> tuple[str, list[bytes]]:
            return "OK", [b"98765"]

    with pytest.raises(YandexImapError, match="UIDVALIDITY response missing"):
        read_uidvalidity_from_response(BrokenImap())


def test_read_uidvalidity_raises_when_response_data_missing() -> None:
    class BrokenImap:
        def response(self, code: str) -> tuple[str, list]:
            return "UIDVALIDITY", []

    with pytest.raises(YandexImapError, match="UIDVALIDITY response missing"):
        read_uidvalidity_from_response(BrokenImap())


def test_read_uidvalidity_raises_when_response_data_malformed() -> None:
    class BrokenImap:
        def response(self, code: str) -> tuple[str, list[bytes]]:
            return "UIDVALIDITY", [b"not-a-number"]

    with pytest.raises(YandexImapError, match="UIDVALIDITY response malformed"):
        read_uidvalidity_from_response(BrokenImap())


@pytest.mark.parametrize("failure", [OSError("connection reset"), TimeoutError("socket timeout")])
def test_imap_connect_network_failure_is_transient(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    class BrokenConnection:
        def __init__(self, *args, **kwargs):
            raise failure

    monkeypatch.setattr(imaplib, "IMAP4_SSL", BrokenConnection)
    with pytest.raises(YandexImapError) as caught:
        ImaplibTransport("imap.yandex.ru", 993, "user@yandex.ru", "pass").select_folder(
            DEFAULT_MAIL_FOLDER
        )
    assert caught.value.failure_kind == "transient"
    assert caught.value.retryable is True


def test_imap_login_rejection_is_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    class LoginRejected:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, email: str, password: str):
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", LoginRejected)
    with pytest.raises(YandexImapError) as caught:
        ImaplibTransport("imap.yandex.ru", 993, "user@yandex.ru", "pass").select_folder(
            DEFAULT_MAIL_FOLDER
        )
    assert caught.value.failure_kind == "authentication"
    assert caught.value.retryable is False


def test_unrelated_imap_protocol_failure_is_unknown() -> None:
    class BrokenImap:
        def select(self, folder: str, readonly: bool = True):
            raise imaplib.IMAP4.error("BAD malformed command")

    transport = ImaplibTransport("imap.yandex.ru", 993, "user@yandex.ru", "pass")
    transport._imap = BrokenImap()
    with pytest.raises(YandexImapError) as caught:
        transport.select_folder(DEFAULT_MAIL_FOLDER)
    assert caught.value.failure_kind == "unknown"
    assert caught.value.retryable is False


class MisbehavingSearchImap:
    """Simulates IMAP servers that include the last UID in UID N:* search results."""

    def __init__(self, search_uids: list[int]) -> None:
        self._search_uids = search_uids

    def select(self, folder: str, readonly: bool = True) -> tuple[str, list[bytes]]:
        return "OK", [b"42"]

    def response(self, code: str) -> tuple[str, list[bytes]]:
        if code == "UIDVALIDITY":
            return "UIDVALIDITY", [b"1"]
        return "NO", [b""]

    def uid(self, command: str, *args: object) -> tuple[str, list[bytes]]:
        if command == "search":
            payload = b" ".join(str(uid).encode() for uid in self._search_uids)
            return "OK", [payload]
        raise AssertionError(f"unexpected uid command: {command}")


def test_incremental_uids_from_search_filters_uid_at_checkpoint() -> None:
    assert incremental_uids_from_search_result(b"100", after_uid=100, max_results=100) == []


def test_incremental_uids_from_search_oldest_batch_when_server_returns_checkpoint_uid(
) -> None:
    search_uids = list(range(100, 351))
    result = incremental_uids_from_search_result(
        b" ".join(str(uid).encode() for uid in search_uids),
        after_uid=100,
        max_results=100,
    )
    assert result == list(range(101, 201))


def test_imaplib_transport_incremental_search_filters_checkpoint_uid() -> None:
    transport = ImaplibTransport("imap.yandex.ru", 993, "user@yandex.ru", "pass")
    transport._imap = MisbehavingSearchImap([100])
    transport._selected_folder = DEFAULT_MAIL_FOLDER
    transport._uidvalidity = 1
    assert transport.search_uids_incremental(DEFAULT_MAIL_FOLDER, after_uid=100, max_results=100) == []


def test_imaplib_transport_incremental_search_oldest_batch_with_misbehaving_server() -> None:
    transport = ImaplibTransport("imap.yandex.ru", 993, "user@yandex.ru", "pass")
    transport._imap = MisbehavingSearchImap(list(range(100, 351)))
    transport._selected_folder = DEFAULT_MAIL_FOLDER
    transport._uidvalidity = 1
    result = transport.search_uids_incremental(DEFAULT_MAIL_FOLDER, after_uid=100, max_results=100)
    assert result == list(range(101, 201))


def test_fake_imap_append_and_ensure_mailbox() -> None:
    from app.connectors.yandex.imap_mailboxes import ImapMailbox

    imap = FakeImapTransport(
        folder="INBOX",
        messages={},
        mailboxes=[
            ImapMailbox(flags=frozenset({"HASNOCHILDREN"}), name="INBOX"),
            ImapMailbox(flags=frozenset({"HASNOCHILDREN", "SENT"}), name="Sent"),
        ],
        folder_messages={"INBOX": {}, "Sent": {}},
    )
    imap.ensure_mailbox("Secretary-Uncertain")
    imap.ensure_mailbox("Secretary-Uncertain")
    assert imap.create_calls == ["Secretary-Uncertain"]
    raw = b"From: a@b.c\r\nSubject: x\r\n\r\nbody"
    imap.append_message("Sent", raw, flags=["\\Seen"])
    assert imap.append_calls == [{"folder": "Sent", "message_bytes": raw, "flags": ["\\Seen"]}]
    uids, incomplete = imap.search_uids_header("Sent", "Subject", "x", 200)
    assert uids == [1]
    assert incomplete is False


class _AppendImap:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.appended: list[tuple[str, str, bytes]] = []

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" INBOX']

    def create(self, name):
        self.created.append(name)
        return "OK", [b""]

    def append(self, mailbox, flags, date_time, message):
        self.appended.append((mailbox, flags, message))
        return "OK", [b""]


def test_imaplib_transport_append_and_create() -> None:
    transport = ImaplibTransport("imap.yandex.ru", 993, "user@yandex.ru", "pass")
    stub = _AppendImap()
    transport._imap = stub
    transport.ensure_mailbox("Secretary-Uncertain")
    assert stub.created == ["Secretary-Uncertain"]
    transport.append_message("Sent", b"raw-bytes", flags=["\\Seen"])
    assert stub.appended == [("Sent", "(\\Seen)", b"raw-bytes")]
    assert transport._selected_folder is None


class _AbortAppendImap:
    def append(self, mailbox, flags, date_time, message):
        raise imaplib.IMAP4.abort("socket error: EOF")


def test_imaplib_append_abort_is_retryable() -> None:
    transport = ImaplibTransport("imap.yandex.ru", 993, "user@yandex.ru", "pass")
    transport._imap = _AbortAppendImap()
    with pytest.raises(YandexImapError) as caught:
        transport.append_message("Sent", b"raw-bytes", flags=["\\Seen"])
    assert caught.value.retryable is True


def test_normalize_imap_message_matches_email_object_shape() -> None:
    raw = _build_raw_email()
    normalized = normalize_imap_message(raw, folder=DEFAULT_MAIL_FOLDER, uid=42, uidvalidity=7)
    assert normalized["kind"] == "email"
    assert normalized["provider"] == "yandex_mail"
    assert normalized["origin"] == "source"
    assert normalized["state"] == "observed"
    assert normalized["external_id"] == build_external_id(DEFAULT_MAIL_FOLDER, 7, 42)
    assert normalized["body"] == "Hello from Yandex"
    assert normalized["metadata"]["imap_uid"] == 42
    assert normalized["metadata"]["imap_uidvalidity"] == 7


def test_normalize_decodes_rfc2047_unicode_headers() -> None:
    msg = EmailMessage(policy=policy.default)
    msg["Subject"] = "Привет мир"
    msg["From"] = "Иван <ivan@example.com>"
    msg["To"] = "user@yandex.ru"
    msg["Message-ID"] = "<cyrillic@yandex.test>"
    msg["Date"] = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg.set_content("Текст")
    normalized = normalize_imap_message(
        msg.as_bytes(),
        folder=DEFAULT_MAIL_FOLDER,
        uid=1,
        uidvalidity=1,
    )
    assert normalized["title"] == "Привет мир"
    assert "Иван" in normalized["metadata"]["sender"]
    assert "ivan@example.com" in normalized["metadata"]["sender"]
    assert "=?utf-8?" not in normalized["title"]


def test_normalize_ignores_attachment_parts_for_body() -> None:
    msg = EmailMessage(policy=policy.default)
    msg["Subject"] = "With attachment"
    msg["From"] = "sender@yandex.ru"
    msg["To"] = "user@yandex.ru"
    msg["Message-ID"] = "<attach@yandex.test>"
    msg.set_content("Main body text")
    msg.add_attachment(
        b"attachment bytes",
        maintype="text",
        subtype="plain",
        filename="notes.txt",
    )
    normalized = normalize_imap_message(
        msg.as_bytes(),
        folder=DEFAULT_MAIL_FOLDER,
        uid=2,
        uidvalidity=1,
    )
    assert normalized["body"] == "Main body text"
    assert "attachment bytes" not in (normalized["body"] or "")


def test_bounded_yandex_sync_creates_observed_email_objects(
    db_session, credential_key: str
) -> None:
    store = YandexMailAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="user@yandex.ru",
        app_password="app-password",
        imap_host="imap.yandex.ru",
        imap_port=993,
    )
    db_session.commit()

    transport = FakeImapTransport(
        uidvalidity=10,
        messages={
            1: _build_raw_email(subject="First", body="Body one"),
            2: _build_raw_email(subject="Second", body="Body two"),
        },
    )

    sync_service = build_yandex_mail_sync_service(
        session=db_session,
        credential_key=credential_key,
        sync_days=30,
        default_limit=50,
        max_limit=100,
        transport_factory=lambda snapshot: transport,
    )
    result = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=10)

    assert result["created"] == 2
    assert result["jobs_enqueued"] == 2

    objects = list(
        db_session.scalars(
            select(Object).where(
                Object.provider == "yandex_mail",
                Object.kind == "email",
                Object.user_id == BOOTSTRAP_USER_ID,
                Object.title.in_(["First", "Second"]),
            )
        ).all()
    )
    assert len(objects) == 2
    for obj in objects:
        assert obj.user_id == BOOTSTRAP_USER_ID
        assert obj.origin == "source"
        assert obj.state == "observed"
        assert obj.metadata_["source_account_email"] == "user@yandex.ru"


def test_incremental_sync_skips_imap_search_for_already_checkpointed_uids(
    db_session, credential_key: str
) -> None:
    store = YandexMailAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="owner@yandex.ru",
        app_password="app-password",
        imap_host="imap.yandex.ru",
        imap_port=993,
    )
    db_session.commit()

    transport = FakeImapTransport(
        uidvalidity=5,
        messages={100: _build_raw_email(subject="Known", body="Stable body")},
    )
    sync_service = build_yandex_mail_sync_service(
        session=db_session,
        credential_key=credential_key,
        sync_days=30,
        default_limit=50,
        max_limit=100,
        transport_factory=lambda snapshot: transport,
    )
    first = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)
    second = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)

    assert first["created"] == 1
    assert first["jobs_enqueued"] == 1
    assert transport.fetch_calls == [100]
    assert second["created"] == 0
    assert second["unchanged"] == 0
    assert second["jobs_enqueued"] == 0
    assert transport.fetch_calls == [100]

    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert account is not None
    assert account.sync_state["inbox_last_uid"] == 100


def test_incremental_sync_processes_oldest_uid_batch_first(
    db_session, credential_key: str
) -> None:
    store = YandexMailAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="batch@yandex.ru",
        app_password="app-password",
        imap_host="imap.yandex.ru",
        imap_port=993,
    )
    store.update_sync_state(
        account,
        {"inbox_uidvalidity": 5, "inbox_last_uid": 100},
    )
    db_session.commit()

    messages = {
        uid: _build_raw_email(subject=f"Msg {uid}", message_id=f"<m{uid}@yandex.test>")
        for uid in range(101, 351)
    }
    transport = FakeImapTransport(uidvalidity=5, messages=messages)
    sync_service = build_yandex_mail_sync_service(
        session=db_session,
        credential_key=credential_key,
        sync_days=30,
        default_limit=100,
        max_limit=100,
        transport_factory=lambda snapshot: transport,
    )

    first = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert first["created"] == 100
    assert account.sync_state["inbox_last_uid"] == 200
    assert transport.fetch_calls == list(range(101, 201))

    second = sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=100)
    account = store.get_by_id_for_user(account.id, BOOTSTRAP_USER_ID)
    assert second["created"] == 100
    assert account.sync_state["inbox_last_uid"] == 300
    assert transport.fetch_calls == list(range(101, 301))


def test_no_db_transaction_during_imap_network(
    db_session, credential_key: str
) -> None:
    store = YandexMailAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="tx@yandex.ru",
        app_password="app-password",
        imap_host="imap.yandex.ru",
        imap_port=993,
    )
    db_session.commit()

    transport = FakeImapTransport(
        uidvalidity=3,
        messages={10: _build_raw_email(subject="Tx test")},
        tx_checker=lambda: db_session.in_transaction(),
    )
    sync_service = build_yandex_mail_sync_service(
        session=db_session,
        credential_key=credential_key,
        sync_days=30,
        default_limit=50,
        max_limit=100,
        transport_factory=lambda snapshot: transport,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=5)


def test_user_b_cannot_sync_user_a_yandex_account(db_session, credential_key: str) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()

    store = YandexMailAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="owner@yandex.ru",
        app_password="app-password",
        imap_host="imap.yandex.ru",
        imap_port=993,
    )
    db_session.commit()

    sync_service = build_yandex_mail_sync_service(
        session=db_session,
        credential_key=credential_key,
        sync_days=30,
        default_limit=50,
        max_limit=100,
        transport_factory=lambda snapshot: FakeImapTransport(messages={1: _build_raw_email()}),
    )
    with pytest.raises(YandexConnectorError, match="yandex mail account not found"):
        sync_service.sync_account(account.id, user_b_id, limit=1)


def test_two_users_can_store_same_yandex_external_id(
    db_session, credential_key: str
) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()

    for user_id in (BOOTSTRAP_USER_ID, user_b_id):
        store = YandexMailAccountStore(db_session, CredentialEncryption(credential_key))
        account = store.upsert_account(
            user_id=user_id,
            email=f"{user_id}@yandex.ru",
            app_password="app-password",
            imap_host="imap.yandex.ru",
            imap_port=993,
        )
        db_session.flush()
        transport = FakeImapTransport(
            uidvalidity=3,
            messages={50: _build_raw_email(subject=f"For {user_id}")},
        )
        sync_service = build_yandex_mail_sync_service(
            session=db_session,
            credential_key=credential_key,
            sync_days=30,
            default_limit=50,
            max_limit=100,
            transport_factory=lambda snapshot, _transport=transport: _transport,
        )
        sync_service.sync_account(account.id, user_id, limit=1)

    external_id = build_external_id(DEFAULT_MAIL_FOLDER, 3, 50)
    objs = list(
        db_session.scalars(
            select(Object).where(
                Object.provider == "yandex_mail",
                Object.external_id == external_id,
            )
        ).all()
    )
    assert len(objs) == 2
    assert {obj.user_id for obj in objs} == {BOOTSTRAP_USER_ID, user_b_id}


def test_yandex_connect_api_does_not_return_app_password(
    client, db_session, credential_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    response = client.post(
        "/connectors/yandex/mail/connect",
        json={
            "email": "api@yandex.ru",
            "app_password": "secret-app-password",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "api@yandex.ru"
    assert "app_password" not in body
    assert "secret-app-password" not in response.text

    account = db_session.scalar(
        select(YandexMailAccount).where(YandexMailAccount.email == "api@yandex.ru")
    )
    assert account is not None
    assert account.user_id == BOOTSTRAP_USER_ID
