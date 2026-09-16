"""PHASE 28C-B2-C1-B — Yandex Mail bounded history runtime."""

import uuid
from datetime import UTC, date, datetime, timedelta
from email import policy
from email.message import EmailMessage
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.deps import get_db
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.yandex.constants import DEFAULT_MAIL_FOLDER
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.connectors.yandex.imap_transport import FakeImapTransport, ImaplibTransport
from app.connectors.yandex.mail_history_state import (
    INITIAL_HISTORY_BEFORE_UID,
    MAX_IMAP_UID,
    format_stored_date,
    get_history_backfill,
)
from app.connectors.yandex.mail_normalize import build_external_id
from app.connectors.yandex.mail_sync import _imap_date, build_yandex_mail_sync_service
from app.core.config import settings
from app.db.engine import engine
from app.db.models import GoogleAccount, Job, Object, User, UserSourcePreference, YandexMailAccount
from app.jobs.constants import JOB_TYPE_SYNC_YANDEX_MAIL
from app.jobs.handlers import HANDLERS
from app.jobs.worker import process_one_job
from app.main import app
from app.services.source_sync_preference_service import SourceSyncPreferenceService
from app.services.source_sync_scheduler import SourceSyncScheduler
from app.source_sync.constants import SOURCE_YANDEX_MAIL
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_yandex_mail import _build_raw_email

FIXED_TODAY = date(2026, 9, 2)
FIXED_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


@pytest.fixture(autouse=True)
def cleanup_tables() -> None:
    conn = engine.connect()
    trans = conn.begin()
    session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    session.execute(delete(Job))
    session.execute(delete(Object))
    session.execute(delete(UserSourcePreference))
    session.execute(delete(YandexMailAccount))
    session.execute(delete(GoogleAccount))
    trans.commit()
    conn.close()
    yield


@pytest.fixture(autouse=True)
def fixed_mail_utcnow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.connectors.yandex.mail_sync.utcnow", lambda: FIXED_NOW)
    monkeypatch.setattr(
        "app.connectors.yandex.mail_history_state.utcnow",
        lambda: FIXED_NOW,
    )


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


def _upsert_account(
    db_session,
    credential_key: str,
    *,
    sync_state: dict | None = None,
    user_id: uuid.UUID = BOOTSTRAP_USER_ID,
) -> YandexMailAccount:
    store = YandexMailAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=user_id,
        email=f"user-{user_id}@yandex.ru",
        app_password="app-password",
        imap_host="imap.yandex.ru",
        imap_port=993,
    )
    if sync_state is not None:
        account.sync_state = sync_state
    db_session.flush()
    return account


def _build_raw_email_with_attachment(uid: int) -> bytes:
    msg = EmailMessage(policy=policy.default)
    msg["Subject"] = f"Attachment {uid}"
    msg["From"] = "sender@yandex.ru"
    msg["To"] = "user@yandex.ru"
    msg["Message-ID"] = f"<att-{uid}@yandex.test>"
    msg["Date"] = FIXED_NOW.strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg.set_content("body")
    msg.add_attachment(b"a,b\n1,2", maintype="text", subtype="plain", filename="data.csv")
    return msg.as_bytes()


def _messages_for_uids(uids: list[int]) -> dict[int, bytes]:
    return {
        uid: _build_raw_email(f"msg-{uid}", message_id=f"<msg-{uid}@yandex.test>")
        for uid in uids
    }


def _transport_with_history(
    credential_key: str,
    *,
    uidvalidity: int = 3,
    history_uids: list[int],
    live_messages: dict[int, bytes] | None = None,
) -> FakeImapTransport:
    history_set = set(history_uids)
    live = dict(live_messages or {})
    for uid in history_set:
        if uid not in live:
            live[uid] = _build_raw_email(f"hist-{uid}", message_id=f"<hist-{uid}@yandex.test>")
    return FakeImapTransport(
        uidvalidity=uidvalidity,
        messages=live,
        history_matching_uids=sorted(history_set),
    )


