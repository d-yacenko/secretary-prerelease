import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.google.errors import GoogleConfigurationError
from app.connectors.yandex.constants import YANDEX_DISK_PROVIDER, YANDEX_DISK_PUBLIC_RESOURCE_FIELDS
from app.connectors.yandex.credentials import YandexMailAccountStore
from app.connectors.yandex.disk_transport import YandexDiskTransport
from app.connectors.yandex.errors import YandexDiskApiError
from app.db.models import Job, Object
from app.jobs.constants import JOB_TYPE_EMBED_OBJECT, JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT
from app.services.explicit_link_intake_service import build_yandex_explicit_link_intake_service
from app.services.open_target_service import OpenTargetService
from app.users.bootstrap import BOOTSTRAP_USER_ID


class FakeYandexDiskTransport:
    def __init__(
        self,
        responses: dict[str, dict[str, Any]] | None = None,
        default_response: dict[str, Any] | None = None,
    ) -> None:
        self._responses = dict(responses or {})
        self._default_response = default_response
        self.calls: list[str] = []

    def get_public_resource_metadata(self, public_key: str) -> dict[str, Any]:
        self.calls.append(public_key)
        if public_key in self._responses:
            return dict(self._responses[public_key])
        if self._default_response is not None:
            return dict(self._default_response)
        raise YandexDiskApiError(
            "not found",
            operation="get_public_resource_metadata",
            status_code=404,
        )

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


@pytest.fixture
def google_settings(monkeypatch: pytest.MonkeyPatch, oauth_client_file: str, credential_key: str) -> None:
    monkeypatch.setattr("app.core.config.settings.google_oauth_client_file", oauth_client_file)
    monkeypatch.setattr(
        "app.core.config.settings.google_redirect_uri",
        "http://localhost:18080/auth/google/callback",
    )
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _yandex_resource(
    resource_id: str,
    name: str,
    resource_type: str = "file",
    **kwargs: Any,
) -> dict[str, Any]:
    payload = {
        "resource_id": resource_id,
        "name": name,
        "type": resource_type,
        "created": "2024-01-01T12:00:00.000Z",
        "modified": "2024-02-01T12:00:00.000Z",
        "size": 4096,
        "mime_type": "application/pdf",
        "md5": "md5sum",
        "sha256": "sha256sum",
        "revision": "1",
        "path": "/shared/doc",
        "public_url": "https://evil.example/phish",
        "media_type": "document",
    }
    payload.update(kwargs)
    return payload


def _intake_service(
    db_session,
    yandex_transport: FakeYandexDiskTransport,
):
    return build_yandex_explicit_link_intake_service(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        yandex_transport=yandex_transport,
    )


def _extract_jobs_for_object(db_session, object_id: uuid.UUID) -> list[Job]:
    return [
        job
        for job in db_session.scalars(
            select(Job).where(Job.type == JOB_TYPE_EXTRACT_EXPLICIT_RESOURCE_CONTENT)
        ).all()
        if (job.payload or {}).get("object_id") == str(object_id)
    ]


def _embed_jobs_for_object(db_session, object_id: uuid.UUID) -> list[Job]:
    return [
        job
        for job in db_session.scalars(select(Job).where(Job.type == JOB_TYPE_EMBED_OBJECT)).all()
        if (job.payload or {}).get("object_id") == str(object_id)
    ]


def test_disk_yandex_ru_folder_url_creates_one_folder_object(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    share_url = "https://disk.yandex.ru/d/folder-share-key"
    resource_id = "yandex-folder-1"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource(
                resource_id,
                "Shared folder",
                resource_type="dir",
                public_url=share_url,
            )
        }
    )
    service = _intake_service(db_session, transport)
    result = service.intake_link(url=share_url)
    service.close()

    assert result.provider == YANDEX_DISK_PROVIDER
    assert result.kind == "folder"
    assert result.status == "created"
    obj = db_session.get(Object, result.object_id)
    assert obj is not None
    assert obj.external_id == resource_id
    count = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == YANDEX_DISK_PROVIDER,
        )
    )
    assert count == 1


def test_disk_yandex_ru_file_url_creates_file_object(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    share_url = "https://disk.yandex.ru/i/file-share-key"
    resource_id = "yandex-file-1"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource(
                resource_id,
                "Budget.pdf",
                public_url=share_url,
            )
        }
    )
    service = _intake_service(db_session, transport)
    result = service.intake_link(url=share_url)
    service.close()

    assert result.kind == "file"
    obj = db_session.get(Object, result.object_id)
    assert obj is not None
    assert obj.external_id == resource_id


