import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.deps import get_db, get_embedding_service
from app.api.schemas import EdgeCreate, ObjectCreate, ResourceRegisterRequest
from app.core.config import settings
from app.db.models import Job, Object, Representation, User
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT, JOB_TYPE_SUMMARIZE_RESOURCE
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.embedding_text import embed_job_payload
from app.main import app
from app.resources.constants import (
    CONTENT_INGESTED_REVISION_KEY,
    PROVIDER_GOOGLE_DRIVE,
    PROVIDER_YANDEX_DISK,
)
from app.resources.upload_staging import StagedUpload
from app.resources.web_fetch import WebFetchResult
from app.services.graph_service import GraphService
from app.services.job_queue_service import JobQueueService
from app.services.resource_registration_service import ResourceRegistrationService
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def client(db_session, tmp_path: Path, auth_headers):
    from tests.conftest import apply_embedding_service_overrides, AuthTestClient

    upload_root = tmp_path / "api-uploads"
    upload_root.mkdir()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(FakeEmbeddingService())
    with (
        patch.object(settings, "resource_upload_root", str(upload_root)),
        TestClient(app) as test_client,
    ):
        yield AuthTestClient(test_client, auth_headers)
    app.dependency_overrides.clear()


@pytest.fixture
def upload_root(tmp_path: Path) -> Path:
    return tmp_path / "uploads"


def _register_service(db_session, upload_root: Path) -> ResourceRegistrationService:
    return ResourceRegistrationService(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        job_queue=JobQueueService(db_session),
        upload_root=upload_root,
    )


def _staged_upload(path: Path, filename: str | None = None) -> StagedUpload:
    data = path.read_bytes()
    return StagedUpload(
        path=path,
        content_hash=hashlib.sha256(data).hexdigest(),
        original_filename=filename or path.name,
        size=len(data),
    )


def test_register_google_drive_metadata_only_enqueues_embed(db_session, upload_root) -> None:
    service = _register_service(db_session, upload_root)
    result = service.register(
        ResourceRegisterRequest(
            kind="file",
            title="Budget report",
            canonical_uri="https://drive.google.com/file/d/abc123/view",
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="abc123",
            metadata={
                "mime_type": "application/pdf",
                "size": 1024,
                "modified_at": "2026-01-15T10:00:00Z",
                "etag": "rev-1",
            },
        )
    )
    assert result.status == "created"
    assert result.jobs_enqueued == 1
    assert result.representations_created == 0

    job = db_session.scalar(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT))
    assert job is not None

    obj = db_session.scalar(select(Object).where(Object.id == result.object_id))
    assert obj is not None
    assert obj.provider == PROVIDER_GOOGLE_DRIVE
    assert obj.external_id == "abc123"


def test_register_same_revision_skips_reprocessing(db_session, upload_root) -> None:
    service = _register_service(db_session, upload_root)
    payload = ResourceRegisterRequest(
        kind="file",
        title="Budget report",
        canonical_uri="https://drive.google.com/file/d/abc123/view",
        provider=PROVIDER_GOOGLE_DRIVE,
        external_id="abc123",
        metadata={
            "mime_type": "application/pdf",
            "etag": "rev-1",
            "modified_at": "2026-01-15T10:00:00Z",
        },
    )
    first = service.register(payload)
    second = service.register(payload)
    assert first.status == "created"
    assert second.status == "unchanged"
    assert second.jobs_enqueued == 0

    job_count = db_session.scalar(
        select(func.count()).select_from(Job).where(Job.type == JOB_TYPE_SUMMARIZE_RESOURCE)
    )
    assert job_count == 0


def test_register_same_revision_metadata_change_no_reingest(db_session, upload_root) -> None:
    service = _register_service(db_session, upload_root)
    base_metadata = {
        "etag": "rev-1",
        "modified_at": "2026-01-15T10:00:00Z",
        "mime_type": "application/pdf",
    }
    first = service.register(
        ResourceRegisterRequest(
            kind="file",
            title="Budget report",
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="abc123",
            canonical_uri="https://drive.google.com/file/d/abc123/view",
            metadata=base_metadata,
            ingest_content=True,
            text="version one body",
        )
    )
    assert first.jobs_enqueued == 1

    second = service.register(
        ResourceRegisterRequest(
            kind="file",
            title="Budget report renamed",
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="abc123",
            canonical_uri="https://drive.google.com/file/d/abc123/new-view",
            metadata={**base_metadata, "mime_type": "application/vnd.pdf"},
            ingest_content=True,
            text="version one body",
        )
    )
    assert second.status == "updated"
    assert second.jobs_enqueued == 0
    assert second.representations_created == 0

    obj = db_session.scalar(select(Object).where(Object.id == first.object_id))
    assert obj.title == "Budget report renamed"
    assert obj.metadata_[CONTENT_INGESTED_REVISION_KEY] is not None

    job_count = db_session.scalar(
        select(func.count()).select_from(Job).where(Job.type == JOB_TYPE_SUMMARIZE_RESOURCE)
    )
    assert job_count == 1


