import json
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import ObjectCreate
from app.connectors.mattermost.credentials import MattermostAccountStore
from app.connectors.mattermost.normalize import build_external_id
from app.connectors.mattermost.sync import build_mattermost_sync_service
from app.connectors.mattermost.transport import FakeMattermostTransport
from app.db.engine import engine
from app.db.models import Job, MattermostAccount, Object, User
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_TYPE_SYNC_MATTERMOST,
)
from app.jobs.handlers import HANDLERS
from app.jobs.worker import process_one_job
from app.main import app
from app.services.graph_service import GraphService
from app.services.job_queue_service import sanitize_job_error, utcnow
from app.services.open_target_service import OpenTargetService
from app.services.recent_source_service import RecentSourceService
from app.services.source_sync_scheduler import SourceSyncScheduler
from app.users.bootstrap import BOOTSTRAP_USER_ID

ALLOWED_URL = "https://mm.example.com"
ALLOWED_URL_B = "https://mm2.example.com"
PAT = "mattermost-personal-access-token"


@pytest.fixture(autouse=True)
def cleanup_mattermost_jobs() -> None:
    conn = engine.connect()
    trans = conn.begin()
    session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    session.execute(delete(Job).where(Job.type == JOB_TYPE_SYNC_MATTERMOST))
    session.execute(delete(MattermostAccount))
    trans.commit()
    conn.close()
    yield


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def mattermost_settings(monkeypatch: pytest.MonkeyPatch, credential_key: str) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    monkeypatch.setattr(
        "app.core.config.settings.mattermost_allowed_base_urls",
        ALLOWED_URL,
    )
    monkeypatch.setattr(
        "app.core.config.settings.source_sync_mattermost_interval_seconds",
        120,
    )


def _mattermost_account(
    db_session,
    credential_key: str,
    user_id: uuid.UUID = BOOTSTRAP_USER_ID,
) -> MattermostAccount:
    store = MattermostAccountStore(
        db_session,
        MattermostAccountStore.build_encryption(credential_key),
    )
    account = store.upsert_account(
        user_id=user_id,
        normalized_server_url=ALLOWED_URL,
        remote_user_id="user-1",
        username="alice",
        access_token=PAT,
        display_name="Alice",
        email="alice@example.com",
    )
    db_session.commit()
    return account


def _persist_mattermost_schedule(
    credential_key: str,
    user_id: uuid.UUID = BOOTSTRAP_USER_ID,
) -> MattermostAccount:
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    store = MattermostAccountStore(
        session,
        MattermostAccountStore.build_encryption(credential_key),
    )
    account = store.upsert_account(
        user_id=user_id,
        normalized_server_url=ALLOWED_URL,
        remote_user_id="user-1",
        username="alice",
        access_token=PAT,
        display_name="Alice",
        email="alice@example.com",
    )
    SourceSyncScheduler(session).run_maintenance()
    trans.commit()
    conn.close()
    return account


def test_mattermost_scheduler_ensures_single_recurring_row(
    db_session,
    credential_key: str,
    mattermost_settings,
) -> None:
    account = _mattermost_account(db_session, credential_key)
    scheduler = SourceSyncScheduler(db_session)
    scheduler.run_maintenance()
    scheduler.run_maintenance()
    db_session.commit()
    jobs = list(
        db_session.scalars(
            select(Job).where(
                Job.type == JOB_TYPE_SYNC_MATTERMOST,
                Job.user_id == BOOTSTRAP_USER_ID,
            )
        )
    )
    assert len(jobs) == 1
    assert jobs[0].payload == {"account_id": str(account.id)}


def test_mattermost_recurring_success_reschedules_same_row(
    credential_key: str,
    mattermost_settings,
    fake_embedding_service,
) -> None:
    account = _persist_mattermost_schedule(credential_key)
    conn = engine.connect()
    session = Session(bind=conn)
    job = session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_MATTERMOST,
            Job.payload["account_id"].as_string() == str(account.id),
        )
    )
    job_id = job.id
    conn.close()

    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_MATTERMOST: lambda s, e, p, u: None}):
        assert process_one_job(fake_embedding_service)

    conn = engine.connect()
    session = Session(bind=conn)
    job = session.get(Job, job_id)
    assert job.status == JOB_STATUS_PENDING
    assert job.attempts == 0
    assert job.last_error is None
    assert "last_success_at" in job.payload
    assert job.run_after > utcnow()
    assert job.run_after <= utcnow() + timedelta(seconds=125)
    conn.close()


