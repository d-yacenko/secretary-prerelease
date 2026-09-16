"""PHASE 26B closure corrective regression tests."""

from datetime import timedelta
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db, get_embedding_service
from app.connectors.google.constants import GMAIL_READONLY_SCOPE
from app.connectors.google.credentials import CredentialEncryption, GoogleAccountStore
from app.connectors.google.gmail_normalize import extract_gmail_attachment_descriptors
from app.connectors.yandex.mail_normalize import extract_imap_attachment_descriptors
from app.db.models import Edge, Job, Object, Representation
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT, JOB_TYPE_SUMMARIZE_RESOURCE
from app.llm.embedding_service import FakeEmbeddingService
from app.llm.summarizer import FakeSummarizer
from app.local.client_paths import compute_client_content_revision
from app.local.constants import POLICY_METADATA_ONLY, PROVIDER_LOCAL_DEVICE
from app.main import app
from app.services.client_intake_constants import (
    MAX_CLIENT_INTAKE_REQUEST_BYTES,
    MAX_CLIENT_REPRESENTATION_PART_BYTES,
    MAX_CLIENT_REPRESENTATION_TOTAL_BYTES,
)
from app.services.correlation_constants import EDGE_TYPE_CONTAINS, SEMANTIC_SUMMARY_INPUT_MAX_CHARS
from app.services.email_attachment_service import EmailAttachmentService
from app.services.open_target_service import OpenTargetService
from app.services.semantic_summary_service import SemanticSummaryService
from app.users.bootstrap import BOOTSTRAP_USER_ID


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def oauth_client_file(tmp_path: Path) -> str:
    path = tmp_path / "google-oauth-client.json"
    path.write_text(
        '{"web":{"client_id":"test-client-id","client_secret":"test-secret","redirect_uris":["http://localhost/callback"]}}'
    )
    return str(path)


@pytest.fixture
def closure_client(db_session, auth_headers, tmp_path: Path):
    from tests.conftest import apply_embedding_service_overrides, AuthTestClient

    local_mirror = tmp_path / "local-mirror"
    local_mirror.mkdir()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    apply_embedding_service_overrides(FakeEmbeddingService())
    with (
        patch("app.core.config.settings.local_files_root", str(local_mirror)),
        TestClient(app) as client,
    ):
        yield AuthTestClient(client, auth_headers)
    app.dependency_overrides.clear()


def _register_device(client, device_key: str = "desk-closure") -> None:
    resp = client.post(
        "/local/devices/register",
        json={"device_key": device_key, "display_name": "Closure desktop"},
    )
    assert resp.status_code == 201


def _revision(
    source_path: str,
    size: int,
    modified_at: str,
    content_hash: str | None = None,
) -> str:
    return compute_client_content_revision(source_path, size, modified_at, content_hash)


def _intake(
    client,
    *,
    source_path: str = "/home/user/notes.md",
    filename: str = "notes.md",
    size: int = 12,
    modified_at: str = "2026-01-01T10:00:00Z",
    content_hash: str | None = None,
    content_revision: str | None = None,
    representations: list | None = None,
    metadata_only: bool = False,
    root_path: str | None = None,
    client_absolute_path: str | None = None,
):
    revision = content_revision or _revision(source_path, size, modified_at, content_hash)
    reps = representations if representations is not None else [{"kind": "full", "text": "hello world"}]
    payload = {
        "device_key": "desk-closure",
        "source_path": source_path,
        "filename": filename,
        "size": size,
        "modified_at": modified_at,
        "content_revision": revision,
        "representations": reps,
        "metadata_only": metadata_only,
    }
    if content_hash:
        payload["content_hash"] = content_hash
    if root_path:
        payload["root_path"] = root_path
    if client_absolute_path:
        payload["client_absolute_path"] = client_absolute_path
    return client.post("/local/files/client-intake", json=payload)


def test_changed_revision_queues_summarize(closure_client, db_session) -> None:
    _register_device(closure_client)
    first = _intake(closure_client)
    assert first.status_code == 201
    second = _intake(
        closure_client,
        modified_at="2026-01-02T10:00:00Z",
        representations=[{"kind": "full", "text": "updated body"}],
    )
    assert second.status_code == 201
    body = second.json()
    assert body["status"] == "updated"
    assert body["jobs_enqueued"] == 1
    jobs = db_session.scalars(
        select(Job).where(Job.type == JOB_TYPE_SUMMARIZE_RESOURCE)
    ).all()
    assert len(jobs) >= 1