def test_register_same_revision_already_ingested_skips_content(db_session, upload_root) -> None:
    service = _register_service(db_session, upload_root)
    metadata = {"etag": "rev-1", "modified_at": "2026-01-15T10:00:00Z"}
    first = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Notes",
            text="stable notes",
            ingest_content=True,
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="notes-stable-1",
            metadata=metadata,
        )
    )
    assert first.jobs_enqueued == 1

    with patch("app.services.resource_registration_service.fetch_web_page") as mock_fetch:
        second = service.register(
            ResourceRegisterRequest(
                kind="document",
                title="Notes",
                text="stable notes",
                ingest_content=True,
                provider=PROVIDER_GOOGLE_DRIVE,
                external_id="notes-stable-1",
                metadata=metadata,
            )
        )
        mock_fetch.assert_not_called()

    assert second.status == "unchanged"
    assert second.jobs_enqueued == 0
    assert second.representations_created == 0


def test_register_metadata_only_then_ingest_once(db_session, upload_root) -> None:
    service = _register_service(db_session, upload_root)
    metadata = {"etag": "rev-ingest-1", "modified_at": "2026-02-01T10:00:00Z"}
    first = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Deferred ingest",
            text="content to ingest later",
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="deferred-ingest-1",
            metadata=metadata,
        )
    )
    assert first.jobs_enqueued == 1
    obj = db_session.scalar(select(Object).where(Object.id == first.object_id))
    assert obj.metadata_.get(CONTENT_INGESTED_REVISION_KEY) is None

    second = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Deferred ingest",
            text="content to ingest later",
            ingest_content=True,
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="deferred-ingest-1",
            metadata=metadata,
        )
    )
    assert second.status == "updated"
    assert second.jobs_enqueued == 1
    assert second.representations_created == 1
    obj = db_session.scalar(select(Object).where(Object.id == first.object_id))
    assert obj.metadata_[CONTENT_INGESTED_REVISION_KEY] == obj.metadata_["content_revision"]

    third = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Deferred ingest",
            text="content to ingest later",
            ingest_content=True,
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="deferred-ingest-1",
            metadata=metadata,
        )
    )
    assert third.jobs_enqueued == 0


def test_register_new_revision_ingests_when_requested(db_session, upload_root) -> None:
    service = _register_service(db_session, upload_root)
    service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Evolving doc",
            text="revision one",
            ingest_content=True,
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="evolving-doc-1",
            metadata={"etag": "rev-a", "modified_at": "2026-01-01T10:00:00Z"},
        )
    )
    second = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Evolving doc",
            text="revision two",
            ingest_content=True,
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="evolving-doc-1",
            metadata={"etag": "rev-b", "modified_at": "2026-02-01T10:00:00Z"},
        )
    )
    assert second.status == "updated"
    assert second.jobs_enqueued == 1
    assert second.representations_created == 1

    job_count = db_session.scalar(
        select(func.count()).select_from(Job).where(Job.type == JOB_TYPE_SUMMARIZE_RESOURCE)
    )
    assert job_count == 2


def test_register_revision_change_updates_metadata_without_embed(db_session, upload_root) -> None:
    service = _register_service(db_session, upload_root)
    first = service.register(
        ResourceRegisterRequest(
            kind="file",
            title="Budget report",
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="abc123",
            canonical_uri="https://drive.google.com/file/d/abc123/view",
            metadata={"etag": "rev-1", "modified_at": "2026-01-15T10:00:00Z"},
        )
    )
    second = service.register(
        ResourceRegisterRequest(
            kind="file",
            title="Budget report v2",
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="abc123",
            canonical_uri="https://drive.google.com/file/d/abc123/view",
            metadata={"etag": "rev-2", "modified_at": "2026-02-01T10:00:00Z"},
        )
    )
    assert second.status == "updated"
    assert second.jobs_enqueued == 1
    obj = db_session.scalar(select(Object).where(Object.id == first.object_id))
    assert obj.title == "Budget report v2"
    assert obj.metadata_["etag"] == "rev-2"