def test_manual_sources_sync_triggers_mattermost_row_without_inline_network(
    db_session,
    credential_key: str,
    mattermost_settings,
    auth_headers,
) -> None:
    from tests.conftest import AuthTestClient

    account = _mattermost_account(db_session, credential_key)
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()

    sync_called = False

    def _fail_if_called(*args, **kwargs):
        nonlocal sync_called
        sync_called = True

    app.dependency_overrides[get_db] = lambda: (yield db_session)
    with (
        patch.dict(HANDLERS, {JOB_TYPE_SYNC_MATTERMOST: _fail_if_called}),
        TestClient(app) as raw,
    ):
        client = AuthTestClient(raw, auth_headers)
        response = client.post("/sources/sync")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert any("mattermost:" in item for item in response.json()["triggered"])
    assert sync_called is False
    job = db_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_MATTERMOST,
            Job.payload["account_id"].as_string() == str(account.id),
        )
    )
    assert job.run_after <= utcnow() + timedelta(seconds=1)


def test_cross_user_cannot_trigger_mattermost_jobs(
    db_session,
    credential_key: str,
    issue_bearer,
    mattermost_settings,
) -> None:
    other_user_id = uuid.uuid4()
    db_session.add(User(id=other_user_id, display_name="Other"))
    bootstrap_account = _mattermost_account(db_session, credential_key, user_id=BOOTSTRAP_USER_ID)
    other_account = _mattermost_account(db_session, credential_key, user_id=other_user_id)
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()

    bootstrap_job = db_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_MATTERMOST,
            Job.payload["account_id"].as_string() == str(bootstrap_account.id),
        )
    )
    bootstrap_run_after = bootstrap_job.run_after

    from tests.conftest import AuthTestClient

    other_bearer = issue_bearer(other_user_id)
    other_headers = {"Authorization": f"Bearer {other_bearer}"}

    app.dependency_overrides[get_db] = lambda: (yield db_session)
    with TestClient(app) as raw:
        client = AuthTestClient(raw, other_headers)
        triggered = client.post("/sources/sync").json()["triggered"]
    app.dependency_overrides.clear()

    assert any(f"mattermost:{other_account.id}" in item for item in triggered)
    assert not any(f"mattermost:{bootstrap_account.id}" in item for item in triggered)
    db_session.expire_all()
    bootstrap_job = db_session.get(Job, bootstrap_job.id)
    assert bootstrap_job.run_after == bootstrap_run_after


def test_stale_mattermost_job_retired_when_account_disappears(
    db_session,
    credential_key: str,
    mattermost_settings,
) -> None:
    account = _mattermost_account(db_session, credential_key)
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()
    db_session.execute(delete(MattermostAccount).where(MattermostAccount.id == account.id))
    db_session.commit()
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()
    job = db_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_MATTERMOST,
            Job.payload["account_id"].as_string() == str(account.id),
        )
    )
    assert job is not None
    assert job.status == JOB_STATUS_DONE


def test_failed_mattermost_job_rearms_via_scheduler(
    credential_key: str,
    mattermost_settings,
    fake_embedding_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.source_sync_failed_rearm_seconds", 60)
    account = _persist_mattermost_schedule(credential_key)
    conn = engine.connect()
    session = Session(bind=conn)
    job = session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_MATTERMOST,
            Job.payload["account_id"].as_string() == str(account.id),
        )
    )
    job_id = job.id
    conn.close()

    def failing_handler(session, embedding, payload, user_id):
        raise RuntimeError("mattermost sync failed")

    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_MATTERMOST: failing_handler}):
        assert process_one_job(fake_embedding_service)

    conn = engine.connect()
    session = Session(bind=conn)
    job = session.get(Job, job_id)
    job.attempts = 3
    job.status = JOB_STATUS_FAILED
    job.run_after = utcnow() - timedelta(seconds=1)
    job.last_error = "RuntimeError"
    session.commit()

    scheduler = SourceSyncScheduler(session)
    scheduler.run_maintenance()
    session.commit()
    job = session.get(Job, job_id)
    assert job.status == JOB_STATUS_PENDING
    assert job.attempts == 0
    conn.close()


def test_sources_status_includes_mattermost_without_pat(
    db_session,
    credential_key: str,
    mattermost_settings,
    auth_headers,
) -> None:
    from tests.conftest import AuthTestClient

    _mattermost_account(db_session, credential_key)
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: (yield db_session)
    with TestClient(app) as raw:
        client = AuthTestClient(raw, auth_headers)
        response = client.get("/sources/status")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    providers = {row["provider"] for row in body["sources"]}
    assert "mattermost" in providers
    assert PAT not in json.dumps(body)
    assert "access_token_encrypted" not in json.dumps(body)


def test_connections_exposes_mattermost_accounts_without_secrets(
    db_session,
    credential_key: str,
    mattermost_settings,
    auth_headers,
) -> None:
    from tests.conftest import AuthTestClient

    account = _mattermost_account(db_session, credential_key)

    app.dependency_overrides[get_db] = lambda: (yield db_session)
    with TestClient(app) as raw:
        client = AuthTestClient(raw, auth_headers)
        response = client.get("/connections")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body["mattermost"]) == 1
    row = body["mattermost"][0]
    assert row["account_id"] == str(account.id)
    assert row["server_url"] == ALLOWED_URL
    assert row["username"] == "alice"
    assert PAT not in json.dumps(body)
    assert "access_token_encrypted" not in json.dumps(body)