def test_disk_360_yandex_host_accepted(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    share_url = "https://disk.360.yandex.ru/d/360-key"
    resource_id = "360-resource"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource(resource_id, "360 doc", public_url=share_url),
        }
    )
    service = _intake_service(db_session, transport)
    result = service.intake_link(url=share_url)
    service.close()
    assert result.status == "created"


def test_yadi_sk_host_accepted(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    share_url = "https://yadi.sk/i/yadi-key"
    resource_id = "yadi-resource"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource(resource_id, "Yadi file", public_url=share_url),
        }
    )
    service = _intake_service(db_session, transport)
    result = service.intake_link(url=share_url)
    service.close()
    assert result.status == "created"


def test_unknown_host_rejected_before_network(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    transport = FakeYandexDiskTransport()
    service = _intake_service(db_session, transport)
    with pytest.raises(Exception, match="unsupported link url"):
        service.intake_link(url="https://evil.example/d/abc")
    service.close()
    assert transport.calls == []


def test_lookalike_host_rejected(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    transport = FakeYandexDiskTransport()
    service = _intake_service(db_session, transport)
    with pytest.raises(Exception, match="unsupported link url"):
        service.intake_link(url="https://disk.yandex.ru.evil.example/d/abc")
    service.close()
    assert transport.calls == []


def test_userinfo_rejected(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    transport = FakeYandexDiskTransport()
    service = _intake_service(db_session, transport)
    with pytest.raises(Exception, match="unsupported link url"):
        service.intake_link(url="https://user:pass@disk.yandex.ru/d/abc")
    service.close()
    assert transport.calls == []


def test_private_client_link_rejected(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    transport = FakeYandexDiskTransport()
    service = _intake_service(db_session, transport)
    with pytest.raises(Exception, match="yandex disk private link unsupported"):
        service.intake_link(url="https://disk.yandex.ru/client/disk/private-doc")
    service.close()
    assert transport.calls == []


def test_transport_calls_only_public_resources_endpoint(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    share_url = "https://disk.yandex.ru/d/http-key"
    resource_id = "http-resource"
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.host + request.url.path)
        return httpx.Response(
            200,
            json=_yandex_resource(resource_id, "HTTP doc", public_url=share_url),
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    transport = YandexDiskTransport(http_client=http_client)
    service = build_yandex_explicit_link_intake_service(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        yandex_transport=transport,
        http_client=http_client,
    )
    service.intake_link(url=share_url)
    service.close()

    assert requested == ["cloud-api.yandex.net/v1/disk/public/resources"]


def test_full_validated_public_link_passed_as_public_key(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    share_url = "https://disk.yandex.ru/d/public-key-value"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource("rid-1", "Doc", public_url=share_url),
        }
    )
    service = _intake_service(db_session, transport)
    service.intake_link(url=share_url)
    service.close()
    assert transport.calls == [share_url]


def test_explicit_fields_exclude_embedded() -> None:
    assert "_embedded" not in YANDEX_DISK_PUBLIC_RESOURCE_FIELDS


def test_folder_embedded_items_do_not_create_child_objects(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    share_url = "https://disk.yandex.ru/d/folder-with-children"
    resource_id = "folder-parent"
    response = _yandex_resource(
        resource_id,
        "Parent folder",
        resource_type="dir",
        public_url=share_url,
    )
    response["_embedded"] = {
        "items": [
            {"resource_id": "child-1", "name": "child1", "type": "file"},
            {"resource_id": "child-2", "name": "child2", "type": "file"},
        ]
    }
    transport = FakeYandexDiskTransport({share_url: response})
    service = _intake_service(db_session, transport)
    result = service.intake_link(url=share_url)
    service.close()

    count = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == YANDEX_DISK_PROVIDER,
        )
    )
    assert count == 1
    obj = db_session.get(Object, result.object_id)
    assert obj is not None
    assert obj.external_id == resource_id
    assert "_embedded" not in obj.metadata_


def test_repeated_same_resource_id_returns_same_object(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    share_url = "https://disk.yandex.ru/d/repeat-key"
    resource_id = "repeat-resource"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource(resource_id, "Stable", public_url=share_url),
        }
    )
    service = _intake_service(db_session, transport)
    first = service.intake_link(url=share_url)
    second = service.intake_link(url=share_url)
    service.close()
    assert second.object_id == first.object_id
    assert second.status == "unchanged"


def test_different_share_urls_same_resource_id_same_object(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    url_a = "https://disk.yandex.ru/d/key-a"
    url_b = "https://yadi.sk/d/key-b"
    resource_id = "shared-resource-id"
    transport = FakeYandexDiskTransport(
        {
            url_a: _yandex_resource(resource_id, "Doc", public_url=url_a),
            url_b: _yandex_resource(resource_id, "Doc", public_url=url_b),
        }
    )
    service = _intake_service(db_session, transport)
    first = service.intake_link(url=url_a)
    second = service.intake_link(url=url_b)
    service.close()
    assert second.object_id == first.object_id
    count = db_session.scalar(
        select(func.count())
        .select_from(Object)
        .where(
            Object.user_id == BOOTSTRAP_USER_ID,
            Object.provider == YANDEX_DISK_PROVIDER,
            Object.external_id == resource_id,
        )
    )
    assert count == 1


def test_metadata_change_same_object_no_extra_embed(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    share_url = "https://disk.yandex.ru/d/meta-key"
    resource_id = "meta-resource"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource(resource_id, "Same title", public_url=share_url),
        }
    )
    service = _intake_service(db_session, transport)
    first = service.intake_link(url=share_url)

    updated = _yandex_resource(
        resource_id,
        "Same title",
        public_url=share_url,
        size=99999,
        modified="2024-03-01T12:00:00.000Z",
    )
    transport._responses[share_url] = updated
    second = service.intake_link(url=share_url)
    service.close()

    assert second.object_id == first.object_id
    assert second.status == "updated"
    assert len(_extract_jobs_for_object(db_session, first.object_id)) == 1


def test_title_change_same_object_enqueues_embed_once(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    share_url = "https://disk.yandex.ru/d/title-key"
    resource_id = "title-resource"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource(resource_id, "Old title", public_url=share_url),
        }
    )
    service = _intake_service(db_session, transport)
    first = service.intake_link(url=share_url)
    jobs = _extract_jobs_for_object(db_session, first.object_id)
    assert len(jobs) == 1
    jobs[0].status = "done"
    db_session.flush()

    transport._responses[share_url] = _yandex_resource(
        resource_id,
        "New title",
        public_url=share_url,
    )
    second = service.intake_link(url=share_url)
    service.close()

    assert second.object_id == first.object_id
    assert second.status == "updated"
    assert len(_extract_jobs_for_object(db_session, first.object_id)) == 1


def test_malicious_public_url_cannot_control_open_target(db_session) -> None:
    resource_id = "open-target-resource"
    share_url = "https://disk.yandex.ru/d/safe-key"
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        provider=YANDEX_DISK_PROVIDER,
        external_id=resource_id,
        origin="source",
        state="observed",
        title="Doc",
        canonical_uri="https://evil.example/phish",
        metadata_={
            "resource_id": resource_id,
            "public_url": "https://evil.example/phish",
            "intake_url": share_url,
        },
    )
    db_session.add(obj)
    db_session.flush()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is True
    assert target.url == share_url
    assert "evil.example" not in (target.url or "")