def _build_service(
    db_session,
    credential_key: str,
    transport: FakeImapTransport,
    sync_days: int = 30,
) -> object:
    return build_yandex_mail_sync_service(
        session=db_session,
        credential_key=credential_key,
        sync_days=sync_days,
        default_limit=settings.yandex_mail_sync_default_limit,
        max_limit=settings.yandex_mail_sync_max_limit,
        transport_factory=lambda snapshot: transport,
    )


def test_effective_history_user_a_seven_user_b_default(
    db_session,
    credential_key: str,
) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()
    account_a = _upsert_account(db_session, credential_key)
    account_b = _upsert_account(db_session, credential_key, user_id=user_b_id)
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_YANDEX_MAIL,
        history_days=7,
        history_days_specified=True,
    )
    transport_a = FakeImapTransport(messages={})
    service_a = _build_service(db_session, credential_key, transport_a, sync_days=7)
    service_a.sync_account(account_a.id, BOOTSTRAP_USER_ID)
    since_a = transport_a.initial_search_calls[0]["since_date"]
    assert since_a >= FIXED_NOW - timedelta(days=7, hours=1)

    transport_b = FakeImapTransport(messages={})
    service_b = _build_service(
        db_session,
        credential_key,
        transport_b,
        sync_days=settings.yandex_mail_sync_days,
    )
    service_b.sync_account(account_b.id, user_b_id)
    since_b = transport_b.initial_search_calls[0]["since_date"]
    expected = FIXED_NOW - timedelta(days=settings.yandex_mail_sync_days)
    assert since_b >= expected - timedelta(hours=1)