def test_register_yandex_disk_metadata(db_session, upload_root) -> None:
    service = _register_service(db_session, upload_root)
    result = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Shared doc",
            canonical_uri="https://disk.yandex.ru/client/disk/doc",
            provider=PROVIDER_YANDEX_DISK,
            external_id="disk-file-9",
            metadata={
                "mime_type": "text/plain",
                "size": 200,
                "modified_at": "2026-03-01T12:00:00Z",
                "revision": "42",
            },
        )
    )
    assert result.status == "created"
    obj = db_session.scalar(select(Object).where(Object.id == result.object_id))
    assert obj.provider == PROVIDER_YANDEX_DISK


def test_register_text_with_ingest_creates_representations_and_job(
    db_session, upload_root
) -> None:
    service = _register_service(db_session, upload_root)
    text = "Important meeting notes for the project."
    result = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Meeting notes",
            text=text,
            ingest_content=True,
        )
    )
    assert result.status == "created"
    assert result.jobs_enqueued == 1
    assert result.representations_created == 1

    reps = list(
        db_session.scalars(
            select(Representation).where(Representation.object_id == result.object_id)
        ).all()
    )
    assert len(reps) == 1


@patch("app.services.embedding_index.refresh_object_embedding")
def test_register_changed_resource_one_embed_job_no_sync_embedding(
    mock_refresh, db_session, upload_root
) -> None:
    service = _register_service(db_session, upload_root)
    result = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Embed once",
            text="unique content for embedding",
            ingest_content=True,
        )
    )
    mock_refresh.assert_not_called()
    assert result.jobs_enqueued == 1
    job_count = db_session.scalar(
        select(func.count()).select_from(Job).where(Job.type == JOB_TYPE_SUMMARIZE_RESOURCE)
    )
    assert job_count == 1


def test_register_unchanged_ingested_revision_no_embedding_activity(
    db_session, upload_root
) -> None:
    service = _register_service(db_session, upload_root)
    metadata = {"etag": "stable", "modified_at": "2026-01-01T00:00:00Z"}
    first = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Stable",
            text="same",
            ingest_content=True,
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="stable-ingest-1",
            metadata=metadata,
        )
    )
    rep_count_before = db_session.scalar(
        select(func.count()).select_from(Representation).where(
            Representation.object_id == first.object_id
        )
    )

    with patch("app.services.embedding_index.refresh_object_embedding") as mock_refresh:
        second = service.register(
            ResourceRegisterRequest(
                kind="document",
                title="Stable",
                text="same",
                ingest_content=True,
                provider=PROVIDER_GOOGLE_DRIVE,
                external_id="stable-ingest-1",
                metadata=metadata,
            )
        )
        mock_refresh.assert_not_called()

    assert second.jobs_enqueued == 0
    rep_count_after = db_session.scalar(
        select(func.count()).select_from(Representation).where(
            Representation.object_id == first.object_id
        )
    )
    assert rep_count_after == rep_count_before


def test_register_web_page_stub_without_ingest(db_session, upload_root) -> None:
    service = _register_service(db_session, upload_root)
    result = service.register(
        ResourceRegisterRequest(
            kind="web_page",
            title="Example",
            canonical_uri="https://example.com/docs",
        )
    )
    assert result.status == "created"
    assert result.jobs_enqueued == 1
    obj = db_session.scalar(select(Object).where(Object.id == result.object_id))
    assert obj.kind == "web_page"


@patch("app.services.resource_registration_service.fetch_web_page")
def test_register_web_page_with_ingest(mock_fetch, db_session, upload_root) -> None:
    mock_fetch.return_value = WebFetchResult(
        title="Fetched title",
        text="Bounded page text",
        final_url="https://example.com/docs",
    )
    service = _register_service(db_session, upload_root)
    tx_checks: list[bool] = []

    def fetch_with_tx_check(url: str) -> WebFetchResult:
        tx_checks.append(db_session.in_transaction())
        return mock_fetch.return_value

    mock_fetch.side_effect = fetch_with_tx_check

    result = service.register(
        ResourceRegisterRequest(
            kind="web_page",
            title="Example",
            canonical_uri="https://example.com/docs",
            ingest_content=True,
        )
    )
    assert tx_checks == [False]
    assert result.status == "created"
    assert result.jobs_enqueued == 1
    assert result.representations_created == 1
    obj = db_session.scalar(select(Object).where(Object.id == result.object_id))
    assert obj.title == "Fetched title"
    assert obj.body == "Bounded page text"