def test_external_id_mismatch_makes_open_target_unavailable(db_session) -> None:
    obj = Object(
        user_id=BOOTSTRAP_USER_ID,
        kind="file",
        provider=YANDEX_DISK_PROVIDER,
        external_id="real-id",
        origin="source",
        state="observed",
        title="Doc",
        canonical_uri="https://disk.yandex.ru/d/key",
        metadata_={
            "resource_id": "tampered-id",
            "intake_url": "https://disk.yandex.ru/d/key",
        },
    )
    db_session.add(obj)
    db_session.flush()

    target = OpenTargetService(db_session, BOOTSTRAP_USER_ID).resolve(obj.id)
    assert target.available is False
    assert target.reason == "yandex_disk_metadata_tampered"


def test_yandex_intake_does_not_call_google_transport(
    db_session, credential_key, oauth_client_file, google_settings
) -> None:
    share_url = "https://disk.yandex.ru/d/no-google"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource("rid", "Doc", public_url=share_url),
        }
    )
    service = _intake_service(db_session, transport)
    service.intake_link(url=share_url)
    service.close()
    assert len(transport.calls) == 1


def test_no_yandex_mail_credentials_in_object_or_api(
    db_session, credential_key, oauth_client_file, google_settings, auth_client
) -> None:
    mail_store = YandexMailAccountStore(db_session, CredentialEncryption(credential_key))
    mail_store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        email="mail@yandex.ru",
        app_password="super-secret-app-password",
        imap_host="imap.yandex.ru",
        imap_port=993,
    )
    db_session.flush()

    share_url = "https://disk.yandex.ru/d/cred-check"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource("cred-rid", "Doc", public_url=share_url),
        }
    )
    with patch(
        "app.api.intake.build_yandex_explicit_link_intake_service",
        return_value=_intake_service(
            db_session,
            transport,
        ),
    ):
        response = auth_client.post("/intake/link", json={"url": share_url})

    assert response.status_code == 200
    body = response.json()
    dumped = json.dumps(body).lower()
    assert "super-secret-app-password" not in dumped
    assert "app_password" not in dumped

    obj = db_session.get(Object, uuid.UUID(body["object_id"]))
    assert obj is not None
    meta_dumped = json.dumps(obj.metadata_)
    assert "super-secret-app-password" not in meta_dumped
    assert "app_password" not in meta_dumped


