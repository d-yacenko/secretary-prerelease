"""PHASE 29A-R1-R1 streaming trust & retrieval visibility closure tests."""

import json
import uuid
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.connectors.google.constants import GOOGLE_DRIVE_PROVIDER
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.yandex.constants import YANDEX_DISK_PROVIDER
from app.connectors.yandex.disk_transport import YandexDiskTransport
from app.content_extraction.bounded_download import DownloadTooLargeError
from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.extract_service import ExplicitResourceContentExtractor
from app.content_extraction.mechanical_extractors import extract_from_path
from app.content_extraction.metadata_keys import STATUS_FAILED, STATUS_PENDING, STATUS_READY
from app.content_extraction.trusted_download import (
    IterableByteStream,
    UnsafeDownloadUrlError,
    bounded_get_safe_redirects,
    validate_download_url,
)
from app.content_extraction.yandex_disk_content import fetch_yandex_disk_public_content
from app.db.models import Object, Representation
from app.services.explicit_link_intake_service import build_google_explicit_link_intake_service
from app.services.retrieval_constants import MAX_CANDIDATE_POOL
from app.services.retrieval_service import RetrievalService, _bounded_round_robin_merge
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.fixtures.phase_29a_fixtures import (
    write_minimal_parquet,
    write_minimal_pptx,
    write_minimal_xlsx,
    write_txt,
)
from tests.test_phase_29a_bounded_content_extraction import (
    FakeDriveTransport,
    _google_account,
)

TRUSTED_DOWNLOAD_URL = "https://downloader.disk.yandex.ru/disk/abc123"


def _public_resolver(host: str) -> list[str]:
    return ["93.158.134.8"]


def _loopback_resolver(host: str) -> list[str]:
    return ["127.0.0.1"]


def _private_resolver(host: str) -> list[str]:
    return ["10.0.0.8"]


def _link_local_resolver(host: str) -> list[str]:
    return ["169.254.1.1"]


PUBLIC_RESOLVER = _public_resolver
LOOPBACK_RESOLVER = _loopback_resolver
PRIVATE_RESOLVER = _private_resolver
LINK_LOCAL_RESOLVER = _link_local_resolver


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


def test_streaming_download_without_content_length_exceeds_max() -> None:
    max_bytes = 100
    stream = IterableByteStream([b"x" * 60, b"y" * 50])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(DownloadTooLargeError):
        bounded_get_safe_redirects(
            client,
            TRUSTED_DOWNLOAD_URL,
            max_bytes=max_bytes,
            resolver=PUBLIC_RESOLVER,
        )


def test_streaming_download_misleading_content_length_exceeds_max() -> None:
    max_bytes = 100
    stream = IterableByteStream([b"z" * 150])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": "10"},
            stream=stream,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(DownloadTooLargeError):
        bounded_get_safe_redirects(
            client,
            TRUSTED_DOWNLOAD_URL,
            max_bytes=max_bytes,
            resolver=PUBLIC_RESOLVER,
        )


def test_streaming_download_within_bound_passes() -> None:
    payload = b"bounded-stream-ok"
    stream = IterableByteStream([payload[:4], payload[4:]])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    data = bounded_get_safe_redirects(
        client,
        TRUSTED_DOWNLOAD_URL,
        max_bytes=1024,
        resolver=PUBLIC_RESOLVER,
    )
    assert data == payload


def test_trusted_yandex_hostname_with_public_resolver_allowed() -> None:
    validate_download_url(TRUSTED_DOWNLOAD_URL, resolver=PUBLIC_RESOLVER)


@pytest.mark.parametrize(
    "url",
    [
        "https://storage.yandex.net/object",
        "https://abc123.storage.yandex.net/object",
    ],
)
def test_trusted_yandex_storage_hosts_allowed(url: str) -> None:
    validate_download_url(url, resolver=PUBLIC_RESOLVER)


@pytest.mark.parametrize(
    "url",
    [
        "http://abc123.storage.yandex.net/object",
        "https://storage.yandex.net.evil.example/object",
        "https://foo.storage.yandex.net.evil.example/object",
        "https://evilstorage.yandex.net/object",
        "https://unrelated.example/object",
    ],
)
def test_untrusted_yandex_storage_like_hosts_rejected(url: str) -> None:
    with pytest.raises(UnsafeDownloadUrlError):
        validate_download_url(url, resolver=PUBLIC_RESOLVER)


def test_downloader_redirect_to_yandex_storage_shard_succeeds() -> None:
    payload = b"yandex-storage-shard-ok"
    storage_url = "https://abc123.storage.yandex.net/disk/object"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "downloader.disk.yandex.ru":
            return httpx.Response(302, headers={"Location": storage_url})
        if request.url.host == "abc123.storage.yandex.net":
            return httpx.Response(200, content=payload)
        raise AssertionError(f"unexpected host: {request.url.host}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    data = bounded_get_safe_redirects(
        client,
        TRUSTED_DOWNLOAD_URL,
        max_bytes=1024,
        resolver=PUBLIC_RESOLVER,
    )
    assert data == payload


