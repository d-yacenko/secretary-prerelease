"""PHASE 29A-R1 corrective regression tests."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.connectors.google.constants import GOOGLE_DRIVE_PROVIDER
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.extract_service import ExplicitResourceContentExtractor
from app.content_extraction.mechanical_extractors import extract_from_path
from app.content_extraction.metadata_keys import (
    CONTENT_EXTRACTION_ERROR,
    CONTENT_EXTRACTION_STATUS,
    STATUS_FAILED,
    STATUS_READY,
)
from app.content_extraction.trusted_download import (
    UnsafeDownloadUrlError,
    bounded_get_safe_redirects,
    validate_download_url,
)
from app.db.models import Job, Object, Representation
from app.jobs.constants import (
    JOB_TYPE_EMBED_OBJECT,
    JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT,
    JOB_TYPE_SUMMARIZE_RESOURCE,
)
from app.services.context_service import ContextService
from app.services.domain_tool_service import DomainToolService
from app.services.explicit_link_intake_service import build_google_explicit_link_intake_service
from app.services.retrieval_service import RetrievalService
from app.tools.schemas import RetrieveInput
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.fixtures.phase_29a_fixtures import (
    write_blank_pdf,
    write_txt,
)
from tests.test_phase_29a_bounded_content_extraction import (
    FakeDriveTransport,
    _google_account,
)

TRUSTED_DOWNLOAD_URL = "https://downloader.disk.yandex.ru/disk/test"


def _public_resolver(host: str) -> list[str]:
    return ["93.158.134.8"]


PUBLIC_RESOLVER = _public_resolver


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


def _ready_object_with_rep_phrase(
    db_session,
    phrase: str,
    *,
    title: str = "generic title",
    body: str | None = None,
    revision: str = "rev-a",
) -> Object:
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        title=title,
        body=body,
        origin="source",
        state="observed",
        provider=GOOGLE_DRIVE_PROVIDER,
        external_id=f"obj-{uuid.uuid4().hex[:8]}",
        metadata_={
            "content_revision": revision,
            "content_extraction_status": STATUS_READY,
            "content_extraction_version": EXTRACTION_VERSION,
            "mechanical_representation_count": 1,
            "content_extracted_at": datetime.now(UTC).isoformat(),
        },
    )
    db_session.add(obj)
    db_session.flush()
    db_session.add(
        Representation(
            object_id=obj.id,
            kind="full",
            text=f"indexed body with {phrase}",
        )
    )
    db_session.flush()
    return obj


def test_retrieve_finds_phrase_only_in_representation(db_session) -> None:
    phrase = f"representation_only_phrase_{uuid.uuid4().hex[:8]}"
    obj = _ready_object_with_rep_phrase(db_session, phrase, body=None, title="untitled resource")

    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(phrase).hits
    assert any(hit.object_id == obj.id for hit in hits)


def test_assistant_retrieve_uses_representation_match(db_session) -> None:
    phrase = f"assistant_rep_phrase_{uuid.uuid4().hex[:8]}"
    obj = _ready_object_with_rep_phrase(db_session, phrase, title="assistant doc")

    output = DomainToolService(db_session, BOOTSTRAP_USER_ID).retrieve(
        RetrieveInput(query=phrase, limit=5)
    )
    assert any(row.object_id == obj.id for row in output.hits)


def test_ready_reintake_preserves_ready_and_skips_jobs(
    db_session, credential_key, oauth_client_file, tmp_path: Path
) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "ready-reintake"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "ready.txt",
                "mimeType": "text/plain",
                "md5Checksum": "stable-md5",
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "trashed": False,
            }
        }
    )
    txt_path = tmp_path / "ready.txt"
    write_txt(txt_path, "ready reintake phrase")
    transport.set_download(file_id, txt_path.read_bytes())

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
    obj = db_session.get(Object, first.object_id)
    extractor = ExplicitResourceContentExtractor(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        drive_transport=transport,
        account_store=GoogleAccountStore(db_session, CredentialEncryption(credential_key)),
        token_manager=service._token_manager,
    )
    extractor.run(obj.id, obj.metadata_["content_revision"], EXTRACTION_VERSION)
    db_session.flush()
    db_session.refresh(obj)
    extracted_at = obj.metadata_["content_extracted_at"]
    mech_count = obj.metadata_["mechanical_representation_count"]

    second = service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )
    service.close()
    db_session.refresh(obj)

    assert second.content_status == STATUS_READY
    assert second.content_jobs_enqueued == 0
    assert obj.metadata_["content_extraction_status"] == STATUS_READY
    assert obj.metadata_["content_extracted_at"] == extracted_at
    assert obj.metadata_["mechanical_representation_count"] == mech_count

    extract_jobs = [
        job
        for job in db_session.scalars(select(Job)).all()
        if job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT
        and (job.payload or {}).get("object_id") == str(obj.id)
    ]
    summarize_jobs = [
        job
        for job in db_session.scalars(select(Job)).all()
        if job.type == JOB_TYPE_SUMMARIZE_RESOURCE
        and (job.payload or {}).get("object_id") == str(obj.id)
    ]
    assert len(extract_jobs) == 1
    assert len(summarize_jobs) == 1


def test_revision_change_invalidates_before_worker(
    db_session, credential_key, oauth_client_file, tmp_path: Path
) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "invalidate-file"
    phrase_a = f"invalidate_phrase_alpha_{uuid.uuid4().hex[:8]}"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "invalidate.txt",
                "mimeType": "text/plain",
                "md5Checksum": "rev-a-md5",
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "trashed": False,
            }
        }
    )
    txt_path = tmp_path / "invalidate.txt"
    write_txt(txt_path, phrase_a)
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
    extractor = ExplicitResourceContentExtractor(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        drive_transport=transport,
        account_store=GoogleAccountStore(db_session, CredentialEncryption(credential_key)),
        token_manager=service._token_manager,
    )
    extractor.run(obj.id, obj.metadata_["content_revision"], EXTRACTION_VERSION)
    db_session.flush()
    db_session.refresh(obj)
    obj.embedding = [0.1, 0.2, 0.3]
    db_session.flush()

    transport._files[file_id]["md5Checksum"] = "rev-b-md5"
    write_txt(txt_path, "invalidate_phrase_bravo")
    transport.set_download(file_id, txt_path.read_bytes())
    service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )
    service.close()
    db_session.refresh(obj)

    assert obj.metadata_["content_extraction_status"] == "pending"
    assert obj.embedding is None
    reps = db_session.scalars(
        select(Representation).where(Representation.object_id == obj.id)
    ).all()
    assert reps == []
    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(phrase_a).hits
    assert not any(hit.object_id == obj.id for hit in hits)
    context = ContextService(db_session, BOOTSTRAP_USER_ID).build_context(object_id=obj.id)
    combined = "\n".join(item.content for item in context.items)
    assert phrase_a not in combined


def test_title_only_change_preserves_ready_without_reextract(
    db_session, credential_key, oauth_client_file, tmp_path: Path
) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "title-only"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "old-title.txt",
                "mimeType": "text/plain",
                "md5Checksum": "title-md5",
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "trashed": False,
            }
        }
    )
    txt_path = tmp_path / "title-only.txt"
    write_txt(txt_path, "title only phrase")
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
    extractor = ExplicitResourceContentExtractor(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        drive_transport=transport,
        account_store=GoogleAccountStore(db_session, CredentialEncryption(credential_key)),
        token_manager=service._token_manager,
    )
    extractor.run(obj.id, obj.metadata_["content_revision"], EXTRACTION_VERSION)
    db_session.flush()

    transport._files[file_id]["name"] = "new-title.txt"
    intake = service.intake_link(
        url=f"https://drive.google.com/file/d/{file_id}/view",
        account_id=account.id,
    )
    service.close()
    db_session.refresh(obj)

    assert obj.title == "new-title.txt"
    assert obj.metadata_["content_extraction_status"] == STATUS_READY
    assert intake.content_jobs_enqueued == 1
    embed_jobs = [
        job
        for job in db_session.scalars(select(Job)).all()
        if job.type == JOB_TYPE_EMBED_OBJECT and (job.payload or {}).get("object_id") == str(obj.id)
    ]
    extract_jobs = [
        job
        for job in db_session.scalars(select(Job)).all()
        if job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT
        and (job.payload or {}).get("object_id") == str(obj.id)
    ]
    assert len(extract_jobs) == 1
    assert len(embed_jobs) == 1


def test_pdf_without_text_fails_with_no_extractable_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "blank.pdf"
    write_blank_pdf(pdf_path)
    with pytest.raises(ValueError, match="no_extractable_text"):
        extract_from_path(uuid.uuid4(), pdf_path)


def test_extractor_records_no_extractable_text_failure(
    db_session, credential_key, oauth_client_file, tmp_path: Path
) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "blank-pdf"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "blank.pdf",
                "mimeType": "application/pdf",
                "md5Checksum": "blank-md5",
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "trashed": False,
            }
        }
    )
    pdf_path = tmp_path / "blank.pdf"
    write_blank_pdf(pdf_path)
    transport.set_download(file_id, pdf_path.read_bytes())

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
    extractor = ExplicitResourceContentExtractor(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        drive_transport=transport,
        account_store=GoogleAccountStore(db_session, CredentialEncryption(credential_key)),
        token_manager=service._token_manager,
    )
    extractor.run(obj.id, obj.metadata_["content_revision"], EXTRACTION_VERSION)
    db_session.flush()
    db_session.refresh(obj)
    service.close()

    assert obj.metadata_[CONTENT_EXTRACTION_STATUS] == STATUS_FAILED
    assert obj.metadata_[CONTENT_EXTRACTION_ERROR] == "no_extractable_text"


def test_trusted_download_rejects_unsafe_urls() -> None:
    with pytest.raises(UnsafeDownloadUrlError):
        validate_download_url("http://disk.yandex.ru/d/abc", resolver=PUBLIC_RESOLVER)
    with pytest.raises(UnsafeDownloadUrlError):
        validate_download_url("https://user:pass@disk.yandex.ru/d/abc", resolver=PUBLIC_RESOLVER)
    with pytest.raises(UnsafeDownloadUrlError):
        validate_download_url("https://localhost/d/abc", resolver=PUBLIC_RESOLVER)
    with pytest.raises(UnsafeDownloadUrlError):
        validate_download_url("https://127.0.0.1/d/abc", resolver=PUBLIC_RESOLVER)
    with pytest.raises(UnsafeDownloadUrlError):
        validate_download_url("https://10.0.0.5/file", resolver=PUBLIC_RESOLVER)


def test_trusted_download_rejects_redirect_to_private() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://10.0.0.8/private"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(UnsafeDownloadUrlError):
        bounded_get_safe_redirects(
            client,
            TRUSTED_DOWNLOAD_URL,
            max_bytes=1024,
            resolver=PUBLIC_RESOLVER,
        )


def test_trusted_download_enforces_redirect_hop_limit() -> None:
    hop = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal hop
        hop += 1
        return httpx.Response(
            302,
            headers={"Location": f"https://downloader.disk.yandex.ru/hop{hop}"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(UnsafeDownloadUrlError, match="redirect_hop_limit"):
        bounded_get_safe_redirects(
            client,
            TRUSTED_DOWNLOAD_URL,
            max_bytes=1024,
            resolver=PUBLIC_RESOLVER,
        )


def test_trusted_download_accepts_valid_https_provider_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"provider-bytes")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    data = bounded_get_safe_redirects(
        client,
        TRUSTED_DOWNLOAD_URL,
        max_bytes=1024,
        resolver=PUBLIC_RESOLVER,
    )
    assert data == b"provider-bytes"


def test_failed_corrupt_extraction_status_is_failed(
    db_session, credential_key, oauth_client_file
) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "corrupt-txt"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "broken.pdf",
                "mimeType": "application/pdf",
                "md5Checksum": "broken-md5",
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
    assert obj.metadata_[CONTENT_EXTRACTION_STATUS] == STATUS_FAILED