def test_content_hash_change_same_size_accepted(closure_client) -> None:
    _register_device(closure_client)
    hash_a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    hash_b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    first = _intake(closure_client, content_hash=hash_a)
    second = _intake(
        closure_client,
        content_hash=hash_b,
        representations=[{"kind": "full", "text": "new hash content"}],
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["status"] == "updated"


def test_unchanged_intake_zero_jobs(closure_client) -> None:
    _register_device(closure_client)
    first = _intake(closure_client)
    second = _intake(closure_client)
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["status"] == "unchanged"
    assert second.json()["jobs_enqueued"] == 0


def test_metadata_only_to_indexed_same_revision_summarize(closure_client, db_session) -> None:
    _register_device(closure_client)
    source = "/home/user/doc.txt"
    modified = "2026-01-01T10:00:00Z"
    rev = _revision(source, 12, modified)
    meta = _intake(
        closure_client,
        source_path=source,
        filename="doc.txt",
        representations=[],
        metadata_only=True,
        content_revision=rev,
    )
    assert meta.status_code == 201
    indexed = _intake(
        closure_client,
        source_path=source,
        filename="doc.txt",
        content_revision=rev,
        metadata_only=False,
        representations=[{"kind": "full", "text": "now indexed"}],
    )
    assert indexed.status_code == 201
    assert indexed.json()["jobs_enqueued"] == 1


def test_indexed_to_metadata_only_privacy(closure_client, db_session) -> None:
    _register_device(closure_client)
    indexed = _intake(closure_client)
    assert indexed.status_code == 201
    obj_id = indexed.json()["object_id"]
    downgrade = _intake(
        closure_client,
        filename="notes.md",
        representations=[],
        metadata_only=True,
    )
    assert downgrade.status_code == 201
    assert downgrade.json()["status"] == "updated"
    obj = db_session.get(Object, obj_id)
    assert obj is not None
    assert obj.metadata_["indexing_policy"] == POLICY_METADATA_ONLY
    assert obj.embedding is None
    assert "semantic_summary" not in obj.metadata_
    reps = db_session.scalars(
        select(Representation).where(Representation.object_id == obj_id)
    ).all()
    assert reps == []
    embed_jobs = db_session.scalars(
        select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)
    ).all()
    assert any(job.payload.get("object_id") == str(obj_id) for job in embed_jobs)


def test_metadata_only_with_reps_rejected(closure_client) -> None:
    _register_device(closure_client)
    resp = _intake(
        closure_client,
        metadata_only=True,
        representations=[{"kind": "full", "text": "bad"}],
    )
    assert resp.status_code == 422


def test_invalid_client_revision(closure_client) -> None:
    _register_device(closure_client)
    resp = _intake(closure_client, content_revision="not-a-valid-revision")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid client revision"


def test_registered_at_preserved(closure_client, db_session) -> None:
    _register_device(closure_client)
    first = _intake(closure_client)
    obj_id = first.json()["object_id"]
    obj = db_session.get(Object, obj_id)
    registered = obj.metadata_["registered_at"]
    second = _intake(
        closure_client,
        modified_at="2026-01-02T10:00:00Z",
        representations=[{"kind": "full", "text": "changed"}],
    )
    assert second.status_code == 201
    obj = db_session.get(Object, obj_id)
    assert obj.metadata_["registered_at"] == registered