def test_register_upload_file_with_ingest(db_session, upload_root, tmp_path) -> None:
    source = tmp_path / "notes.md"
    source.write_text("Uploaded markdown content.", encoding="utf-8")
    staged = _staged_upload(source, "notes.md")
    service = _register_service(db_session, upload_root)
    result = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Uploaded notes",
            ingest_content=True,
        ),
        staged_upload=staged,
    )
    assert result.status == "created"
    assert result.jobs_enqueued == 1
    assert result.representations_created == 1
    obj = db_session.scalar(select(Object).where(Object.id == result.object_id))
    assert obj.provider == "upload"
    assert obj.external_id == staged.content_hash
    assert obj.metadata_["upload_filename"] == "notes.md"


def test_task_can_link_to_registered_resource(db_session, upload_root) -> None:
    service = _register_service(db_session, upload_root)
    registered = service.register(
        ResourceRegisterRequest(
            kind="file",
            title="Drive spec",
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="spec-1",
            canonical_uri="https://drive.google.com/file/d/spec-1/view",
            metadata={"etag": "e1"},
        )
    )
    graph = GraphService(db_session, BOOTSTRAP_USER_ID)
    task = graph.create_object(
        ObjectCreate(kind="task", title="Review spec", origin="user")
    )
    edge = graph.create_edge(
        EdgeCreate(
            source_id=task.id,
            target_id=registered.object_id,
            type="attached_to",
            origin="user",
            state="confirmed",
        )
    )
    assert edge.source_id == task.id
    assert edge.target_id == registered.object_id