def test_sanitize_job_error_strips_authorization_and_bearer() -> None:
    assert sanitize_job_error(RuntimeError("Authorization: Bearer secret-token")) == "RuntimeError"
    assert sanitize_job_error(RuntimeError("access_token=leaked")) == "RuntimeError"
    assert sanitize_job_error(RuntimeError("personal-access-token leaked")) == "RuntimeError"


def test_open_target_mattermost_team_post_deep_link(
    db_session,
    credential_key: str,
    mattermost_settings,
) -> None:
    account = _mattermost_account(db_session, credential_key)
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="mattermost",
        external_id=f"{ALLOWED_URL}|post-1",
        origin="source",
        state="observed",
        title="Bob: hello",
        body="hello",
        metadata_={
            "account_id": str(account.id),
            "post_id": "post-1",
            "team_name": "team-alpha",
            "server_url": ALLOWED_URL,
        },
    )
    db_session.add(obj)
    db_session.commit()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is True
    assert target.label == "Открыть в Mattermost"
    assert target.url == f"{ALLOWED_URL}/team-alpha/pl/post-1"


def test_open_target_mattermost_dm_fallback_to_server_base(
    db_session,
    credential_key: str,
    mattermost_settings,
) -> None:
    account = _mattermost_account(db_session, credential_key)
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="mattermost",
        external_id=f"{ALLOWED_URL}|dm-post",
        origin="source",
        state="observed",
        title="DM",
        body="private",
        metadata_={
            "account_id": str(account.id),
            "post_id": "dm-post",
            "channel_type": "D",
            "server_url": ALLOWED_URL,
        },
    )
    db_session.add(obj)
    db_session.commit()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is True
    assert target.url == ALLOWED_URL
    assert target.reason == "mattermost_exact_post_link_unavailable"


def test_open_target_rejects_tampered_mattermost_account_id(
    db_session,
    credential_key: str,
    mattermost_settings,
) -> None:
    account = _mattermost_account(db_session, credential_key)
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="mattermost",
        external_id=f"{ALLOWED_URL}|tampered",
        origin="source",
        state="observed",
        title="Tampered",
        body="x",
        metadata_={
            "account_id": str(uuid.uuid4()),
            "post_id": "tampered",
            "team_name": "team-alpha",
            "server_url": ALLOWED_URL,
        },
    )
    db_session.add(obj)
    db_session.commit()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is False
    assert target.reason == "mattermost_metadata_tampered"
    assert account.id != uuid.UUID(obj.metadata_["account_id"])


def test_open_target_rejects_metadata_server_url_mismatch(
    db_session,
    credential_key: str,
    mattermost_settings,
) -> None:
    account = _mattermost_account(db_session, credential_key)
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="mattermost",
        external_id=build_external_id(ALLOWED_URL, "post-1"),
        origin="source",
        state="observed",
        title="Mismatch",
        body="x",
        metadata_={
            "account_id": str(account.id),
            "post_id": "post-1",
            "team_name": "team-alpha",
            "server_url": ALLOWED_URL_B,
        },
    )
    db_session.add(obj)
    db_session.commit()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is False
    assert target.reason == "mattermost_metadata_tampered"


def test_open_target_rejects_same_user_cross_account_metadata_substitution(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    monkeypatch.setattr(
        "app.core.config.settings.mattermost_allowed_base_urls",
        f"{ALLOWED_URL},{ALLOWED_URL_B}",
    )
    store = MattermostAccountStore(
        db_session,
        MattermostAccountStore.build_encryption(credential_key),
    )
    account_a = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        normalized_server_url=ALLOWED_URL,
        remote_user_id="user-a",
        username="alice",
        access_token=PAT,
    )
    account_b = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        normalized_server_url=ALLOWED_URL_B,
        remote_user_id="user-b",
        username="bob",
        access_token=PAT,
    )
    db_session.commit()

    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="mattermost",
        external_id=build_external_id(ALLOWED_URL, "cross-post"),
        origin="source",
        state="observed",
        title="Cross account",
        body="x",
        metadata_={
            "account_id": str(account_b.id),
            "post_id": "cross-post",
            "team_name": "team-alpha",
            "server_url": ALLOWED_URL_B,
        },
    )
    db_session.add(obj)
    db_session.commit()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is False
    assert target.reason == "mattermost_metadata_tampered"
    assert account_a.server_url != account_b.server_url


