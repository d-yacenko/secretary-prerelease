from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.google.constants import DRIVE_READONLY_SCOPE, GOOGLE_DRIVE_PROVIDER
from app.connectors.google.credentials import GoogleAccountStore
from app.connectors.google.drive_metadata_errors import raise_for_drive_metadata_error
from app.connectors.google.drive_normalize import normalize_drive_file
from app.connectors.google.drive_transport import DriveTransport
from app.connectors.google.drive_url_parser import parse_google_drive_file_id
from app.connectors.google.errors import (
    GoogleApiError,
    GoogleConfigurationError,
    GoogleConnectorError,
)
from app.connectors.google.gmail_transport import GoogleTokenManager
from app.connectors.google.oauth_service import GoogleOAuthService
from app.connectors.yandex.constants import YANDEX_DISK_PROVIDER
from app.connectors.yandex.disk_normalize import normalize_yandex_disk_resource
from app.connectors.yandex.disk_transport import YandexDiskTransport
from app.connectors.yandex.disk_url_parser import parse_yandex_disk_share_url
from app.connectors.yandex.errors import YandexDiskApiError
from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.content_invalidation import invalidate_object_content_immediately
from app.content_extraction.extract_service import (
    apply_intake_content_metadata,
    extraction_work_needed,
)
from app.content_extraction.intake_metadata import (
    content_revision_changed,
    is_ready_content_unchanged,
    merge_intake_metadata,
    provider_metadata_changed,
)
from app.content_extraction.metadata_keys import CONTENT_EXTRACTION_STATUS, STATUS_READY
from app.content_extraction.revision import metadata_extraction_version
from app.db.models import GoogleAccount, Object, Representation
from app.domain.object_visibility import (
    is_object_hidden_from_active_reads,
    restore_object_from_explicit_intake,
)
from app.services.client_intake_constants import CLIENT_REPRESENTATION_KINDS
from app.services.explicit_link_intake_errors import (
    AccountSelectionRequiredError,
    ExplicitLinkIntakeError,
)
from app.services.explicit_link_provider import detect_intake_provider
from app.services.pipeline_enqueue import (
    enqueue_embed_object,
    enqueue_extract_explicit_resource_content,
)

EXPLICIT_INTAKE_MODE = "explicit_link"


@dataclass(frozen=True)
class IntakeLinkResult:
    object_id: UUID
    provider: str
    kind: str
    status: str
    content_status: str
    content_jobs_enqueued: int