def test_register_api_json(client: TestClient) -> None:
    response = client.post(
        "/resources/register",
        json={
            "kind": "file",
            "title": "API file",
            "canonical_uri": "https://drive.google.com/file/d/api-1/view",
            "provider": PROVIDER_GOOGLE_DRIVE,
            "external_id": "api-1",
            "metadata": {"etag": "api-e1", "mime_type": "text/plain"},
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "created"
    assert payload["jobs_enqueued"] == 1


def test_register_api_multipart_upload(client: TestClient) -> None:
    content = b"hello from upload"
    content_hash = hashlib.sha256(content).hexdigest()
    payload = {
        "kind": "document",
        "title": "Multipart doc",
        "ingest_content": True,
    }
    response = client.post(
        "/resources/register",
        data={"payload": json.dumps(payload)},
        files={"file": ("note.txt", content, "text/plain")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["representations_created"] == 1
    assert body["jobs_enqueued"] == 1
    assert body["external_id"] == content_hash


def test_register_api_upload_at_limit(client: TestClient) -> None:
    with patch("app.resources.upload_staging.MAX_UPLOAD_BYTES", 1024):
        content = b"x" * 1024
        response = client.post(
            "/resources/register",
            data={"payload": json.dumps({"kind": "document", "title": "Limit ok"})},
            files={"file": ("limit.txt", content, "text/plain")},
        )
    assert response.status_code == 201


def test_register_api_upload_over_limit_rejected(client: TestClient) -> None:
    with patch("app.resources.upload_staging.MAX_UPLOAD_BYTES", 1024):
        content = b"x" * 1025
        response = client.post(
            "/resources/register",
            data={"payload": json.dumps({"kind": "document", "title": "Too big"})},
            files={"file": ("big.txt", content, "text/plain")},
        )
    assert response.status_code == 413


def test_register_api_preserves_original_filename(client: TestClient, db_session) -> None:
    content = b"filename test"
    response = client.post(
        "/resources/register",
        data={"payload": json.dumps({"kind": "document", "title": "Named upload"})},
        files={"file": ("My Report.txt", content, "text/plain")},
    )
    assert response.status_code == 201
    obj = db_session.scalar(select(Object).where(Object.id == response.json()["object_id"]))
    assert obj.metadata_["upload_filename"] == "My_Report.txt"


def test_register_api_malformed_payload_returns_422(client: TestClient) -> None:
    response = client.post(
        "/resources/register",
        data={"payload": "not-json"},
        files={"file": ("note.txt", b"hi", "text/plain")},
    )
    assert response.status_code == 422

    bad_json = client.post(
        "/resources/register",
        content=b"{bad",
        headers={"content-type": "application/json"},
    )
    assert bad_json.status_code == 422


def test_register_api_oversized_json_returns_413(client: TestClient) -> None:
    with patch("app.api.routes.resources.MAX_REGISTER_PAYLOAD_BYTES", 128):
        response = client.post(
            "/resources/register",
            content=b"x" * 129,
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413


def test_register_api_oversized_multipart_payload_returns_413(client: TestClient) -> None:
    with patch("app.api.routes.resources.MAX_UPLOAD_BYTES", 64), patch(
        "app.api.routes.resources.MAX_MULTIPART_PAYLOAD_BYTES", 64
    ):
        response = client.post(
            "/resources/register",
            files={"payload": (None, "x" * 65)},
        )
    assert response.status_code == 413


def test_different_external_id_same_revision_are_separate_objects(
    db_session, upload_root
) -> None:
    service = _register_service(db_session, upload_root)
    metadata = {"revision": "42", "modified_at": "2026-03-01T12:00:00Z"}
    first = service.register(
        ResourceRegisterRequest(
            kind="file",
            title="Yandex file A",
            provider=PROVIDER_YANDEX_DISK,
            external_id="disk-file-a",
            metadata=metadata,
        )
    )
    second = service.register(
        ResourceRegisterRequest(
            kind="file",
            title="Yandex file B",
            provider=PROVIDER_YANDEX_DISK,
            external_id="disk-file-b",
            metadata=metadata,
        )
    )
    assert first.object_id != second.object_id


def test_same_revision_different_providers_do_not_merge(db_session, upload_root) -> None:
    service = _register_service(db_session, upload_root)
    metadata = {"revision": "42", "modified_at": "2026-03-01T12:00:00Z"}
    google = service.register(
        ResourceRegisterRequest(
            kind="file",
            title="Drive file",
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="shared-rev-object",
            metadata=metadata,
        )
    )
    yandex = service.register(
        ResourceRegisterRequest(
            kind="file",
            title="Disk file",
            provider=PROVIDER_YANDEX_DISK,
            external_id="shared-rev-object",
            metadata=metadata,
        )
    )
    assert google.object_id != yandex.object_id


def test_same_provider_external_id_updates_in_place(db_session, upload_root) -> None:
    service = _register_service(db_session, upload_root)
    first = service.register(
        ResourceRegisterRequest(
            kind="file",
            title="Original title",
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="stable-object-1",
            metadata={"etag": "rev-1", "modified_at": "2026-01-01T00:00:00Z"},
        )
    )
    second = service.register(
        ResourceRegisterRequest(
            kind="file",
            title="Updated title",
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="stable-object-1",
            metadata={"etag": "rev-2", "modified_at": "2026-02-01T00:00:00Z"},
        )
    )
    assert second.object_id == first.object_id
    obj = db_session.scalar(select(Object).where(Object.id == first.object_id))
    assert obj.title == "Updated title"
    assert obj.metadata_["etag"] == "rev-2"


def test_register_long_text_chunks_embedded_by_worker_and_ranked_in_context(
    db_session, upload_root
) -> None:
    from app.jobs.handlers import handle_embed_object
    from app.llm.concept_stub_embedding import ConceptStubEmbeddingService
    from app.services.context_service import ContextService
    from app.services.representation_service import KIND_CHUNK, SMALL_TEXT_MAX_CHARS

    service = _register_service(db_session, upload_root)
    finance_sentence = "Budget planning section with revenue targets and expense review. "
    long_text = finance_sentence * 40
    assert len(long_text) > SMALL_TEXT_MAX_CHARS

    with patch.object(ConceptStubEmbeddingService, "embed") as mock_embed:
        result = service.register(
            ResourceRegisterRequest(
                kind="document",
                title="Finance report",
                text=long_text,
                ingest_content=True,
                provider=PROVIDER_GOOGLE_DRIVE,
                external_id="finance-long-1",
                metadata={"etag": "fin-long-1"},
            )
        )
        mock_embed.assert_not_called()

    chunks = list(
        db_session.scalars(
            select(Representation).where(
                Representation.object_id == result.object_id,
                Representation.kind == KIND_CHUNK,
            )
        ).all()
    )
    assert chunks
    assert all(chunk.embedding is None for chunk in chunks)

    stub = ConceptStubEmbeddingService()
    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: db_session
    ), patch.object(db_session, "close", lambda: None):
        handle_embed_object(
            db_session,
            stub,
            embed_job_payload(db_session.get(Object, result.object_id)),
            BOOTSTRAP_USER_ID,
        )
    db_session.expire_all()
    chunks_after = list(
        db_session.scalars(
            select(Representation).where(
                Representation.object_id == result.object_id,
                Representation.kind == KIND_CHUNK,
            )
        ).all()
    )
    assert all(chunk.embedding is not None for chunk in chunks_after)

    context = ContextService(
        db_session, BOOTSTRAP_USER_ID, ConceptStubEmbeddingService()
    ).build_context(
        object_id=result.object_id,
        query="budget revenue planning",
    )
    chunk_items = [
        item for item in context.items if item.representation_kind == KIND_CHUNK
    ]
    assert chunk_items


def test_worker_rejects_embedding_other_user_chunk_representations(
    db_session, upload_root, user_b_id
) -> None:
    from app.jobs.handlers import handle_embed_object
    from app.services.representation_embedding_worker import load_unembedded_chunk_targets

    service_a = ResourceRegistrationService(
        db_session,
        BOOTSTRAP_USER_ID,
        JobQueueService(db_session),
        upload_root=upload_root,
    )
    finance_sentence = "Budget planning section with revenue targets and expense review. "
    long_text = finance_sentence * 40
    result = service_a.register(
        ResourceRegisterRequest(
            kind="document",
            title="Private finance",
            text=long_text,
            ingest_content=True,
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="private-finance-1",
            metadata={"etag": "pf-1"},
        )
    )
    with pytest.raises(ValueError, match="ownership mismatch"), patch(
        "app.services.representation_embedding_worker.SessionLocal",
        lambda: db_session,
    ):
        load_unembedded_chunk_targets(result.object_id, user_b_id)
    obj_before = db_session.get(Object, result.object_id)
    embedding_before = obj_before.embedding
    handle_embed_object(
        db_session,
        FakeEmbeddingService(),
        {"object_id": str(result.object_id)},
        user_b_id,
    )
    obj_after = db_session.get(Object, result.object_id)
    assert obj_after.embedding == embedding_before


def test_metadata_only_upload_persisted_for_later_ingest(
    db_session, upload_root, tmp_path
) -> None:
    source = tmp_path / "defer.txt"
    source.write_text("deferred upload content", encoding="utf-8")
    staged = _staged_upload(source, "defer.txt")
    service = _register_service(db_session, upload_root)
    first = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Deferred file",
            ingest_content=False,
        ),
        staged_upload=staged,
    )
    assert first.jobs_enqueued == 1
    obj = db_session.scalar(select(Object).where(Object.id == first.object_id))
    stored_path = Path(obj.metadata_["upload_path"])
    assert stored_path.is_file()
    assert upload_root in stored_path.parents or str(upload_root) in str(stored_path)
    assert obj.metadata_["upload_filename"] == "defer.txt"
    assert stored_path.name == f"{staged.content_hash}.txt"
    original_hash = obj.metadata_["content_hash"]
    original_revision = obj.metadata_["content_revision"]

    second = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Deferred file",
            ingest_content=True,
            provider="upload",
            external_id=staged.content_hash,
        ),
    )
    assert second.object_id == first.object_id
    assert second.representations_created == 1
    assert second.jobs_enqueued == 1

    obj = db_session.scalar(select(Object).where(Object.id == first.object_id))
    assert obj.metadata_["upload_path"] == str(stored_path)
    assert Path(obj.metadata_["upload_path"]).is_file()
    assert obj.metadata_["content_hash"] == original_hash
    assert obj.metadata_["content_revision"] == original_revision
    assert obj.metadata_[CONTENT_INGESTED_REVISION_KEY] == original_revision
    assert obj.metadata_["upload_filename"] == "defer.txt"

    third = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Deferred file",
            ingest_content=True,
            provider="upload",
            external_id=staged.content_hash,
        ),
    )
    assert third.status == "unchanged"
    assert third.representations_created == 0
    assert third.jobs_enqueued == 0
    obj = db_session.scalar(select(Object).where(Object.id == first.object_id))
    assert obj.metadata_["upload_path"] == str(stored_path)
    assert Path(obj.metadata_["upload_path"]).is_file()
    assert obj.metadata_["content_hash"] == original_hash
    assert obj.metadata_["content_revision"] == original_revision
    assert obj.metadata_[CONTENT_INGESTED_REVISION_KEY] == original_revision
    assert obj.metadata_["upload_filename"] == "defer.txt"


