"""PHASE 26B: client intake, attachments, open-target."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.deps import get_db, get_embedding_service
from app.connectors.google.constants import GMAIL_READONLY_SCOPE
from app.connectors.google.credentials import CredentialEncryption, GoogleAccountStore
from app.connectors.google.gmail_normalize import extract_gmail_attachment_descriptors
from app.connectors.google.gmail_sync import build_gmail_sync_service
from app.connectors.yandex.mail_normalize import extract_imap_attachment_descriptors
from app.db.models import Edge, Job, Object, Representation, User
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT, JOB_TYPE_SUMMARIZE_RESOURCE
from app.llm.embedding_service import FakeEmbeddingService
from app.local.client_paths import compute_client_content_revision
from app.local.constants import PROVIDER_LOCAL_DEVICE
from app.main import app
from app.services.correlation_constants import EDGE_TYPE_CONTAINS
from app.services.open_target_service import OpenTargetService
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
def phase26b_client(db_session, auth_headers, tmp_path: Path):
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


def _register_device(client, device_key: str = "desk-26b") -> None:
    resp = client.post(
        "/local/devices/register",
        json={"device_key": device_key, "display_name": "Test desktop"},
    )
    assert resp.status_code == 201


def _revision(
    source_path: str = "/home/user/notes.md",
    size: int = 12,
    modified_at: str = "2026-01-01T10:00:00Z",
    content_hash: str | None = None,
) -> str:
    return compute_client_content_revision(source_path, size, modified_at, content_hash)


def _intake_payload(**overrides) -> dict:
    source_path = overrides.get("source_path", "/home/user/notes.md")
    size = overrides.get("size", 12)
    modified_at = overrides.get("modified_at", "2026-01-01T10:00:00Z")
    content_hash = overrides.get("content_hash")
    base = {
        "device_key": "desk-26b",
        "source_path": source_path,
        "filename": "notes.md",
        "size": size,
        "modified_at": modified_at,
        "content_revision": overrides.get(
            "content_revision",
            _revision(source_path, size, modified_at, content_hash),
        ),
        "representations": [{"kind": "full", "text": "hello world"}],
        "metadata_only": False,
    }
    base.update(overrides)
    if "content_revision" not in overrides:
        base["content_revision"] = _revision(
            base["source_path"], base["size"], base["modified_at"], base.get("content_hash")
        )
    return base


def test_client_intake_accepts_allowed_representations(phase26b_client, db_session) -> None:
    _register_device(phase26b_client)
    resp = phase26b_client.post("/local/files/client-intake", json=_intake_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "created"
    assert body["jobs_enqueued"] == 1
    assert body["representations_created"] == 1

    obj = db_session.get(Object, body["object_id"])
    assert obj is not None
    assert obj.origin == "user"
    assert obj.state == "confirmed"
    assert obj.provider == PROVIDER_LOCAL_DEVICE

    job = db_session.scalar(
        select(Job).where(Job.type == JOB_TYPE_SUMMARIZE_RESOURCE)
    )
    assert job is not None


def test_client_intake_rejects_summary_from_client(phase26b_client) -> None:
    _register_device(phase26b_client)
    payload = _intake_payload(
        representations=[{"kind": "summary", "text": "evil"}]
    )
    resp = phase26b_client.post("/local/files/client-intake", json=payload)
    assert resp.status_code == 422


def test_client_intake_rejects_stale_revision(phase26b_client, db_session) -> None:
    _register_device(phase26b_client)
    first = phase26b_client.post("/local/files/client-intake", json=_intake_payload())
    assert first.status_code == 201

    stale = phase26b_client.post(
        "/local/files/client-intake",
        json=_intake_payload(
            content_revision="rev-old",
            representations=[{"kind": "full", "text": "stale"}],
        ),
    )
    assert stale.status_code == 422
    assert stale.json()["detail"] == "invalid client revision"

    obj = db_session.get(Object, first.json()["object_id"])
    reps = db_session.scalars(
        select(Representation).where(Representation.object_id == obj.id)
    ).all()
    assert len(reps) == 1
    assert reps[0].text == "hello world"


def test_client_intake_rejects_duplicate_part_index(phase26b_client) -> None:
    _register_device(phase26b_client)
    payload = _intake_payload(
        content_revision="rev-chunks",
        representations=[
            {"kind": "chunk", "text": "a", "part_index": 0},
            {"kind": "chunk", "text": "b", "part_index": 0},
        ],
    )
    payload["content_revision"] = _revision()
    resp = phase26b_client.post("/local/files/client-intake", json=payload)
    assert resp.status_code == 422


def test_client_intake_rejects_oversized_payload(phase26b_client) -> None:
    _register_device(phase26b_client)
    huge = "x" * (256 * 1024 + 1)
    payload = _intake_payload(
        representations=[{"kind": "full", "text": huge}],
    )
    resp = phase26b_client.post("/local/files/client-intake", json=payload)
    assert resp.status_code == 422


def test_client_intake_metadata_only_enqueues_embed(phase26b_client, db_session) -> None:
    _register_device(phase26b_client)
    resp = phase26b_client.post(
        "/local/files/client-intake",
        json=_intake_payload(
            filename="report.pdf",
            source_path="/home/user/report.pdf",
            representations=[],
            metadata_only=True,
        ),
    )
    assert resp.status_code == 201
    assert resp.json()["metadata_only"] is True
    job = db_session.scalar(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT))
    assert job is not None
    assert db_session.scalar(
        select(func.count()).select_from(Representation).where(
            Representation.object_id == resp.json()["object_id"]
        )
    ) == 0


def test_client_intake_unchanged_revision_idempotent(phase26b_client, db_session) -> None:
    _register_device(phase26b_client)
    first = phase26b_client.post("/local/files/client-intake", json=_intake_payload())
    second = phase26b_client.post("/local/files/client-intake", json=_intake_payload())
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["status"] == "unchanged"
    assert second.json()["jobs_enqueued"] == 0


def test_client_intake_no_synchronous_llm(phase26b_client) -> None:
    _register_device(phase26b_client)
    with patch("app.llm.openai_summarizer.OpenAISummarizer.summarize") as mock_summarize:
        resp = phase26b_client.post("/local/files/client-intake", json=_intake_payload())
        assert resp.status_code == 201
        mock_summarize.assert_not_called()


def test_open_target_gmail_safe_url(db_session) -> None:
    email = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="email",
        title="Mail",
        origin="source",
        state="observed",
        provider="gmail",
        external_id="msg-1",
        metadata_={"thread_id": "thread-abc"},
    )
    db_session.add(email)
    db_session.flush()
    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(email.id)
    assert target.available
    assert target.action == "web_url"
    assert target.label == "Открыть в Gmail"
    assert target.url == "https://mail.google.com/mail/u/0/#inbox/thread-abc"


def test_open_target_rejects_unsafe_scheme(db_session) -> None:
    page = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="web_page",
        title="Bad",
        origin="source",
        state="observed",
        canonical_uri="javascript:alert(1)",
        metadata_={},
    )
    db_session.add(page)
    db_session.flush()
    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(page.id)
    assert not target.available
    assert target.action == "unavailable"


def test_open_target_local_file_metadata(db_session) -> None:
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="document",
        title="notes.md",
        origin="user",
        state="confirmed",
        provider=PROVIDER_LOCAL_DEVICE,
        external_id="desk:client-source:/notes.md",
        metadata_={
            "device_key": "desk",
            "client_source_path": "/home/user/notes.md",
        },
    )
    db_session.add(obj)
    db_session.flush()
    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available
    assert target.action == "local_file"
    assert target.device_key == "desk"
    assert target.local_path == "/home/user/notes.md"


def test_open_target_wrong_user_404(db_session, phase26b_client) -> None:
    other_id = uuid4()
    db_session.add(User(id=other_id, display_name="other"))
    db_session.flush()
    obj = Object(
        user_id=other_id,
        kind="email",
        title="Private",
        origin="source",
        state="observed",
        provider="gmail",
        external_id="private",
        metadata_={},
    )
    db_session.add(obj)
    db_session.flush()
    resp = phase26b_client.get(f"/objects/{obj.id}/open-target")
    assert resp.status_code == 404


def test_gmail_attachment_descriptors_exclude_body(db_session, oauth_client_file, credential_key) -> None:
    from tests.test_google_oauth import FakeHttpClient, utcnow

    payload = {
        "id": "msg-att",
        "threadId": "thread-att",
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "With attachment"}],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": "SGVsbG8="},
                },
                {
                    "filename": "note.txt",
                    "mimeType": "text/plain",
                    "body": {"attachmentId": "att-1", "size": 5},
                },
            ],
        },
    }
    descriptors = extract_gmail_attachment_descriptors(payload["payload"])
    assert len(descriptors) == 1
    assert descriptors[0]["filename"] == "note.txt"

    account_store = GoogleAccountStore(db_session, CredentialEncryption(credential_key))
    account = account_store.upsert_tokens(
        user_id=BOOTSTRAP_USER_ID,
        email="user@example.com",
        scopes=[GMAIL_READONLY_SCOPE],
        access_token="access-token",
        refresh_token="refresh-token",
        token_expiry=utcnow() + timedelta(hours=1),
    )
    db_session.commit()

    fake_http = FakeHttpClient(
        {
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages"): lambda params, headers: httpx.Response(
                200, json={"messages": [{"id": "msg-att"}]}
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-att"): lambda params, headers: httpx.Response(
                200, json=payload
            ),
            ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages/msg-att/attachments/att-1"): lambda params, headers: httpx.Response(
                200, json={"data": "aGVsbG8="}
            ),
        }
    )
    sync_service = build_gmail_sync_service(
        session=db_session,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        sync_days=30,
        default_limit=50,
        max_limit=100,
        http_client=fake_http,
    )
    sync_service.sync_account(account.id, BOOTSTRAP_USER_ID, limit=1)

    email = db_session.scalar(
        select(Object).where(Object.external_id == "msg-att", Object.kind == "email")
    )
    assert email is not None
    assert email.body == "Hello"

    attachment = db_session.scalar(
        select(Object).where(
            Object.provider == "gmail",
            Object.kind == "file",
            Object.external_id == "gmail:msg-att:att:att-1",
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
    assert edge.origin == "source"
    assert edge.state == "observed"


def test_yandex_imap_attachment_descriptors() -> None:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "Yandex att"
    msg.set_content("Body text")
    msg.add_attachment(b"csv,data", maintype="text", subtype="plain", filename="data.csv")
    descriptors = extract_imap_attachment_descriptors(msg)
    assert len(descriptors) == 1
    assert descriptors[0]["filename"] == "data.csv"
    assert descriptors[0].get("inline_bytes") == b"csv,data"