def test_request_body_envelope_413(closure_client) -> None:
    _register_device(closure_client)
    oversized = b"x" * (MAX_CLIENT_INTAKE_REQUEST_BYTES + 1)
    resp = closure_client.post(
        "/local/files/client-intake",
        content=oversized,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 413


def test_representation_bounds_422(closure_client) -> None:
    _register_device(closure_client)
    too_many = [{"kind": "chunk", "text": "a", "part_index": i} for i in range(65)]
    resp = _intake(closure_client, representations=too_many)
    assert resp.status_code == 422

    big = "x" * (MAX_CLIENT_REPRESENTATION_PART_BYTES + 1)
    resp = _intake(closure_client, representations=[{"kind": "full", "text": big}])
    assert resp.status_code == 422

    total = "x" * (MAX_CLIENT_REPRESENTATION_TOTAL_BYTES // 2 + 1)
    resp = _intake(
        closure_client,
        representations=[
            {"kind": "chunk", "text": total, "part_index": 0},
            {"kind": "chunk", "text": total, "part_index": 1},
        ],
    )
    assert resp.status_code == 422


def test_representation_policy_pdf_full_accepted(closure_client) -> None:
    _register_device(closure_client)
    resp = _intake(
        closure_client,
        filename="doc.pdf",
        source_path="/home/user/doc.pdf",
        representations=[{"kind": "full", "text": "fake pdf text"}],
    )
    assert resp.status_code == 201


def test_representation_policy_csv_full_accepted(closure_client) -> None:
    _register_device(closure_client)
    resp = _intake(
        closure_client,
        filename="data.csv",
        source_path="/home/user/data.csv",
        representations=[
            {"kind": "schema", "text": "columns: a"},
            {"kind": "sample", "text": "sample"},
            {"kind": "statistics", "text": "rows: 1"},
            {"kind": "full", "text": "a\n1"},
        ],
    )
    assert resp.status_code == 201


def test_representation_policy_txt_schema_rejected(closure_client) -> None:
    _register_device(closure_client)
    resp = _intake(
        closure_client,
        representations=[{"kind": "schema", "text": "columns: a"}],
    )
    assert resp.status_code == 422


def test_csv_duplicate_schema_rejected(closure_client) -> None:
    _register_device(closure_client)
    reps = [
        {"kind": "schema", "text": "columns: a"},
        {"kind": "schema", "text": "columns: b"},
        {"kind": "sample", "text": "1"},
        {"kind": "statistics", "text": "rows: 1"},
    ]
    resp = _intake(
        closure_client,
        filename="data.csv",
        source_path="/home/user/data.csv",
        representations=reps,
    )
    assert resp.status_code == 422


def test_dataset_summary_input_bounded(closure_client, db_session) -> None:
    _register_device(closure_client)
    schema = "columns: " + ",".join(f"c{i}" for i in range(100))
    sample = "\n".join(["x" * 500 for _ in range(20)])
    stats = "\n".join([f"column c{i}: type=text" for i in range(100)])
    resp = _intake(
        closure_client,
        filename="big.csv",
        source_path="/home/user/big.csv",
        representations=[
            {"kind": "schema", "text": schema},
            {"kind": "sample", "text": sample},
            {"kind": "statistics", "text": stats},
        ],
    )
    assert resp.status_code == 201
    obj = db_session.get(Object, resp.json()["object_id"])
    reps = db_session.scalars(
        select(Representation).where(Representation.object_id == obj.id)
    ).all()
    recorder = FakeSummarizer(max_chars=4000)
    service = SemanticSummaryService(db_session, BOOTSTRAP_USER_ID, summarizer=recorder)
    input_text = service._build_summary_input(obj, list(reps))
    assert len(input_text) <= 4000


def test_gmail_known_oversized_skips_fetch(
    db_session, oauth_client_file, credential_key
) -> None:
    from tests.test_google_oauth import utcnow

    payload = {
        "id": "msg-big",
        "threadId": "thread-big",
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "Big att"}],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": "SGVsbG8="}},
                {
                    "filename": "huge.bin",
                    "mimeType": "application/octet-stream",
                    "body": {"attachmentId": "att-big", "size": 11 * 1024 * 1024},
                },
            ],
        },
    }
    fetch_calls = 0

    def fetch_attachment(_desc):
        nonlocal fetch_calls
        fetch_calls += 1
        return b"data"

    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    email = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        title="Mail",
        origin="source",
        state="observed",
        provider="gmail",
        external_id="msg-big",
        metadata_={},
    )
    db_session.add(email)
    db_session.flush()
    descriptors = extract_gmail_attachment_descriptors(payload["payload"])
    EmailAttachmentService(db_session, BOOTSTRAP_USER_ID).materialize_gmail_attachments(
        email, descriptors, fetch_attachment
    )
    assert fetch_calls == 0


def test_gmail_inline_body_attachment_materialized(db_session) -> None:
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": "SGVsbG8="}},
            {
                "filename": "inline.txt",
                "mimeType": "text/plain",
                "partId": "1",
                "body": {"data": "aGVsbG8="},
            },
        ],
    }
    descriptors = extract_gmail_attachment_descriptors(payload)
    assert len(descriptors) == 1
    assert descriptors[0].get("inline_bytes") == b"hello"