def test_new_upload_orphan_cleaned_on_ingest_failure_preserves_old_revision(
    db_session, upload_root, tmp_path
) -> None:
    from app.services.representation_service import RepresentationService

    old_source = tmp_path / "old.txt"
    old_source.write_text("old revision content", encoding="utf-8")
    old_staged = _staged_upload(old_source, "old.txt")
    service = _register_service(db_session, upload_root)
    first = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Versioned file",
            ingest_content=True,
            provider="upload",
            external_id="versioned-upload-1",
        ),
        staged_upload=old_staged,
    )
    obj = db_session.scalar(select(Object).where(Object.id == first.object_id))
    old_path = Path(obj.metadata_["upload_path"])
    assert old_path.is_file()

    new_source = tmp_path / "new.txt"
    new_source.write_text("new revision content fails extraction", encoding="utf-8")
    new_staged = _staged_upload(new_source, "new.txt")
    new_path = (
        upload_root
        / str(BOOTSTRAP_USER_ID)
        / str(first.object_id)
        / f"{new_staged.content_hash}.txt"
    )

    with patch.object(
        RepresentationService,
        "ingest_file",
        side_effect=ValueError("extract failed"),
    ), pytest.raises(ValueError, match="extract failed"):
        service.register(
            ResourceRegisterRequest(
                kind="document",
                title="Versioned file",
                ingest_content=True,
                provider="upload",
                external_id="versioned-upload-1",
            ),
            staged_upload=new_staged,
        )

    assert old_path.is_file()
    assert not new_path.is_file()
    obj = db_session.scalar(select(Object).where(Object.id == first.object_id))
    assert obj.metadata_["upload_path"] == str(old_path)
    assert obj.metadata_["content_hash"] == old_staged.content_hash
    assert obj.metadata_.get(CONTENT_INGESTED_REVISION_KEY) is not None