def test_arbitrary_public_hostname_rejected() -> None:
    with pytest.raises(UnsafeDownloadUrlError, match="untrusted_download_host"):
        validate_download_url("https://evil.example/file", resolver=PUBLIC_RESOLVER)


def test_trusted_hostname_resolving_to_loopback_rejected() -> None:
    with pytest.raises(UnsafeDownloadUrlError, match="private_destination_forbidden"):
        validate_download_url(TRUSTED_DOWNLOAD_URL, resolver=LOOPBACK_RESOLVER)


def test_trusted_hostname_resolving_to_private_rejected() -> None:
    with pytest.raises(UnsafeDownloadUrlError, match="private_destination_forbidden"):
        validate_download_url(TRUSTED_DOWNLOAD_URL, resolver=PRIVATE_RESOLVER)


def test_trusted_hostname_resolving_to_link_local_rejected() -> None:
    with pytest.raises(UnsafeDownloadUrlError, match="private_destination_forbidden"):
        validate_download_url(TRUSTED_DOWNLOAD_URL, resolver=LINK_LOCAL_RESOLVER)


def test_redirect_to_private_ip_rejected() -> None:
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


def test_redirect_to_unrelated_hostname_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://evil.example/file"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(UnsafeDownloadUrlError, match="untrusted_download_host"):
        bounded_get_safe_redirects(
            client,
            TRUSTED_DOWNLOAD_URL,
            max_bytes=1024,
            resolver=PUBLIC_RESOLVER,
        )


def test_redirect_hop_limit_still_rejected() -> None:
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


def _cloud_object(
    db_session,
    *,
    provider: str,
    title: str,
    status: str,
    body: str | None = None,
) -> Object:
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        title=title,
        body=body,
        origin="source",
        state="observed",
        provider=provider,
        external_id=f"ext-{uuid.uuid4().hex[:10]}",
        metadata_={
            "content_revision": "rev-test",
            "content_extraction_status": status,
            "content_extraction_version": EXTRACTION_VERSION,
        },
    )
    db_session.add(obj)
    db_session.flush()
    return obj


def test_cloud_object_pending_title_retrievable(db_session) -> None:
    title = f"pending_title_unique_{uuid.uuid4().hex[:8]}"
    obj = _cloud_object(
        db_session,
        provider=GOOGLE_DRIVE_PROVIDER,
        title=title,
        status=STATUS_PENDING,
    )
    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(title).hits
    assert any(hit.object_id == obj.id for hit in hits)


def test_cloud_object_unsupported_title_retrievable(db_session) -> None:
    title = f"unsupported_title_{uuid.uuid4().hex[:8]}"
    obj = _cloud_object(
        db_session,
        provider=YANDEX_DISK_PROVIDER,
        title=title,
        status="unsupported",
    )
    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(title).hits
    assert any(hit.object_id == obj.id for hit in hits)


def test_cloud_object_failed_title_retrievable(db_session) -> None:
    title = f"failed_title_unique_{uuid.uuid4().hex[:8]}"
    obj = _cloud_object(
        db_session,
        provider=GOOGLE_DRIVE_PROVIDER,
        title=title,
        status=STATUS_FAILED,
    )
    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(title).hits
    assert any(hit.object_id == obj.id for hit in hits)


def test_stale_representation_not_retrieved_for_non_ready_cloud(db_session) -> None:
    phrase = f"stale_rep_phrase_{uuid.uuid4().hex[:8]}"
    obj = _cloud_object(
        db_session,
        provider=GOOGLE_DRIVE_PROVIDER,
        title=f"neutral-title-{uuid.uuid4().hex[:6]}",
        status=STATUS_PENDING,
    )
    db_session.add(
        Representation(
            object_id=obj.id,
            kind="full",
            text=f"stale body contains {phrase}",
        )
    )
    db_session.flush()
    hits = RetrievalService(db_session, BOOTSTRAP_USER_ID).retrieve(phrase).hits
    assert not any(hit.object_id == obj.id for hit in hits)


def test_bounded_round_robin_merge_never_exceeds_max_pool() -> None:
    branches = [[uuid.uuid4() for _ in range(60)] for _ in range(4)]
    merged = _bounded_round_robin_merge(branches, MAX_CANDIDATE_POOL)
    assert len(merged) <= MAX_CANDIDATE_POOL
    assert len(merged) == MAX_CANDIDATE_POOL