def test_gmail_cumulative_budget(db_session, oauth_client_file, credential_key) -> None:

    email = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        title="Mail",
        origin="source",
        state="observed",
        provider="gmail",
        external_id="msg-budget",
        metadata_={},
    )
    db_session.add(email)
    db_session.flush()

    chunk = b"x" * (8 * 1024 * 1024)
    descriptors = [
        {
            "attachment_key": "a1",
            "attachment_id": "a1",
            "filename": "one.txt",
            "mime_type": "text/plain",
            "size": len(chunk),
        },
        {
            "attachment_key": "a2",
            "attachment_id": "a2",
            "filename": "two.txt",
            "mime_type": "text/plain",
            "size": len(chunk),
        },
        {
            "attachment_key": "a3",
            "attachment_id": "a3",
            "filename": "three.txt",
            "mime_type": "text/plain",
            "size": len(chunk),
        },
    ]

    fetch_count = 0

    def fetch_bytes(desc):
        nonlocal fetch_count
        fetch_count += 1
        return chunk

    EmailAttachmentService(db_session, BOOTSTRAP_USER_ID).materialize_gmail_attachments(
        email, descriptors, fetch_bytes
    )
    assert fetch_count <= 2
    indexed_objects = db_session.scalars(
        select(Object).where(
            Object.provider == "gmail",
            Object.external_id.like("gmail:msg-budget:att:%"),
            Object.id.in_(
                select(Representation.object_id).where(
                    Representation.kind.in_(("full", "chunk", "schema", "sample", "statistics"))
                )
            ),
        )
    ).all()
    assert len(indexed_objects) <= 2


def test_gmail_attachment_rerun_idempotent(db_session) -> None:
    email = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        title="Mail",
        origin="source",
        state="observed",
        provider="gmail",
        external_id="msg-rerun",
        metadata_={},
    )
    db_session.add(email)
    db_session.flush()
    data = b"hello world"
    descriptors = [
        {
            "attachment_key": "att-1",
            "attachment_id": "att-1",
            "filename": "note.txt",
            "mime_type": "text/plain",
            "size": len(data),
            "inline_bytes": data,
        },
    ]

    def fetch_bytes(_desc):
        return data

    service = EmailAttachmentService(db_session, BOOTSTRAP_USER_ID)
    service.materialize_gmail_attachments(email, descriptors, fetch_bytes)
    jobs_first = db_session.scalars(select(Job)).all()
    service.materialize_gmail_attachments(email, descriptors, fetch_bytes)
    jobs_second = db_session.scalars(select(Job)).all()
    assert len(jobs_second) == len(jobs_first)


def test_yandex_many_attachments_bounded() -> None:
    msg = EmailMessage()
    msg["Subject"] = "Many"
    msg.set_content("Body")
    for i in range(25):
        msg.add_attachment(
            f"data{i}".encode(),
            maintype="text",
            subtype="plain",
            filename=f"f{i}.txt",
        )
    descriptors = extract_imap_attachment_descriptors(msg)
    assert len(descriptors) <= 20


def test_yandex_oversized_not_retained() -> None:
    msg = EmailMessage()
    msg["Subject"] = "Huge"
    msg.set_content("Body")
    msg.add_attachment(b"x" * (11 * 1024 * 1024), maintype="application", subtype="octet-stream")
    descriptors = extract_imap_attachment_descriptors(msg)
    assert len(descriptors) == 1
    assert "inline_bytes" not in descriptors[0]


def test_yandex_materialization_contains_edge(db_session) -> None:
    email = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        title="Yandex mail",
        origin="source",
        state="observed",
        provider="yandex_mail",
        external_id="uid-1",
        metadata_={},
    )
    db_session.add(email)
    db_session.flush()
    descriptors = [
        {
            "part_key": "part-0",
            "filename": "data.csv",
            "mime_type": "text/csv",
            "size": 7,
            "inline_bytes": b"a,b\n1,2",
        },
    ]
    EmailAttachmentService(db_session, BOOTSTRAP_USER_ID).materialize_yandex_attachments(
        email, descriptors
    )
    attachment = db_session.scalar(
        select(Object).where(
            Object.provider == "yandex_mail",
            Object.external_id == "yandex_mail:uid-1:att:part-0",
        )
    )
    assert attachment is not None
    edge = db_session.scalar(
        select(Edge).where(
            Edge.source_id == email.id,
            Edge.target_id == attachment.id,
            Edge.type == EDGE_TYPE_CONTAINS,
        )
    )
    assert edge is not None