def test_open_target_rejects_external_id_server_prefix_mismatch(
    db_session,
    credential_key: str,
    mattermost_settings,
) -> None:
    account = _mattermost_account(db_session, credential_key)
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="mattermost",
        external_id=build_external_id(ALLOWED_URL_B, "post-1"),
        origin="source",
        state="observed",
        title="Wrong server prefix",
        body="x",
        metadata_={
            "account_id": str(account.id),
            "post_id": "post-1",
            "team_name": "team-alpha",
            "server_url": ALLOWED_URL,
        },
    )
    db_session.add(obj)
    db_session.commit()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is False
    assert target.reason == "mattermost_metadata_tampered"


def test_open_target_rejects_external_id_post_id_mismatch(
    db_session,
    credential_key: str,
    mattermost_settings,
) -> None:
    account = _mattermost_account(db_session, credential_key)
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="mattermost",
        external_id=build_external_id(ALLOWED_URL, "other-post"),
        origin="source",
        state="observed",
        title="Wrong post id",
        body="x",
        metadata_={
            "account_id": str(account.id),
            "post_id": "post-1",
            "team_name": "team-alpha",
            "server_url": ALLOWED_URL,
        },
    )
    db_session.add(obj)
    db_session.commit()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is False
    assert target.reason == "mattermost_metadata_tampered"


def test_open_target_ignores_malicious_canonical_uri_with_valid_provenance(
    db_session,
    credential_key: str,
    mattermost_settings,
) -> None:
    account = _mattermost_account(db_session, credential_key)
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="chat_message",
        provider="mattermost",
        external_id=build_external_id(ALLOWED_URL, "post-safe"),
        canonical_uri="https://evil.example/phish",
        origin="source",
        state="observed",
        title="Canonical ignored",
        body="x",
        metadata_={
            "account_id": str(account.id),
            "post_id": "post-safe",
            "team_name": "team-alpha",
            "server_url": ALLOWED_URL,
        },
    )
    db_session.add(obj)
    db_session.commit()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is True
    assert target.url == f"{ALLOWED_URL}/team-alpha/pl/post-safe"
    assert "evil.example" not in (target.url or "")


def test_mattermost_chat_message_visible_in_recent_source_feed(
    db_session,
    credential_key: str,
    mattermost_settings,
) -> None:
    GraphService(db_session, BOOTSTRAP_USER_ID).create_object(
        ObjectCreate(
            kind="chat_message",
            title="Mattermost recent feed",
            origin="source",
            state="observed",
            provider="mattermost",
            external_id=f"{ALLOWED_URL}|recent-1",
            occurred_at=utcnow(),
        )
    )
    rows = RecentSourceService(db_session, BOOTSTRAP_USER_ID).list_recent()
    assert any(row.title == "Mattermost recent feed" for row in rows)


def test_mattermost_worker_handler_calls_sync_with_account_id_only_payload(
    db_session,
    credential_key: str,
    mattermost_settings,
) -> None:
    account = _mattermost_account(db_session, credential_key)
    now = utcnow()
    transport = FakeMattermostTransport(
        channels=[
            {
                "id": "ch-1",
                "name": "general",
                "display_name": "General",
                "type": "O",
                "team_id": "team-1",
                "last_post_at": int(now.timestamp() * 1000),
            }
        ],
        teams=[{"id": "team-1", "name": "team", "display_name": "Team"}],
        users_by_id={
            "author-1": {"id": "author-1", "username": "bob", "display_name": "Bob"},
        },
        posts_by_channel={
            "ch-1": [
                {
                    "id": "p1",
                    "channel_id": "ch-1",
                    "user_id": "author-1",
                    "message": "synced via worker",
                    "create_at": int((now - timedelta(hours=1)).timestamp() * 1000),
                    "update_at": int((now - timedelta(hours=1)).timestamp() * 1000),
                    "type": "",
                    "root_id": "",
                    "file_ids": [],
                }
            ],
        },
    )
    SourceSyncScheduler(db_session).run_maintenance()
    db_session.commit()
    job = db_session.scalar(select(Job).where(Job.type == JOB_TYPE_SYNC_MATTERMOST))
    assert set(job.payload.keys()) == {"account_id"}

    service = build_mattermost_sync_service(
        session=db_session,
        credential_key=credential_key,
        sync_days=14,
        max_channels=50,
        initial_posts_per_channel=100,
        max_posts_per_run=500,
        overlap_seconds=300,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: now,
    )

    with patch(
        "app.jobs.source_sync_handlers._mattermost_sync_service",
        return_value=service,
    ):
        from app.jobs.source_sync_handlers import handle_sync_mattermost

        handle_sync_mattermost(
            db_session,
            None,
            {"account_id": str(account.id)},
            BOOTSTRAP_USER_ID,
        )
    db_session.commit()
    obj = db_session.scalar(select(Object).where(Object.provider == "mattermost"))
    assert obj is not None
    assert obj.body == "synced via worker"