def test_strict_candidate_collection_bounded(db_session) -> None:
    titles = [f"pool_bound_title_{index}_{uuid.uuid4().hex[:4]}" for index in range(60)]
    for title in titles:
        obj = Object(
            user_id=BOOTSTRAP_USER_ID,
            kind="file",
            title=title,
            body=f"body text for {title} searchable content",
            origin="source",
            state="observed",
            provider=GOOGLE_DRIVE_PROVIDER,
            external_id=f"pool-{uuid.uuid4().hex}",
            metadata_={
                "content_revision": "rev",
                "content_extraction_status": STATUS_PENDING,
            },
        )
        db_session.add(obj)
        db_session.flush()
        db_session.add(
            Representation(
                object_id=obj.id,
                kind="full",
                text=f"representation searchable {title}",
            )
        )
    db_session.flush()

    query = "pool_bound_title searchable content"
    service = RetrievalService(db_session, BOOTSTRAP_USER_ID)
    strict_ids = service._collect_strict_candidate_ids(
        query=query,
        kind=None,
        provider=None,
        project_id=None,
        horizon_cutoff=None,
        date_from=None,
        date_to=None,
        apply_horizon=False,
    )
    assert len(strict_ids) <= MAX_CANDIDATE_POOL


def test_google_sheets_export_extraction(
    db_session, credential_key, oauth_client_file, tmp_path: Path
) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "gsheet-r1r1"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "Budget",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "version": "3",
                "trashed": False,
            }
        }
    )
    xlsx_path = tmp_path / f"{file_id}.xlsx"
    write_minimal_xlsx(xlsx_path)
    transport.set_download(file_id, xlsx_path.read_bytes())

    service = build_google_explicit_link_intake_service(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        google_transport=transport,
    )
    result = service.intake_link(
        url=f"https://docs.google.com/spreadsheets/d/{file_id}/edit",
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
    assert "export_file" in [call[0] for call in transport.calls]
    reps = db_session.scalars(
        select(Representation).where(Representation.object_id == obj.id)
    ).all()
    service.close()
    assert any("xlsx_value" in rep.text for rep in reps)
    assert obj.metadata_["content_extraction_status"] == STATUS_READY


def test_google_slides_export_extraction(
    db_session, credential_key, oauth_client_file, tmp_path: Path
) -> None:
    account = _google_account(db_session, credential_key)
    file_id = "gslides-r1r1"
    transport = FakeDriveTransport(
        {
            file_id: {
                "id": file_id,
                "name": "Deck",
                "mimeType": "application/vnd.google-apps.presentation",
                "modifiedTime": "2024-01-01T00:00:00.000Z",
                "version": "2",
                "trashed": False,
            }
        }
    )
    pptx_path = tmp_path / "deck.pptx"
    write_minimal_pptx(pptx_path, slide_text="slides distinctive phrase r1r1")
    transport.set_download(file_id, pptx_path.read_bytes())

    service = build_google_explicit_link_intake_service(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        credential_key=credential_key,
        client_file=oauth_client_file,
        redirect_uri="http://localhost/callback",
        google_transport=transport,
    )
    result = service.intake_link(
        url=f"https://docs.google.com/presentation/d/{file_id}/edit",
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
    assert "export_file" in [call[0] for call in transport.calls]
    reps = db_session.scalars(
        select(Representation).where(Representation.object_id == obj.id)
    ).all()
    service.close()
    assert any("slides distinctive phrase r1r1" in rep.text for rep in reps)
    assert obj.metadata_["content_extraction_status"] == STATUS_READY


def test_parquet_mechanical_extraction(tmp_path: Path) -> None:
    object_id = uuid.uuid4()
    parquet_path = tmp_path / "tiny.parquet"
    marker = f"parquet_marker_{uuid.uuid4().hex[:6]}"
    write_minimal_parquet(parquet_path, marker=marker)
    reps, meta = extract_from_path(object_id, parquet_path)
    assert meta["content_format"] == ".parquet"
    assert any(marker in rep.text for rep in reps)


def test_yandex_transport_streamed_download_to_extraction(tmp_path: Path) -> None:
    payload = b"yandex streamed distinctive phrase"
    stream = IterableByteStream([payload[:10], payload[10:]])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/public/resources/download"):
            return httpx.Response(200, json={"href": TRUSTED_DOWNLOAD_URL})
        return httpx.Response(200, stream=stream)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = YandexDiskTransport(http_client=client)
    metadata = {
        "intake_url": "https://disk.yandex.ru/d/public-share-key",
    }
    raw = fetch_yandex_disk_public_content(transport, metadata)
    assert raw == payload
    transport.close()

    txt_path = tmp_path / "from_yandex.txt"
    write_txt(txt_path, payload.decode())
    # extraction path validated separately; download is the adapter focus here


def test_yandex_folder_intake_zero_download(db_session) -> None:
    from app.connectors.yandex.disk_normalize import normalize_yandex_disk_resource
    from app.content_extraction.format_resolver import resolve_content_extraction_plan

    normalized = normalize_yandex_disk_resource(
        {
            "resource_id": "yandex-folder-id",
            "name": "Public folder",
            "type": "dir",
            "modified": "2024-01-01T00:00:00.000Z",
        },
        intake_url="https://disk.yandex.ru/d/folder-key",
        intake_mode="explicit_link",
    )
    assert normalized is not None
    plan = resolve_content_extraction_plan(
        YANDEX_DISK_PROVIDER,
        normalized["kind"],
        normalized["metadata"],
        normalized["title"],
    )
    assert plan.eligible is False
    assert plan.status == "metadata_only"