def test_same_hash_reupload_preserves_path_and_skips_reingest(
    db_session, upload_root, tmp_path
) -> None:
    source = tmp_path / "same.txt"
    source.write_text("same bytes content", encoding="utf-8")
    staged = _staged_upload(source, "original_name.txt")
    service = _register_service(db_session, upload_root)
    first = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Same hash doc",
            ingest_content=True,
        ),
        staged_upload=staged,
    )
    obj = db_session.scalar(select(Object).where(Object.id == first.object_id))
    original_path = Path(obj.metadata_["upload_path"])

    renamed = _staged_upload(source, "renamed_display.txt")
    second = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Same hash doc",
            ingest_content=True,
            provider="upload",
            external_id=staged.content_hash,
        ),
        staged_upload=renamed,
    )
    assert second.object_id == first.object_id
    assert second.status == "updated"
    assert second.jobs_enqueued == 0
    assert second.representations_created == 0

    obj = db_session.scalar(select(Object).where(Object.id == first.object_id))
    assert Path(obj.metadata_["upload_path"]) == original_path
    assert original_path.is_file()
    assert obj.metadata_["upload_filename"] == "renamed_display.txt"


def test_worker_chunk_embedding_calls_are_bounded(
    db_session, upload_root
) -> None:
    from app.jobs.handlers import handle_embed_object
    from app.services.bounded_chunks import MAX_INDEXED_TEXT_CHUNKS
    from app.services.representation_service import KIND_CHUNK

    service = _register_service(db_session, upload_root)
    finance_sentence = "Budget planning section with revenue targets and expense review. "
    long_text = finance_sentence * 40
    result = service.register(
        ResourceRegisterRequest(
            kind="document",
            title="Bounded embed doc",
            text=long_text,
            ingest_content=True,
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="bounded-embed-1",
            metadata={"etag": "bounded-embed-etag"},
        )
    )
    chunk_count = db_session.scalar(
        select(func.count()).select_from(Representation).where(
            Representation.object_id == result.object_id,
            Representation.kind == KIND_CHUNK,
        )
    )
    assert chunk_count is not None
    assert chunk_count <= MAX_INDEXED_TEXT_CHUNKS

    embed_calls: list[str] = []

    class CountingEmbedding(FakeEmbeddingService):
        def embed(self, text: str) -> list[float]:
            embed_calls.append(text)
            return super().embed(text)

    stub = CountingEmbedding()
    with patch("app.jobs.handlers.SessionLocal", lambda: db_session), patch(
        "app.services.representation_embedding_worker.SessionLocal", lambda: db_session
    ), patch.object(db_session, "close", lambda: None):
        handle_embed_object(
            db_session,
            stub,
            embed_job_payload(db_session.get(Object, result.object_id)),
            BOOTSTRAP_USER_ID,
        )

    assert len(embed_calls) <= MAX_INDEXED_TEXT_CHUNKS + 1


