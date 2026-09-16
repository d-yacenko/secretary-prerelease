"""PHASE 29A bounded explicit resource content extraction tests."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.connectors.google.constants import DRIVE_READONLY_SCOPE, GOOGLE_DRIVE_PROVIDER
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleApiError
from app.content_extraction.bounded_download import DownloadTooLargeError, bounded_get
from app.content_extraction.constants import EXTRACTION_VERSION, MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES
from app.content_extraction.extract_service import ExplicitResourceContentExtractor
from app.content_extraction.mechanical_extractors import extract_from_path
from app.content_extraction.metadata_keys import STATUS_FAILED, STATUS_READY
from app.content_extraction.zip_safety import UnsafeZipError
from app.db.models import GoogleAccount, Job, Object, Representation, User
from app.jobs.constants import (
    JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
    JOB_TYPE_SUMMARIZE_RESOURCE,
)
from app.services.context_service import ContextService
from app.services.explicit_link_intake_service import build_google_explicit_link_intake_service
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.fixtures.phase_29a_fixtures import (
    write_csv,
    write_minimal_docx,
    write_minimal_pdf,
    write_minimal_pptx,
    write_minimal_xlsx,
    write_txt,
    write_zip_bomb,
)


class FakeDriveTransport:
    def __init__(self, files: dict[str, dict[str, Any]] | None = None) -> None:
        self._files = dict(files or {})
        self._downloads: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []

    def set_download(self, file_id: str, data: bytes) -> None:
        self._downloads[file_id] = data

    def get_file_metadata(self, access_token: str, file_id: str) -> dict[str, Any]:
        self.calls.append(("get_file_metadata", file_id))
        payload = self._files.get(file_id)
        if payload is None:
            raise GoogleApiError("not found", operation="get_file_metadata", status_code=404)
        return dict(payload)

    def export_file(
        self,
        access_token: str,
        file_id: str,
        export_mime: str,
        *,
        max_bytes: int,
    ) -> bytes:
        self.calls.append(("export_file", file_id))
        data = self._downloads.get(file_id)
        if data is None:
            raise ValueError("missing fake download bytes")
        if len(data) > max_bytes:
            raise DownloadTooLargeError(len(data), max_bytes)
        return data

    def download_file_media(
        self,
        access_token: str,
        file_id: str,
        *,
        max_bytes: int,
    ) -> bytes:
        self.calls.append(("download_file_media", file_id))
        data = self._downloads.get(file_id)
        if data is None:
            raise ValueError("missing fake download bytes")
        if len(data) > max_bytes:
            raise DownloadTooLargeError(len(data), max_bytes)
        return data

    def close(self) -> None:
        pass


class FakeYandexDiskTransport:
    def __init__(self) -> None:
        self._downloads: dict[str, bytes] = {}
        self.calls: list[str] = []

    def set_download(self, public_key: str, data: bytes) -> None:
        self._downloads[public_key] = data

    def get_public_resource_metadata(self, public_key: str) -> dict[str, Any]:
        self.calls.append("get_public_resource_metadata")
        return {}

    def get_public_resource_download_url(self, public_key: str) -> str:
        self.calls.append("get_public_resource_download_url")
        return f"https://fake-download.test/{uuid.uuid4().hex}"

    def download_bounded_url(self, url: str, *, max_bytes: int) -> bytes:
        self.calls.append("download_bounded_url")
        for key, data in self._downloads.items():
            if key in url or True:
                if len(data) > max_bytes:
                    raise DownloadTooLargeError(len(data), max_bytes)
                return data
        raise ValueError("missing yandex fake download")

    def close(self) -> None:
        pass


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


def _google_account(db_session, credential_key: str) -> GoogleAccount:
    store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    return store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="phase29a@example.com",
        scopes=[DRIVE_READONLY_SCOPE],
        access_token="unittest-access",
        refresh_token="unittest-refresh",
        token_expiry=datetime.now(UTC) + timedelta(hours=1),
    )


def test_mechanical_extractors_supported_formats(tmp_path: Path) -> None:
    object_id = uuid.uuid4()
    txt_path = tmp_path / "sample.txt"
    write_txt(txt_path)
    reps, meta = extract_from_path(object_id, txt_path)
    assert reps
    assert "distinctive phrase alpha" in reps[0].text
    assert meta["content_format"] == ".txt"

    csv_path = tmp_path / "sample.csv"
    write_csv(csv_path)
    reps, _ = extract_from_path(object_id, csv_path)
    assert {rep.kind for rep in reps} >= {"schema", "sample", "statistics"}

    pdf_path = tmp_path / "sample.pdf"
    write_minimal_pdf(pdf_path)
    reps, _ = extract_from_path(object_id, pdf_path)
    assert any("distinctive phrase delta" in rep.text for rep in reps)

    docx_path = tmp_path / "sample.docx"
    write_minimal_docx(docx_path)
    reps, _ = extract_from_path(object_id, docx_path)
    assert any("distinctive phrase beta" in rep.text for rep in reps)

    xlsx_path = tmp_path / "sample.xlsx"
    write_minimal_xlsx(xlsx_path)
    reps, _ = extract_from_path(object_id, xlsx_path)
    assert any("xlsx_value" in rep.text for rep in reps)

    pptx_path = tmp_path / "sample.pptx"
    write_minimal_pptx(pptx_path)
    reps, _ = extract_from_path(object_id, pptx_path)
    assert any("distinctive phrase gamma" in rep.text for rep in reps)


def test_zip_bomb_rejected(tmp_path: Path) -> None:
    bomb_path = tmp_path / "bomb.docx"
    write_zip_bomb(bomb_path)
    with pytest.raises((UnsafeZipError, Exception)):
        extract_from_path(uuid.uuid4(), bomb_path)


def test_bounded_download_rejects_content_length() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES + 1)},
            content=b"",
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    with pytest.raises(DownloadTooLargeError):
        bounded_get(client, "https://example.test/file", max_bytes=MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES)


def test_google_docs_export_extraction(
    db_session, credential_key, oauth_client_file, tmp_path: Path
) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "gdoc-1"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "Notes",
                "mimeType": "application/vnd.google-apps.document",
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "version": "7",
                "trashed": False,
            }
        }
    )
    transport.set_download(file_id, b"google docs distinctive phrase omega")
    service = build_google_explicit_link_intake_service(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        google_transport=transport,
    )
    result = service.intake_link(
        url=f"https://docs.google.com/document/d/{file_id}/edit",
        account_id=account.id,
    )
    service.close()
    assert result.content_status == "pending"

    extractor = ExplicitResourceContentExtractor(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        drive_transport=transport,
        account_store=GoogleAccountStore(db_session, CredentialEncryption(credential_key)),
        token_manager=service._token_manager,
    )
    obj = db_session.get(Object, result.object_id)
    extractor.run(obj.id, obj.metadata_["content_revision"], EXTRACTION_VERSION)
    db_session.flush()

    reps = db_session.scalars(
        select(Representation).where(Representation.object_id == obj.id)
    ).all()
    assert any("distinctive phrase omega" in rep.text for rep in reps)
    assert obj.metadata_["content_extraction_status"] == STATUS_READY


def test_revision_unchanged_skips_second_extract_job(
    db_session, credential_key, oauth_client_file
) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "stable-file"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "report.pdf",
                "mimeType": "application/pdf",
                "md5Checksum": "same-md5",
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "size": "100",
                "trashed": False,
            }
        }
    )
    transport.set_download(file_id, b"%PDF-1.4\n")
    service = build_google_explicit_link_intake_service(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        google_transport=transport,
    )
    first = service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )
    second = service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )
    service.close()
    assert second.status == "unchanged"
    jobs = [
        job
        for job in db_session.scalars(
            select(Job).where(Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT)
        ).all()
        if (job.payload or {}).get("object_id") == str(first.object_id)
    ]
    assert len(jobs) == 1


def test_stale_extract_job_no_overwrite(db_session, credential_key, oauth_client_file, tmp_path: Path) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "rev-file"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "note.txt",
                "mimeType": "text/plain",
                "md5Checksum": "rev-a",
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "trashed": False,
            }
        }
    )
    txt_path = tmp_path / "note.txt"
    write_txt(txt_path, "stale job phrase one")
    transport.set_download(file_id, txt_path.read_bytes())

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
    obj = db_session.get(Object, result.object_id)
    old_revision = obj.metadata_["content_revision"]

    transport._files[file_id]["md5Checksum"] = "rev-b"
    write_txt(txt_path, "stale job phrase two")
    transport.set_download(file_id, txt_path.read_bytes())
    service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )

    extractor = ExplicitResourceContentExtractor(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        drive_transport=transport,
        account_store=GoogleAccountStore(db_session, CredentialEncryption(credential_key)),
        token_manager=service._token_manager,
    )
    extractor.run(obj.id, old_revision, EXTRACTION_VERSION)
    db_session.flush()
    db_session.refresh(obj)
    reps = db_session.scalars(
        select(Representation).where(Representation.object_id == obj.id)
    ).all()
    assert not any("stale job phrase one" in rep.text for rep in reps)


def test_get_context_includes_mechanical_phrase(db_session, tmp_path: Path) -> None:
    phrase = "context_only_phrase_zeta"
    txt_path = tmp_path / "retrieve.txt"
    write_txt(txt_path, phrase)
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="document",
        title="retrieve.txt",
        origin="source",
        state="observed",
        provider=GOOGLE_DRIVE_PROVIDER,
        external_id="retrieve-file",
        metadata_={
            "content_revision": "test-rev",
            "content_extraction_status": STATUS_READY,
            "content_extraction_version": EXTRACTION_VERSION,
        },
    )
    db_session.add(obj)
    db_session.flush()
    reps, _ = extract_from_path(obj.id, txt_path)
    for rep in reps:
        db_session.add(rep)
    db_session.flush()

    context = ContextService(db_session, BOOTSTRAP_USER_ID).build_context(object_id=obj.id)
    combined = "\n".join(item.content for item in context.items)
    assert phrase in combined


def test_cross_user_extract_rejected(db_session, credential_key) -> None:
    other_user = uuid.uuid4()
    db_session.add(User(id=other_user, display_name="other"))
    db_session.flush()
    obj = Object(
        user_id=other_user,
        kind="file",
        title="secret",
        origin="source",
        state="observed",
        provider=GOOGLE_DRIVE_PROVIDER,
        external_id="secret",
        metadata_={"content_revision": "r1"},
    )
    db_session.add(obj)
    db_session.flush()

    extractor = ExplicitResourceContentExtractor(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        drive_transport=FakeDriveTransport(),
    )
    with pytest.raises(ValueError, match="ownership mismatch"):
        extractor.run(obj.id, "r1", EXTRACTION_VERSION)


def test_google_unsupported_native_type_metadata_only(
    db_session, credential_key, oauth_client_file
) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "drawing-1"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "Sketch",
                "mimeType": "application/vnd.google-apps.drawing",
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "trashed": False,
            }
        }
    )
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
    assert result.content_status == "unsupported"
    obj = db_session.get(Object, result.object_id)
    assert obj is not None
    assert obj.body is None


def test_successful_extraction_enqueues_summarize_once(
    db_session, credential_key, oauth_client_file, tmp_path: Path
) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "summarize-once"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "note.txt",
                "mimeType": "text/plain",
                "md5Checksum": "md5-once",
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "trashed": False,
            }
        }
    )
    txt_path = tmp_path / "note.txt"
    write_txt(txt_path, "summarize enqueue phrase")
    transport.set_download(file_id, txt_path.read_bytes())
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
    extractor = ExplicitResourceContentExtractor(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        drive_transport=transport,
        account_store=GoogleAccountStore(db_session, CredentialEncryption(credential_key)),
        token_manager=service._token_manager,
    )
    obj = db_session.get(Object, result.object_id)
    extractor.run(obj.id, obj.metadata_["content_revision"], EXTRACTION_VERSION)
    db_session.flush()
    summarize_jobs = [
        job
        for job in db_session.scalars(
            select(Job).where(Job.type == JOB_TYPE_SUMMARIZE_RESOURCE)
        ).all()
        if (job.payload or {}).get("object_id") == str(obj.id)
    ]
    service.close()
    assert len(summarize_jobs) == 1


def test_failed_extraction_preserves_object(
    db_session, credential_key, oauth_client_file
) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "fail-file"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "broken.pdf",
                "mimeType": "application/pdf",
                "md5Checksum": "md5-fail",
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "trashed": False,
            }
        }
    )
    transport.set_download(file_id, b"%PDF-1.4 corrupt not a valid pdf structure")
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
    extractor = ExplicitResourceContentExtractor(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        drive_transport=transport,
        account_store=GoogleAccountStore(db_session, CredentialEncryption(credential_key)),
        token_manager=service._token_manager,
    )
    obj = db_session.get(Object, result.object_id)
    extractor.run(obj.id, obj.metadata_["content_revision"], EXTRACTION_VERSION)
    db_session.flush()
    db_session.refresh(obj)
    service.close()
    assert obj.id == result.object_id
    assert obj.metadata_["content_extraction_status"] == STATUS_FAILED
