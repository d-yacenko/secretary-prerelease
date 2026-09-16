"""Trusted source navigation targets for objects."""

from dataclasses import dataclass
from urllib.parse import quote, urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google.constants import GOOGLE_DRIVE_PROVIDER
from app.connectors.google.drive_normalize import build_canonical_uri
from app.connectors.mattermost.errors import MattermostSecurityError
from app.connectors.mattermost.normalize import (
    build_external_id,
    normalize_server_url,
    parse_allowed_base_urls,
)
from app.connectors.yandex.constants import YANDEX_DISK_PROVIDER
from app.connectors.yandex.disk_url_parser import (
    is_valid_yandex_disk_share_url,
    parse_yandex_disk_share_url,
)
from app.core.config import settings
from app.db.models import GoogleAccount, MattermostAccount, Object
from app.domain.object_visibility import is_object_hidden_from_active_reads
from app.local.constants import PROVIDER_LOCAL_DEVICE
from app.services.errors import NotFoundError

_SAFE_WEB_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class OpenTarget:
    available: bool
    action: str
    label: str
    url: str | None = None
    device_key: str | None = None
    local_path: str | None = None
    reason: str | None = None


class OpenTargetService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id

    def resolve(self, object_id: UUID) -> OpenTarget:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None or is_object_hidden_from_active_reads(obj):
            raise NotFoundError("object", object_id)

        provider = (obj.provider or "").lower()
        meta = obj.metadata_ or {}

        if provider == "gmail" and obj.kind == "email":
            return self._gmail_target(obj, meta)
        if provider in {"yandex_mail", "yandex"} and obj.kind == "email":
            return self._yandex_mail_target(obj, meta)
        if provider in {"google_calendar", "google"} and obj.kind in {"event", "calendar_event"}:
            return self._calendar_target(obj, meta)
        if provider == "mattermost" and obj.kind == "chat_message":
            return self._mattermost_target(obj, meta)
        if provider == GOOGLE_DRIVE_PROVIDER and obj.kind in {"file", "folder"}:
            return self._google_drive_target(obj, meta)
        if provider == YANDEX_DISK_PROVIDER and obj.kind in {"file", "folder"}:
            return self._yandex_disk_target(obj, meta)
        if obj.kind == "web_page":
            return self._web_target(obj)
        if provider == PROVIDER_LOCAL_DEVICE:
            return self._local_device_target(obj, meta)
        if obj.kind == "file" and provider in {"gmail", "yandex_mail"}:
            return self._attachment_target(obj, meta)
        if obj.canonical_uri and self._is_safe_web_url(obj.canonical_uri):
            return OpenTarget(
                available=True,
                action="web_url",
                label="Открыть страницу",
                url=obj.canonical_uri,
            )
        return OpenTarget(
            available=False,
            action="unavailable",
            label="Открыть в источнике",
            reason="no_trusted_open_target",
        )

    def _gmail_target(self, obj: Object, meta: dict) -> OpenTarget:
        thread_id = meta.get("thread_id")
        if thread_id:
            url = f"https://mail.google.com/mail/u/0/#inbox/{thread_id}"
            return OpenTarget(
                available=True,
                action="web_url",
                label="Открыть в Gmail",
                url=url,
            )
        message_id = meta.get("message_id")
        if message_id:
            url = f"https://mail.google.com/mail/u/0/#all/{message_id}"
            return OpenTarget(
                available=True,
                action="web_url",
                label="Открыть в Gmail",
                url=url,
            )
        return OpenTarget(
            available=True,
            action="web_url",
            label="Открыть в Gmail",
            url="https://mail.google.com/mail/u/0/#inbox",
        )

    def _yandex_mail_target(self, obj: Object, meta: dict) -> OpenTarget:
        # Yandex IMAP sync does not provide a reliable per-message browser URL.
        return OpenTarget(
            available=True,
            action="web_url",
            label="Открыть Яндекс.Почту",
            url="https://mail.yandex.ru/",
            reason="yandex_exact_message_link_unavailable",
        )

    def _calendar_target(self, obj: Object, meta: dict) -> OpenTarget:
        html_link = meta.get("html_link") or obj.canonical_uri
        if html_link and self._is_safe_web_url(html_link):
            return OpenTarget(
                available=True,
                action="web_url",
                label="Открыть в календаре",
                url=html_link,
            )
        return OpenTarget(
            available=False,
            action="unavailable",
            label="Открыть в источнике",
            reason="calendar_link_missing",
        )

    def _mattermost_target(self, obj: Object, meta: dict) -> OpenTarget:
        label = "Открыть в Mattermost"
        raw_account_id = meta.get("account_id")
        post_id = str(meta.get("post_id") or "").strip()
        raw_meta_server = meta.get("server_url")
        if not raw_account_id or not post_id or not raw_meta_server:
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="mattermost_metadata_incomplete",
            )
        try:
            account_id = UUID(str(raw_account_id))
        except ValueError:
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="mattermost_metadata_tampered",
            )

        account = self._session.scalar(
            select(MattermostAccount).where(
                MattermostAccount.id == account_id,
                MattermostAccount.user_id == self._user_id,
            )
        )
        if account is None:
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="mattermost_metadata_tampered",
            )

        try:
            meta_server = normalize_server_url(str(raw_meta_server))
        except MattermostSecurityError:
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="mattermost_metadata_tampered",
            )

        if meta_server != account.server_url:
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="mattermost_metadata_tampered",
            )

        allowed_urls = parse_allowed_base_urls(settings.mattermost_allowed_base_urls)
        if account.server_url not in allowed_urls:
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="mattermost_server_not_allowlisted",
            )

        expected_external_id = build_external_id(account.server_url, post_id)
        if obj.external_id != expected_external_id:
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="mattermost_metadata_tampered",
            )

        server_base = account.server_url.rstrip("/")
        team_name = str(meta.get("team_name") or "").strip()
        if team_name and self._is_safe_path_segment(team_name) and self._is_safe_path_segment(post_id):
            team_segment = quote(team_name, safe="")
            post_segment = quote(post_id, safe="")
            url = f"{server_base}/{team_segment}/pl/{post_segment}"
            if self._is_safe_web_url(url):
                return OpenTarget(
                    available=True,
                    action="web_url",
                    label=label,
                    url=url,
                )

        if self._is_safe_web_url(server_base):
            return OpenTarget(
                available=True,
                action="web_url",
                label=label,
                url=server_base,
                reason="mattermost_exact_post_link_unavailable",
            )
        return OpenTarget(
            available=False,
            action="unavailable",
            label=label,
            reason="mattermost_server_unsafe",
        )

    def _google_drive_target(self, obj: Object, meta: dict) -> OpenTarget:
        label = "Открыть в Google Drive"
        raw_account_id = meta.get("account_id")
        file_id = str(meta.get("file_id") or "").strip()
        if not raw_account_id or not file_id:
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="google_drive_metadata_tampered",
            )
        try:
            account_id = UUID(str(raw_account_id))
        except ValueError:
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="google_drive_metadata_tampered",
            )

        account = self._session.scalar(
            select(GoogleAccount).where(
                GoogleAccount.id == account_id,
                GoogleAccount.user_id == self._user_id,
            )
        )
        if account is None:
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="google_drive_metadata_tampered",
            )

        if obj.external_id != file_id:
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="google_drive_metadata_tampered",
            )

        url = build_canonical_uri(file_id)
        if not self._is_safe_web_url(url):
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="google_drive_metadata_tampered",
            )
        return OpenTarget(
            available=True,
            action="web_url",
            label=label,
            url=url,
        )

    def _yandex_disk_target(self, obj: Object, meta: dict) -> OpenTarget:
        label = "Открыть в Яндекс.Диске"
        resource_id = str(meta.get("resource_id") or "").strip()
        if not resource_id or obj.external_id != resource_id:
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="yandex_disk_metadata_tampered",
            )

        url: str | None = None
        public_url = meta.get("public_url")
        if public_url and is_valid_yandex_disk_share_url(str(public_url)):
            url = parse_yandex_disk_share_url(str(public_url))
        if url is None:
            intake_url = meta.get("intake_url")
            if intake_url and is_valid_yandex_disk_share_url(str(intake_url)):
                url = parse_yandex_disk_share_url(str(intake_url))

        if not url or not self._is_safe_web_url(url):
            return OpenTarget(
                available=False,
                action="unavailable",
                label=label,
                reason="yandex_disk_metadata_tampered",
            )
        return OpenTarget(
            available=True,
            action="web_url",
            label=label,
            url=url,
        )

    def _web_target(self, obj: Object) -> OpenTarget:
        uri = obj.canonical_uri
        if uri and self._is_safe_web_url(uri):
            return OpenTarget(
                available=True,
                action="web_url",
                label="Открыть страницу",
                url=uri,
            )
        return OpenTarget(
            available=False,
            action="unavailable",
            label="Открыть в источнике",
            reason="unsafe_or_missing_web_uri",
        )

    def _local_device_target(self, obj: Object, meta: dict) -> OpenTarget:
        device_key = meta.get("device_key")
        client_path = meta.get("client_source_path")
        if not device_key or not client_path:
            return OpenTarget(
                available=False,
                action="unavailable",
                label="Открыть файл",
                reason="client_source_path_missing",
            )
        if obj.kind == "folder":
            return OpenTarget(
                available=True,
                action="local_folder",
                label="Открыть папку",
                device_key=str(device_key),
                local_path=str(client_path),
            )
        return OpenTarget(
            available=True,
            action="local_file",
            label="Открыть файл",
            device_key=str(device_key),
            local_path=str(client_path),
        )

    def _attachment_target(self, obj: Object, meta: dict) -> OpenTarget:
        parent_id = meta.get("parent_email_id")
        if parent_id:
            parent = self._session.scalar(
                select(Object).where(
                    Object.id == UUID(str(parent_id)),
                    Object.user_id == self._user_id,
                )
            )
            if parent is not None:
                return self.resolve(parent.id)
        return OpenTarget(
            available=False,
            action="unavailable",
            label="Открыть в источнике",
            reason="attachment_parent_missing",
        )

    @staticmethod
    def _is_safe_web_url(url: str) -> bool:
        parsed = urlparse(url.strip())
        if parsed.scheme not in _SAFE_WEB_SCHEMES:
            return False
        if parsed.username or parsed.password:
            return False
        return bool(parsed.netloc)

    @staticmethod
    def _is_safe_path_segment(value: str) -> bool:
        if not value or value in {".", ".."}:
            return False
        return "/" not in value and "\\" not in value