def test_two_users_upload_same_filename_isolated(db_session, upload_root, user_b_id) -> None:
    service_a = ResourceRegistrationService(
        db_session,
        BOOTSTRAP_USER_ID,
        JobQueueService(db_session),
        upload_root=upload_root,
    )
    service_b = ResourceRegistrationService(
        db_session,
        user_b_id,
        JobQueueService(db_session),
        upload_root=upload_root,
    )
    content_a = b"user-a-content"
    content_b = b"user-b-content"
    staged_a = StagedUpload(
        path=Path("/unused"),
        content_hash=hashlib.sha256(content_a).hexdigest(),
        original_filename="report.txt",
        size=len(content_a),
    )
    staged_b = StagedUpload(
        path=Path("/unused"),
        content_hash=hashlib.sha256(content_b).hexdigest(),
        original_filename="report.txt",
        size=len(content_b),
    )
    staging = upload_root / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    path_a = staging / "a.bin"
    path_b = staging / "b.bin"
    path_a.write_bytes(content_a)
    path_b.write_bytes(content_b)
    staged_a = StagedUpload(
        path=path_a,
        content_hash=staged_a.content_hash,
        original_filename="report.txt",
        size=len(content_a),
    )
    staged_b = StagedUpload(
        path=path_b,
        content_hash=staged_b.content_hash,
        original_filename="report.txt",
        size=len(content_b),
    )
    result_a = service_a.register(
        ResourceRegisterRequest(kind="document", title="Report A"),
        staged_upload=staged_a,
    )
    result_b = service_b.register(
        ResourceRegisterRequest(kind="document", title="Report B"),
        staged_upload=staged_b,
    )
    obj_a = db_session.scalar(select(Object).where(Object.id == result_a.object_id))
    obj_b = db_session.scalar(select(Object).where(Object.id == result_b.object_id))
    path_a_stored = Path(obj_a.metadata_["upload_path"])
    path_b_stored = Path(obj_b.metadata_["upload_path"])
    assert path_a_stored != path_b_stored
    assert path_a_stored.read_bytes() == content_a
    assert path_b_stored.read_bytes() == content_b


def test_staging_paths_unique_per_request(tmp_path) -> None:
    import asyncio

    from app.resources.upload_staging import stage_upload_file

    class FakeUpload:
        def __init__(self, data: bytes, filename: str) -> None:
            self._data = data
            self.filename = filename
            self._done = False

        async def read(self, size: int = -1) -> bytes:
            if self._done:
                return b""
            self._done = True
            return self._data

    async def stage_twice() -> list[Path]:
        staging_dir = tmp_path / "staging"
        paths: list[Path] = []
        for _ in range(2):
            staged = await stage_upload_file(
                FakeUpload(b"same-bytes", "same-name.txt"),
                staging_dir,
            )
            paths.append(staged.path)
        return paths

    paths = asyncio.run(stage_twice())
    assert paths[0] != paths[1]


def test_user_b_cannot_access_user_a_registered_resource(
    db_session, upload_root, user_b_id
) -> None:
    service_a = ResourceRegistrationService(
        db_session,
        BOOTSTRAP_USER_ID,
        JobQueueService(db_session),
        upload_root=upload_root,
    )
    result = service_a.register(
        ResourceRegisterRequest(
            kind="document",
            title="Private doc",
            provider=PROVIDER_GOOGLE_DRIVE,
            external_id="private-1",
            metadata={"etag": "p1"},
        )
    )
    service_b = ResourceRegistrationService(
        db_session,
        user_b_id,
        JobQueueService(db_session),
        upload_root=upload_root,
    )
    from app.services.errors import NotFoundError

    with pytest.raises(NotFoundError):
        service_b.get_object_for_user(result.object_id)


@pytest.fixture
def user_b_id(db_session):
    user_id = uuid4()
    db_session.add(User(id=user_id, display_name="User B"))
    db_session.flush()
    return user_id