def test_direct_endpoint_live_only_no_history_search(
    db_session,
    credential_key: str,
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    account = _upsert_account(db_session, credential_key)
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_YANDEX_MAIL,
        history_days=7,
        history_days_specified=True,
    )
    transport = FakeImapTransport(messages={})

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(
        "app.api.yandex.build_yandex_mail_sync_service",
        lambda **kwargs: _build_service(db_session, credential_key, transport, sync_days=7),
    )
    with TestClient(app) as client:
        response = client.post(
            f"/connectors/yandex/mail/sync?account_id={account.id}",
            headers=auth_headers,
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert transport.history_search_calls == []


def test_worker_live_search_before_history_search(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(db_session, credential_key)
    transport = FakeImapTransport(
        messages={100: _build_raw_email("live")},
        history_matching_uids=[],
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert len(transport.initial_search_calls) >= 1
    assert len(transport.history_search_calls) == 1


def test_one_history_page_per_run(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(db_session, credential_key)
    transport = FakeImapTransport(messages={}, history_matching_uids=[])
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert len(transport.history_search_calls) == 1


def test_zero_last_uid_uses_initial_not_incremental(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={"inbox_uidvalidity": 10, "inbox_last_uid": 0},
    )
    transport = FakeImapTransport(uidvalidity=10, messages={})
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID)
    assert len(transport.initial_search_calls) == 1
    assert transport.incremental_search_calls == []


def test_live_checkpoint_update_preserves_history_backfill(
    db_session,
    credential_key: str,
) -> None:
    history_state = {
        "history_backfill": {
            "version": 1,
            "scanned_start_date": format_stored_date(FIXED_TODAY - timedelta(days=7)),
            "scanned_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
        },
        "custom_marker": True,
    }
    account = _upsert_account(db_session, credential_key, sync_state=history_state)
    transport = FakeImapTransport(messages={1: _build_raw_email()})
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID)
    stored = db_session.get(YandexMailAccount, account.id)
    assert stored.sync_state["custom_marker"] is True
    assert get_history_backfill(stored.sync_state)["scanned_start_date"] is not None


def test_history_update_preserves_forward_checkpoint(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={"inbox_uidvalidity": 5, "inbox_last_uid": 1000, "custom_marker": True},
    )
    transport = FakeImapTransport(
        uidvalidity=5,
        messages={},
        history_matching_uids=[],
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(YandexMailAccount, account.id)
    assert stored.sync_state["inbox_last_uid"] == 1000
    assert stored.sync_state["custom_marker"] is True


def test_initial_history_persisted_before_provider_search(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(db_session, credential_key)
    persisted = False

    class WatchingTransport(FakeImapTransport):
        def search_uids_history_page(self, folder, since_date, before_date, before_uid, max_results):
            stored = db_session.get(YandexMailAccount, account.id)
            backfill = get_history_backfill(stored.sync_state)
            nonlocal persisted
            persisted = (
                backfill.get("active_before_uid") == INITIAL_HISTORY_BEFORE_UID
                and backfill.get("inbox_uidvalidity") == 7
                and backfill.get("active_start_date") is not None
            )
            return super().search_uids_history_page(
                folder, since_date, before_date, before_uid, max_results
            )

    transport = WatchingTransport(
        uidvalidity=7,
        messages={},
        history_matching_uids=[],
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert persisted


def test_initial_history_search_uses_max_imap_uid_upper_bound() -> None:
    captured: list[str] = []

    class HistorySearchImap:
        def select(self, folder: str, readonly: bool = True) -> tuple[str, list[bytes]]:
            return "OK", [b"42"]

        def response(self, code: str) -> tuple[str, list[bytes]]:
            if code == "UIDVALIDITY":
                return "UIDVALIDITY", [b"7"]
            return "NO", [b""]

        def uid(self, command: str, *args: object) -> tuple[str, list[bytes]]:
            if command == "search":
                captured.append(str(args[-1]))
                return "OK", [b"10 20"]
            raise AssertionError(command)

    transport = ImaplibTransport("imap.yandex.ru", 993, "user@yandex.ru", "pass")
    transport._imap = HistorySearchImap()
    transport._selected_folder = DEFAULT_MAIL_FOLDER
    transport._uidvalidity = 7
    since = datetime(2026, 8, 1, tzinfo=UTC)
    before = datetime(2026, 9, 3, tzinfo=UTC)
    transport.search_uids_history_page(
        DEFAULT_MAIL_FOLDER,
        since,
        before,
        INITIAL_HISTORY_BEFORE_UID,
        50,
    )
    assert f"UID 1:{MAX_IMAP_UID}" in captured[0]


def test_non_final_page_persists_cursor_after_full_processing(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={
            "history_backfill": {
                "version": 1,
                "active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=30)),
                "active_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
                "active_history_days": 30,
                "active_before_uid": 251,
                "inbox_uidvalidity": 3,
            }
        },
    )
    transport = _transport_with_history(
        credential_key,
        uidvalidity=3,
        history_uids=list(range(1, 251)),
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(
        account.id,
        BOOTSTRAP_USER_ID,
        include_history_pass=True,
        limit=100,
    )
    stored = db_session.get(YandexMailAccount, account.id)
    backfill = get_history_backfill(stored.sync_state)
    assert backfill.get("active_before_uid") == 151


def test_final_page_completes_and_clears_active(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={
            "history_backfill": {
                "version": 1,
                "active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=10)),
                "active_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
                "active_history_days": 30,
                "active_before_uid": 51,
                "inbox_uidvalidity": 2,
            }
        },
    )
    transport = _transport_with_history(
        credential_key,
        uidvalidity=2,
        history_uids=list(range(1, 51)),
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(YandexMailAccount, account.id)
    backfill = get_history_backfill(stored.sync_state)
    assert backfill.get("active_before_uid") is None
    assert backfill.get("scanned_start_date") is not None


def test_crash_mid_page_keeps_cursor(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={
            "history_backfill": {
                "version": 1,
                "active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=30)),
                "active_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
                "active_history_days": 30,
                "active_before_uid": 251,
                "inbox_uidvalidity": 4,
            }
        },
    )
    messages = {
        200: _build_raw_email("m200", message_id="<m200@yandex.test>"),
        210: _build_raw_email("m210", message_id="<m210@yandex.test>"),
    }
    transport = FakeImapTransport(
        uidvalidity=4,
        messages=messages,
        history_matching_uids=list(range(151, 251)),
    )
    service = _build_service(db_session, credential_key, transport)
    original = service._materialize_uids

    def crash_wrapper(**kwargs):
        uids = kwargs["uids"]
        if len(uids) > 1:
            original(
                transport=kwargs["transport"],
                folder=kwargs["folder"],
                uidvalidity=kwargs["uidvalidity"],
                uids=uids[:1],
                owner_user_id=kwargs["owner_user_id"],
                initial_max_uid=kwargs["initial_max_uid"],
            )
            raise RuntimeError("simulated crash")
        return original(**kwargs)

    monkeypatch.setattr(service, "_materialize_uids", crash_wrapper)
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(YandexMailAccount, account.id)
    backfill = get_history_backfill(stored.sync_state)
    assert backfill.get("active_before_uid") == 251


def test_crash_retry_completes_page_without_duplicates(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_uids = list(range(202, 302))
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={
            "history_backfill": {
                "version": 1,
                "active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=30)),
                "active_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
                "active_history_days": 30,
                "active_before_uid": 302,
                "inbox_uidvalidity": 4,
            }
        },
    )
    transport = FakeImapTransport(
        uidvalidity=4,
        messages=_messages_for_uids(page_uids),
        history_matching_uids=list(range(201, 302)),
    )
    service = _build_service(db_session, credential_key, transport)
    crash_count = 0
    original = service._materialize_uids

    def crash_wrapper(**kwargs):
        nonlocal crash_count
        uids = kwargs["uids"]
        if crash_count == 0 and len(uids) > 1:
            crash_count += 1
            original(
                transport=kwargs["transport"],
                folder=kwargs["folder"],
                uidvalidity=kwargs["uidvalidity"],
                uids=uids[:1],
                owner_user_id=kwargs["owner_user_id"],
                initial_max_uid=kwargs["initial_max_uid"],
            )
            raise RuntimeError("simulated crash")
        return original(**kwargs)

    monkeypatch.setattr(service, "_materialize_uids", crash_wrapper)
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.sync_account(
            account.id,
            BOOTSTRAP_USER_ID,
            include_history_pass=True,
            limit=100,
        )
    fetch_after_crash = len(transport.fetch_calls)
    service.sync_account(
        account.id,
        BOOTSTRAP_USER_ID,
        include_history_pass=True,
        limit=100,
    )
    assert len(transport.fetch_calls) == fetch_after_crash + len(page_uids) - 1
    stored = db_session.get(YandexMailAccount, account.id)
    backfill = get_history_backfill(stored.sync_state)
    assert backfill.get("active_before_uid") == 202
    embed_jobs = list(db_session.scalars(select(Job).where(Job.type == "embed_object")))
    assert len(embed_jobs) == len(page_uids)


def test_historical_attachment_materialized_once_on_retry(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(db_session, credential_key)
    uid = 777
    transport = FakeImapTransport(
        uidvalidity=10,
        messages={uid: _build_raw_email_with_attachment(uid)},
        history_matching_uids=[uid],
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    email = db_session.scalar(
        select(Object).where(
            Object.external_id == build_external_id(DEFAULT_MAIL_FOLDER, 10, uid)
        )
    )
    assert email is not None
    att_external_id = f"yandex_mail:{email.external_id}:att:part-0"
    attachment = db_session.scalar(
        select(Object).where(Object.external_id == att_external_id)
    )
    assert attachment is not None
    transport.fetch_calls.clear()
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert transport.fetch_calls == []
    attachments = list(
        db_session.scalars(select(Object).where(Object.external_id == att_external_id))
    )
    assert len(attachments) == 1


def test_history_increase_schedules_older_interval(
    db_session,
    credential_key: str,
) -> None:
    scanned_start = FIXED_TODAY - timedelta(days=30)
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={
            "history_backfill": {
                "version": 1,
                "scanned_start_date": format_stored_date(scanned_start),
                "scanned_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
            }
        },
    )
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_YANDEX_MAIL,
        history_days=90,
        history_days_specified=True,
    )
    transport = FakeImapTransport(uidvalidity=11, messages={}, history_matching_uids=[])
    service = _build_service(db_session, credential_key, transport, sync_days=90)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert len(transport.history_search_calls) == 1
    call = transport.history_search_calls[0]
    assert call["since_date"] == _imap_date(FIXED_TODAY - timedelta(days=90))
    assert call["before_date"] == _imap_date(scanned_start)


def test_history_decrease_abandons_active_without_deleting_objects(
    db_session,
    credential_key: str,
) -> None:
    old_obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        provider="yandex_mail",
        external_id=build_external_id(DEFAULT_MAIL_FOLDER, 12, 50),
        origin="source",
        state="observed",
        title="old historical",
    )
    db_session.add(old_obj)
    db_session.flush()
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={
            "history_backfill": {
                "version": 1,
                "scanned_start_date": format_stored_date(FIXED_TODAY - timedelta(days=90)),
                "scanned_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
                "active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=90)),
                "active_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
                "active_history_days": 90,
                "active_before_uid": 1000,
                "inbox_uidvalidity": 12,
            }
        },
    )
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_YANDEX_MAIL,
        history_days=14,
        history_days_specified=True,
    )
    transport = FakeImapTransport(uidvalidity=12, messages={}, history_matching_uids=[])
    service = _build_service(db_session, credential_key, transport, sync_days=14)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(YandexMailAccount, account.id)
    backfill = get_history_backfill(stored.sync_state)
    assert backfill.get("active_before_uid") is None
    assert db_session.get(Object, old_obj.id) is not None
    assert transport.history_search_calls == []


def test_time_drift_preserves_active_frozen_cursor(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={
            "history_backfill": {
                "version": 1,
                "active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=30)),
                "active_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
                "active_history_days": 30,
                "active_before_uid": 500,
                "inbox_uidvalidity": 13,
            }
        },
    )
    later = FIXED_NOW + timedelta(days=1)
    monkeypatch.setattr("app.connectors.yandex.mail_sync.utcnow", lambda: later)
    transport = FakeImapTransport(
        uidvalidity=13,
        messages=_messages_for_uids(list(range(400, 500))),
        history_matching_uids=list(range(400, 500)),
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(
        account.id,
        BOOTSTRAP_USER_ID,
        include_history_pass=True,
        limit=100,
    )
    call = transport.history_search_calls[0]
    assert call["since_date"] == _imap_date(FIXED_TODAY - timedelta(days=30))
    assert call["before_date"] == _imap_date(FIXED_TODAY + timedelta(days=1))
    assert call["before_uid"] == 500


def test_uidvalidity_unchanged_continues_active_history(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={
            "history_backfill": {
                "version": 1,
                "active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=30)),
                "active_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
                "active_history_days": 30,
                "active_before_uid": 250,
                "inbox_uidvalidity": 14,
            }
        },
    )
    transport = FakeImapTransport(
        uidvalidity=14,
        messages=_messages_for_uids(list(range(150, 250))),
        history_matching_uids=list(range(150, 250)),
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(
        account.id,
        BOOTSTRAP_USER_ID,
        include_history_pass=True,
        limit=100,
    )
    assert transport.history_search_calls[0]["before_uid"] == 250
    stored = db_session.get(YandexMailAccount, account.id)
    backfill = get_history_backfill(stored.sync_state)
    assert backfill.get("active_before_uid") is None
    assert backfill.get("scanned_start_date") is not None


def test_empty_mailbox_zero_checkpoint_stays_safe_across_runs(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={"inbox_uidvalidity": 15, "inbox_last_uid": 0},
    )
    transport = FakeImapTransport(uidvalidity=15, messages={})
    service = _build_service(db_session, credential_key, transport)
    for _ in range(3):
        service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=False)
    assert transport.incremental_search_calls == []
    assert len(transport.initial_search_calls) == 3


def test_history_mail_created_once_with_embed(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(db_session, credential_key)
    transport = _transport_with_history(credential_key, uidvalidity=8, history_uids=[500])
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    obj = db_session.scalar(
        select(Object).where(
            Object.external_id == build_external_id(DEFAULT_MAIL_FOLDER, 8, 500)
        )
    )
    assert obj is not None
    embed_jobs = list(db_session.scalars(select(Job).where(Job.type == "embed_object")))
    assert len(embed_jobs) == 1


def test_known_historical_uid_skips_fetch(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(db_session, credential_key)
    existing = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        provider="yandex_mail",
        external_id=build_external_id(DEFAULT_MAIL_FOLDER, 9, 300),
        origin="source",
        state="observed",
        title="known",
    )
    db_session.add(existing)
    db_session.flush()
    transport = FakeImapTransport(
        uidvalidity=9,
        messages={},
        history_matching_uids=[300],
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert transport.fetch_calls == []


def test_history_does_not_change_forward_last_uid(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={"inbox_uidvalidity": 6, "inbox_last_uid": 1000},
    )
    transport = FakeImapTransport(
        uidvalidity=6,
        messages={},
        history_matching_uids=[],
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(YandexMailAccount, account.id)
    assert stored.sync_state["inbox_last_uid"] == 1000


def test_uidvalidity_change_clears_history_and_uses_initial_live(
    db_session,
    credential_key: str,
) -> None:
    account = _upsert_account(
        db_session,
        credential_key,
        sync_state={
            "inbox_uidvalidity": 5,
            "inbox_last_uid": 500,
            "history_backfill": {
                "version": 1,
                "active_start_date": format_stored_date(FIXED_TODAY - timedelta(days=30)),
                "active_end_date": format_stored_date(FIXED_TODAY + timedelta(days=1)),
                "active_history_days": 30,
                "active_before_uid": 999,
                "inbox_uidvalidity": 5,
            },
        },
    )
    transport = FakeImapTransport(
        uidvalidity=6,
        messages={},
        history_matching_uids=[],
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(YandexMailAccount, account.id)
    assert stored.sync_state["inbox_uidvalidity"] == 6
    assert len(transport.initial_search_calls) >= 1
    assert transport.incremental_search_calls == []
    backfill = get_history_backfill(stored.sync_state)
    assert backfill.get("active_before_uid") != 999
    assert transport.history_search_calls[0]["before_uid"] == INITIAL_HISTORY_BEFORE_UID


def test_disabled_yandex_mail_worker_skips_imap(
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_embedding_service,
) -> None:
    handler_calls = 0

    def fake_handler(session, embedding_service, payload, user_id) -> None:
        nonlocal handler_calls
        handler_calls += 1

    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    conn = engine.connect()
    trans = conn.begin()
    persist_session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    store = YandexMailAccountStore(persist_session, CredentialEncryption(credential_key))
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="user@yandex.ru",
        app_password="app-password",
        imap_host="imap.yandex.ru",
        imap_port=993,
    )
    SourceSyncScheduler(persist_session).run_maintenance()
    SourceSyncPreferenceService.build(persist_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_YANDEX_MAIL,
        enabled=False,
        enabled_specified=True,
    )
    trans.commit()
    conn.close()

    conn = engine.connect()
    trans = conn.begin()
    ready_session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    job = ready_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_YANDEX_MAIL,
            Job.payload["account_id"].as_string() == str(account.id),
        )
    )
    job.run_after = utcnow() - timedelta(seconds=1)
    trans.commit()
    conn.close()

    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_YANDEX_MAIL: fake_handler}):
        assert process_one_job(fake_embedding_service)

    assert handler_calls == 0