class ExplicitLinkIntakeService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        google_transport: DriveTransport | None = None,
        yandex_transport: YandexDiskTransport | None = None,
        account_store: GoogleAccountStore | None = None,
        token_manager: GoogleTokenManager | None = None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._google_transport = google_transport
        self._yandex_transport = yandex_transport
        self._account_store = account_store
        self._token_manager = token_manager

    def intake_link(self, url: str, account_id: UUID | None = None) -> IntakeLinkResult:
        provider = detect_intake_provider(url)
        if provider == GOOGLE_DRIVE_PROVIDER:
            return self._intake_google_drive(url, account_id)
        if provider == YANDEX_DISK_PROVIDER:
            return self._intake_yandex_disk(url)
        raise ExplicitLinkIntakeError("unsupported link url")

    def close(self) -> None:
        if self._google_transport is not None:
            self._google_transport.close()
        if self._yandex_transport is not None:
            self._yandex_transport.close()

    def _intake_google_drive(self, url: str, account_id: UUID | None) -> IntakeLinkResult:
        if (
            self._account_store is None
            or self._token_manager is None
            or self._google_transport is None
        ):
            raise GoogleConfigurationError("google explicit link intake is not configured")

        file_id = parse_google_drive_file_id(url)
        account = self._resolve_google_account(account_id)
        self._require_drive_scope(account)

        access_token = self._token_manager.get_valid_access_token(account.id, self._user_id)
        self._session.commit()

        try:
            raw_file = self._google_transport.get_file_metadata(access_token, file_id)
        except GoogleApiError as exc:
            raise_for_drive_metadata_error(exc)

        normalized = normalize_drive_file(
            raw_file,
            account.id,
            intake_mode=EXPLICIT_INTAKE_MODE,
        )
        if normalized is None:
            raise ExplicitLinkIntakeError("google drive resource unavailable")

        existing = self._find_existing(GOOGLE_DRIVE_PROVIDER, normalized["external_id"])
        if normalized.get("trashed"):
            if existing is None:
                raise ExplicitLinkIntakeError("google drive resource unavailable")
            internal_status = self._tombstone_existing(existing)
            return self._result(existing, internal_status)

        obj, internal_status, jobs = self._upsert(existing, normalized)
        return self._result(obj, internal_status, jobs)

    def _intake_yandex_disk(self, url: str) -> IntakeLinkResult:
        if self._yandex_transport is None:
            raise ExplicitLinkIntakeError("yandex disk intake unavailable")

        share_url = parse_yandex_disk_share_url(url)

        try:
            raw_resource = self._yandex_transport.get_public_resource_metadata(share_url)
        except YandexDiskApiError as exc:
            if exc.status_code == 404:
                raise ExplicitLinkIntakeError("yandex disk resource unavailable") from exc
            if exc.status_code in {401, 403}:
                raise ExplicitLinkIntakeError("yandex disk resource permission denied") from exc
            raise

        normalized = normalize_yandex_disk_resource(
            raw_resource,
            intake_url=share_url,
            intake_mode=EXPLICIT_INTAKE_MODE,
        )
        if normalized is None:
            raise ExplicitLinkIntakeError("yandex disk provider metadata error")

        existing = self._find_existing(YANDEX_DISK_PROVIDER, normalized["external_id"])
        obj, internal_status, jobs = self._upsert(existing, normalized)
        return self._result(obj, internal_status, jobs)

    def _resolve_google_account(self, account_id: UUID | None) -> GoogleAccount:
        assert self._account_store is not None
        if account_id is not None:
            account = self._account_store.get_by_id_for_user(account_id, self._user_id)
            if account is None:
                raise ExplicitLinkIntakeError("google account not found")
            return account

        accounts = self._account_store.list_accounts(self._user_id)
        if not accounts:
            raise ExplicitLinkIntakeError("google account not connected")

        drive_accounts = [
            account
            for account in accounts
            if DRIVE_READONLY_SCOPE in set(account.scopes or [])
        ]
        if not drive_accounts:
            raise GoogleConnectorError("google drive scope not granted")
        if len(drive_accounts) == 1:
            return drive_accounts[0]
        raise AccountSelectionRequiredError("google account selection required")

    def _require_drive_scope(self, account: GoogleAccount) -> None:
        if DRIVE_READONLY_SCOPE not in set(account.scopes or []):
            raise GoogleConnectorError("google drive scope not granted")

    def _find_existing(self, provider: str, external_id: str) -> Object | None:
        return self._session.scalar(
            select(Object).where(
                Object.user_id == self._user_id,
                Object.provider == provider,
                Object.external_id == external_id,
            )
        )

    def _upsert(
        self,
        existing: Object | None,
        normalized: dict[str, Any],
    ) -> tuple[Object, str, int]:
        provider = normalized["provider"]
        kind = normalized["kind"]
        title = normalized["title"]
        incoming_provider_meta = dict(normalized["metadata"])

        if existing is None:
            content_metadata = apply_intake_content_metadata(
                incoming_provider_meta,
                provider,
                kind,
                title,
            )
            obj = Object(
                user_id=self._user_id,
                kind=kind,
                provider=provider,
                external_id=normalized["external_id"],
                origin=normalized["origin"],
                state=normalized["state"],
                title=title,
                body=normalized.get("body"),
                canonical_uri=normalized.get("canonical_uri"),
                metadata_=content_metadata,
                occurred_at=normalized.get("occurred_at"),
            )
            self._session.add(obj)
            self._session.flush()
            jobs_enqueued = self._enqueue_new_object_pipeline(obj, content_metadata)
            return obj, "created", jobs_enqueued

        was_deleted = is_object_hidden_from_active_reads(existing)
        prior_meta = dict(existing.metadata_ or {})
        had_mechanical = self._has_mechanical_representations(existing.id)

        derived_incoming = apply_intake_content_metadata(
            incoming_provider_meta,
            provider,
            kind,
            title,
        )
        revision_changed = content_revision_changed(prior_meta, derived_incoming)
        title_changed = existing.title != title
        provider_changed = provider_metadata_changed(prior_meta, incoming_provider_meta)
        structural_changed = (
            existing.kind != kind
            or existing.occurred_at != normalized.get("occurred_at")
            or existing.canonical_uri != normalized.get("canonical_uri")
        )
        ready_unchanged = is_ready_content_unchanged(
            prior_meta,
            derived_incoming,
            had_mechanical,
        )
        version_stale = metadata_extraction_version(prior_meta) != EXTRACTION_VERSION

        if (
            not was_deleted
            and not revision_changed
            and not title_changed
            and not provider_changed
            and not structural_changed
            and not version_stale
        ):
            return existing, "unchanged", 0

        merged_meta = merge_intake_metadata(
            prior_meta,
            incoming_provider_meta,
            provider,
            kind,
            title,
            had_mechanical,
        )
        work_needed = (
            extraction_work_needed(
                provider,
                kind,
                title,
                prior_meta,
                merged_meta,
                had_mechanical,
            )
            if not ready_unchanged
            else False
        )

        jobs_enqueued = 0

        if revision_changed or version_stale:
            invalidate_object_content_immediately(self._session, existing)
            prior_meta = dict(existing.metadata_ or {})
            merged_meta = merge_intake_metadata(
                prior_meta,
                incoming_provider_meta,
                provider,
                kind,
                title,
                False,
            )
            work_needed = extraction_work_needed(
                provider,
                kind,
                title,
                prior_meta,
                merged_meta,
                False,
            ) or version_stale

        existing.kind = kind
        existing.title = title
        existing.body = normalized.get("body")
        existing.canonical_uri = normalized.get("canonical_uri")
        existing.occurred_at = normalized.get("occurred_at")
        existing.metadata_ = merged_meta

        if was_deleted:
            restore_object_from_explicit_intake(existing)

        self._session.flush()

        if work_needed:
            revision = merged_meta.get("content_revision")
            enqueue_extract_explicit_resource_content(
                self._session,
                existing.id,
                self._user_id,
                revision,
                EXTRACTION_VERSION,
            )
            merged_meta[CONTENT_EXTRACTION_STATUS] = "pending"
            existing.metadata_ = merged_meta
            jobs_enqueued = 1
        elif title_changed and merged_meta.get(CONTENT_EXTRACTION_STATUS) == STATUS_READY:
            enqueue_embed_object(self._session, existing.id, self._user_id)
            jobs_enqueued = 1
        elif merged_meta.get(CONTENT_EXTRACTION_STATUS) in {"metadata_only", "unsupported"}:
            if was_deleted or provider_changed or structural_changed:
                enqueue_embed_object(self._session, existing.id, self._user_id)
                jobs_enqueued = 1

        if was_deleted:
            return existing, "restored", jobs_enqueued
        if revision_changed or version_stale or work_needed:
            return existing, "updated", jobs_enqueued
        if title_changed or provider_changed or structural_changed:
            return existing, "metadata_updated", jobs_enqueued
        return existing, "unchanged", jobs_enqueued

    def _enqueue_new_object_pipeline(self, obj: Object, content_metadata: dict[str, Any]) -> int:
        plan_status = content_metadata.get(CONTENT_EXTRACTION_STATUS)
        if extraction_work_needed(
            obj.provider,
            obj.kind,
            obj.title,
            {},
            content_metadata,
            False,
        ):
            enqueue_extract_explicit_resource_content(
                self._session,
                obj.id,
                self._user_id,
                content_metadata.get("content_revision"),
                EXTRACTION_VERSION,
            )
            content_metadata[CONTENT_EXTRACTION_STATUS] = "pending"
            obj.metadata_ = content_metadata
            return 1
        if plan_status in {"metadata_only", "unsupported"}:
            enqueue_embed_object(self._session, obj.id, self._user_id)
            return 1
        enqueue_embed_object(self._session, obj.id, self._user_id)
        return 1

    def _tombstone_existing(self, existing: Object) -> str:
        if existing.status == "deleted":
            return "unchanged"
        existing.status = "deleted"
        return "tombstoned"

    def _result(
        self,
        obj: Object | None,
        internal_status: str,
        content_jobs_enqueued: int = 0,
    ) -> IntakeLinkResult:
        if obj is None:
            raise ExplicitLinkIntakeError("intake object unavailable")
        public_status = self._public_status(internal_status)
        metadata = obj.metadata_ or {}
        content_status = str(metadata.get(CONTENT_EXTRACTION_STATUS) or "metadata_only")
        return IntakeLinkResult(
            object_id=obj.id,
            provider=obj.provider,
            kind=obj.kind,
            status=public_status,
            content_status=content_status,
            content_jobs_enqueued=content_jobs_enqueued,
        )

    @staticmethod
    def _public_status(internal_status: str) -> str:
        if internal_status in {"created", "unchanged"}:
            return internal_status
        return "updated"

    def _has_mechanical_representations(self, object_id: UUID) -> bool:
        row = self._session.scalar(
            select(Representation.id).where(
                Representation.object_id == object_id,
                Representation.kind.in_(CLIENT_REPRESENTATION_KINDS),
            ).limit(1)
        )
        return row is not None