def test_yandex_works_without_credential_key(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", "")
    monkeypatch.setattr("app.core.config.settings.google_oauth_client_file", "")

    share_url = "https://disk.yandex.ru/d/no-credential-key"
    resource_id = "no-cred-resource"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource(resource_id, "Public doc", public_url=share_url),
        }
    )
    service = build_yandex_explicit_link_intake_service(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        yandex_transport=transport,
    )
    result = service.intake_link(url=share_url)
    service.close()

    assert result.status == "created"
    obj = db_session.get(Object, result.object_id)
    assert obj is not None
    assert obj.external_id == resource_id


def test_yandex_works_without_google_oauth_file(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.google_oauth_client_file",
        "/nonexistent/google-oauth-client.json",
    )
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", "")

    share_url = "https://disk.yandex.ru/d/no-oauth-file"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource("oauth-free", "Doc", public_url=share_url),
        }
    )
    service = build_yandex_explicit_link_intake_service(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        yandex_transport=transport,
    )
    result = service.intake_link(url=share_url)
    service.close()
    assert result.status == "created"


def test_yandex_intake_does_not_load_google_oauth_config(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    share_url = "https://disk.yandex.ru/d/no-google-loader"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource("loader-free", "Doc", public_url=share_url),
        }
    )

    def _boom(_client_file: str) -> dict[str, str]:
        raise GoogleConfigurationError("google oauth config loader touched")

    monkeypatch.setattr(
        "app.connectors.google.oauth_config.load_oauth_client_config",
        _boom,
    )

    service = build_yandex_explicit_link_intake_service(
        session=db_session,
        user_id=BOOTSTRAP_USER_ID,
        yandex_transport=transport,
    )
    result = service.intake_link(url=share_url)
    service.close()
    assert result.status == "created"


def test_unsupported_host_rejected_before_provider_build(auth_client, monkeypatch) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", "")

    with patch(
        "app.api.intake.build_yandex_explicit_link_intake_service",
    ) as build_yandex, patch(
        "app.api.intake.build_google_explicit_link_intake_service",
    ) as build_google:
        response = auth_client.post(
            "/intake/link",
            json={"url": "https://evil.example/d/abc"},
        )

    assert response.status_code == 400
    build_yandex.assert_not_called()
    build_google.assert_not_called()


def test_yandex_api_without_credential_key_uses_yandex_builder_only(
    auth_client, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", "")
    monkeypatch.setattr(
        "app.core.config.settings.google_oauth_client_file",
        "/nonexistent/google-oauth-client.json",
    )

    share_url = "https://disk.yandex.ru/d/api-no-cred"
    transport = FakeYandexDiskTransport(
        {
            share_url: _yandex_resource("api-rid", "API doc", public_url=share_url),
        }
    )

    with patch(
        "app.api.intake.build_google_explicit_link_intake_service",
    ) as build_google, patch(
        "app.api.intake.build_yandex_explicit_link_intake_service",
        return_value=build_yandex_explicit_link_intake_service(
            session=db_session,
            user_id=BOOTSTRAP_USER_ID,
            yandex_transport=transport,
        ),
    ) as build_yandex:
        response = auth_client.post("/intake/link", json={"url": share_url})

    assert response.status_code == 200
    build_google.assert_not_called()
    build_yandex.assert_called_once()