def test_open_target_bare_relative_unavailable(db_session) -> None:
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        title="foo.pdf",
        origin="user",
        state="confirmed",
        provider=PROVIDER_LOCAL_DEVICE,
        external_id="desk:local:docs/foo.pdf",
        metadata_={
            "device_key": "desk",
            "local_relative_path": "docs/foo.pdf",
            "local_root_path": "home/user/docs",
        },
    )
    db_session.add(obj)
    db_session.flush()
    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert not target.available
    assert target.reason == "client_source_path_missing"


def test_folder_client_source_path_on_register(closure_client, db_session) -> None:
    _register_device(closure_client)
    resp = closure_client.post(
        "/local/roots/register",
        json={
            "device_key": "desk-closure",
            "root_path": "home/user/docs",
            "default_policy": "metadata_only",
            "client_source_path": "/home/user/docs",
        },
    )
    assert resp.status_code == 201
    folder = db_session.scalar(
        select(Object).where(
            Object.provider == PROVIDER_LOCAL_DEVICE,
            Object.kind == "folder",
        )
    )
    assert folder is not None
    assert folder.metadata_["client_source_path"] == "/home/user/docs"
    assert folder.metadata_["local_root_path"] == "home/user/docs"


def test_dataset_summary_input_hard_cap_when_schema_exceeds_limit(db_session) -> None:
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="dataset",
        title="big.csv",
        origin="user",
        state="confirmed",
        provider=PROVIDER_LOCAL_DEVICE,
        external_id="closure:dataset-cap",
        metadata_={},
    )
    db_session.add(obj)
    db_session.flush()
    schema = "columns: " + "x" * 5000
    stats = "\n".join([f"column c{i}: type=text" for i in range(200)])
    sample = "\n".join(["sample-row " * 40 for _ in range(20)])
    reps = [
        Representation(object_id=obj.id, kind="schema", text=schema, metadata_={}),
        Representation(object_id=obj.id, kind="statistics", text=stats, metadata_={}),
        Representation(object_id=obj.id, kind="sample", text=sample, metadata_={}),
    ]
    service = SemanticSummaryService(db_session, BOOTSTRAP_USER_ID)
    input_text = service._build_summary_input(obj, reps)
    assert len(input_text) <= SEMANTIC_SUMMARY_INPUT_MAX_CHARS


def test_indexed_intake_empty_representations_rejected(closure_client) -> None:
    _register_device(closure_client)
    resp = _intake(
        closure_client,
        representations=[],
        metadata_only=False,
    )
    assert resp.status_code == 422
    assert "mechanical" in resp.json()["detail"].lower()


def test_indexed_pdf_requires_representations(closure_client) -> None:
    _register_device(closure_client)
    resp = _intake(
        closure_client,
        source_path="/home/user/doc.pdf",
        filename="doc.pdf",
        representations=[],
        metadata_only=False,
    )
    assert resp.status_code == 422
    assert "representations" in resp.json()["detail"].lower()


def test_indexed_parquet_requires_representations(closure_client) -> None:
    _register_device(closure_client)
    resp = _intake(
        closure_client,
        source_path="/home/user/data.parquet",
        filename="data.parquet",
        representations=[],
        metadata_only=False,
    )
    assert resp.status_code == 422
    assert "representations" in resp.json()["detail"].lower()


def test_indexed_unknown_bin_requires_metadata_only(closure_client) -> None:
    _register_device(closure_client)
    resp = _intake(
        closure_client,
        source_path="/home/user/data.bin",
        filename="data.bin",
        representations=[],
        metadata_only=False,
    )
    assert resp.status_code == 422
    assert "metadata_only" in resp.json()["detail"].lower()


def test_metadata_only_pdf_accepted_without_representations(closure_client) -> None:
    _register_device(closure_client)
    resp = _intake(
        closure_client,
        source_path="/home/user/doc.pdf",
        filename="doc.pdf",
        representations=[],
        metadata_only=True,
    )
    assert resp.status_code == 201
    assert resp.json()["metadata_only"] is True