def build_yandex_explicit_link_intake_service(
    session: Session,
    user_id: UUID,
    yandex_transport: YandexDiskTransport | None = None,
    http_client: Any | None = None,
) -> ExplicitLinkIntakeService:
    disk_transport = yandex_transport or YandexDiskTransport(http_client=http_client)
    return ExplicitLinkIntakeService(
        session=session,
        user_id=user_id,
        yandex_transport=disk_transport,
    )


def build_google_explicit_link_intake_service(
    session: Session,
    user_id: UUID,
    credential_key: str,
    client_file: str,
    redirect_uri: str,
    google_transport: DriveTransport | None = None,
    http_client: Any | None = None,
) -> ExplicitLinkIntakeService:
    if not credential_key:
        raise GoogleConfigurationError("credential encryption key is not configured")

    encryption = GoogleAccountStore.build_encryption(credential_key)
    account_store = GoogleAccountStore(session, encryption)
    oauth_service = GoogleOAuthService(client_file, redirect_uri, http_client=http_client)
    token_manager = GoogleTokenManager(session, account_store, oauth_service)
    drive_transport = google_transport or DriveTransport(http_client=http_client)
    return ExplicitLinkIntakeService(
        session=session,
        user_id=user_id,
        account_store=account_store,
        token_manager=token_manager,
        google_transport=drive_transport,
    )


def build_explicit_link_intake_service(
    session: Session,
    user_id: UUID,
    credential_key: str,
    client_file: str,
    redirect_uri: str,
    google_transport: DriveTransport | None = None,
    yandex_transport: YandexDiskTransport | None = None,
    http_client: Any | None = None,
) -> ExplicitLinkIntakeService:
    google_service = build_google_explicit_link_intake_service(
        session=session,
        user_id=user_id,
        credential_key=credential_key,
        client_file=client_file,
        redirect_uri=redirect_uri,
        google_transport=google_transport,
        http_client=http_client,
    )
    disk_transport = yandex_transport or YandexDiskTransport(http_client=http_client)
    return ExplicitLinkIntakeService(
        session=session,
        user_id=user_id,
        account_store=google_service._account_store,
        token_manager=google_service._token_manager,
        google_transport=google_service._google_transport,
        yandex_transport=disk_transport,
    )
