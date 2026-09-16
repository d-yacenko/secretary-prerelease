"""PHASE 29A stale extraction version boundaries: routine sync vs explicit re-intake."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.connectors.google.constants import (
    CALENDAR_READONLY_SCOPE,
    DRIVE_READONLY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GOOGLE_DRIVE_PROVIDER,
)
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.yandex.calendar_credentials import YandexCalendarAccountStore
from app.connectors.yandex.constants import YANDEX_DISK_PROVIDER
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.content_extraction.constants import EXTRACTION_VERSION
from app.db.models import Job, Object, Representation
from app.jobs.constants import (
    JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
    RECURRING_SOURCE_JOB_TYPES,
)
from app.services.explicit_link_intake_service import (
    build_google_explicit_link_intake_service,
    build_yandex_explicit_link_intake_service,
)
from app.services.source_sync_scheduler import SourceSyncScheduler
from app.source_sync.constants import SUPPORTED_SOURCE_KEYS
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_phase_27c_explicit_intake_yandex import FakeYandexDiskTransport, _yandex_resource
from tests.test_phase_29a_bounded_content_extraction import FakeDriveTransport


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def oauth_client_file(tmp_path: Path) -> str:
    path = tmp_path / "google-oauth-client.json"
    path.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "test-client-id",
                    "client_secret": "test-client-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def google_settings(monkeypatch: pytest.MonkeyPatch, oauth_client_file: str, credential_key: str) -> None:
    monkeypatch.setattr("app.core.config.settings.google_oauth_client_file", oauth_client_file)
    monkeypatch.setattr(
        "app.core.config.settings.google_redirect_uri",
        "http://localhost:18080/auth/google/callback",
    )
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)


def _extract_jobs_for_object(db_session, object_id) -> list[Job]:
    return [
        job
        for job in db_session.scalars(
            select(Job).where(Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT)
        ).all()
        if (job.payload or {}).get("object_id") == str(object_id)
    ]


def _seed_google_drive_object(db_session, *, file_id: str, md5: str) -> Object:
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        provider=GOOGLE_DRIVE_PROVIDER,
        external_id=file_id,
        origin="explicit",
        state="observed",
        title="notes.txt",
        metadata_={
            "content_revision": f"gdrive:md5:{md5}",
            "content_extraction_status": "ready",
            "content_extraction_version": "phase29a-v2",
            "mime_type": "text/plain",
            "file_id": file_id,
            "md5_checksum": md5,
            "modified_time": "2024-01-01T00:00:00.000Z",
        },
    )
    db_session.add(obj)
    db_session.flush()
    db_session.add(
        Representation(object_id=obj.id, kind="full", text="historical drive content", metadata_={})
    )
    db_session.flush()
    return obj


def _seed_yandex_disk_object(
    db_session,
    *,
    resource_id: str,
    share_url: str,
    md5: str,
) -> Object:
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        provider=YANDEX_DISK_PROVIDER,
        external_id=resource_id,
        origin="explicit",
        state="observed",
        title="notes.txt",
        metadata_={
            "content_revision": f"yandex:md5:{md5}",
            "content_extraction_status": "ready",
            "content_extraction_version": "phase29a-v2",
            "resource_id": resource_id,
            "resource_type": "file",
            "mime_type": "text/plain",
            "md5": md5,
            "modified_time": "2024-02-01T12:00:00.000Z",
            "revision": "1",
            "size": 4096,
            "intake_url": share_url,
            "public_url": share_url,
        },
    )
    db_session.add(obj)
    db_session.flush()
    db_session.add(
        Representation(object_id=obj.id, kind="full", text="historical yandex content", metadata_={})
    )
    db_session.flush()
    return obj


def _bootstrap_routine_sync_accounts(db_session, credential_key: str) -> None:
    encryption = CredentialEncryption(credential_key)
    google_store = GoogleAccountStore(db_session, encryption)
    google_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="routine-sync@example.com",
        scopes=[GMAIL_READONLY_SCOPE, CALENDAR_READONLY_SCOPE, DRIVE_READONLY_SCOPE],
        access_token="unittest-google-access",
        refresh_token="unittest-google-refresh",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )
    yandex_mail_store = YandexMailAccountStore(db_session, encryption)
    yandex_mail_store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="routine-sync@yandex.example",
        app_password="app-password",
        imap_host="imap.yandex.ru",
        imap_port=993,
    )
    yandex_calendar_store = YandexCalendarAccountStore(db_session, encryption)
    yandex_calendar_store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="routine-sync@yandex.example",
        app_password="app-password",
        caldav_host="caldav.yandex.ru",
    )
    db_session.flush()


def test_routine_source_sync_registry_excludes_drive_and_disk() -> None:
    assert "google_drive" not in SUPPORTED_SOURCE_KEYS
    assert "yandex_disk" not in SUPPORTED_SOURCE_KEYS
    assert all("drive" not in job_type for job_type in RECURRING_SOURCE_JOB_TYPES)


def test_google_drive_background_sync_does_not_enqueue_stale_version_extract(
    db_session, credential_key, google_settings
) -> None:
    obj = _seed_google_drive_object(
        db_session,
        file_id="routine-sync-drive",
        md5="routine-stable-md5",
    )
    _bootstrap_routine_sync_accounts(db_session, credential_key)

    scheduler = SourceSyncScheduler(db_session)
    scheduler.run_maintenance()
    scheduler.trigger_all_for_user(BOOTSTRAP_USER_ID)
    db_session.flush()

    assert _extract_jobs_for_object(db_session, obj.id) == []
    assert obj.metadata_["content_extraction_version"] == "phase29a-v2"


def test_yandex_disk_background_sync_does_not_enqueue_stale_version_extract(
    db_session, credential_key, google_settings
) -> None:
    share_url = "https://disk.yandex.ru/d/routine-sync-key"
    obj = _seed_yandex_disk_object(
        db_session,
        resource_id="routine-sync-yandex-file",
        share_url=share_url,
        md5="routine-stable-yandex-md5",
    )
    _bootstrap_routine_sync_accounts(db_session, credential_key)

    scheduler = SourceSyncScheduler(db_session)
    scheduler.run_maintenance()
    scheduler.trigger_all_for_user(BOOTSTRAP_USER_ID)
    db_session.flush()

    assert _extract_jobs_for_object(db_session, obj.id) == []
    assert obj.metadata_["content_extraction_version"] == "phase29a-v2"


def test_google_drive_explicit_reintake_enqueues_one_stale_version_extract_job(
    db_session, credential_key, oauth_client_file
) -> None:
    file_id = "explicit-reintake-drive"
    md5 = "explicit-stable-md5"
    obj = _seed_google_drive_object(db_session, file_id=file_id, md5=md5)
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "notes.txt",
                "mimeType": "text/plain",
                "md5Checksum": md5,
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "trashed": False,
            }
        }
    )
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="explicit-reintake@example.com",
        scopes=[DRIVE_READONLY_SCOPE],
        access_token="unittest-access",
        refresh_token="unittest-refresh",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.flush()

    service = build_google_explicit_link_intake_service(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        google_transport=transport,
    )
    result = service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )
    service.close()

    assert result.status == "updated"
    assert result.content_jobs_enqueued == 1
    jobs = _extract_jobs_for_object(db_session, obj.id)
    assert len(jobs) == 1
    assert jobs[0].payload["extraction_version"] == EXTRACTION_VERSION


def test_yandex_disk_explicit_reintake_enqueues_one_stale_version_extract_job(
    db_session,
) -> None:
    share_url = "https://disk.yandex.ru/d/explicit-reintake-key"
    resource_id = "explicit-reintake-yandex-file"
    md5 = "explicit-stable-yandex-md5"
    obj = _seed_yandex_disk_object(
        db_session,
        resource_id=resource_id,
        share_url=share_url,
        md5=md5,
    )
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource(
                resource_id,
                "notes.txt",
                public_url=share_url,
                mime_type="text/plain",
                md5=md5,
            )
        }
    )
    service = build_yandex_explicit_link_intake_service(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        yandex_transport=transport,
    )
    result = service.intake_link(url=share_url)
    service.close()

    assert result.status == "updated"
    assert result.content_jobs_enqueued == 1
    jobs = _extract_jobs_for_object(db_session, obj.id)
    assert len(jobs) == 1
    assert jobs[0].payload["extraction_version"] == EXTRACTION_VERSION


def test_extraction_work_needed_true_for_stale_version_same_revision() -> None:
    from app.content_extraction.extract_service import extraction_work_needed

    prior = {
        "content_revision": "gdrive:md5:abc",
        "content_extraction_status": "ready",
        "content_extraction_version": "phase29a-v2",
        "mime_type": "text/plain",
    }
    incoming = dict(prior)
    assert extraction_work_needed(
        GOOGLE_DRIVE_PROVIDER,
        "file",
        "notes.txt",
        prior,
        incoming,
        True,
    )
