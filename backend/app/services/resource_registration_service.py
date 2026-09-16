import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ResourceRegisterRequest
from app.db.models import Object
from app.resources.constants import (
    ALLOWED_UPLOAD_SUFFIXES,
    CLOUD_PROVIDERS,
    CONTENT_INGESTED_REVISION_KEY,
    MAX_REGISTER_TEXT_CHARS,
    MAX_UPLOAD_BYTES,
    PROVIDER_UPLOAD,
    PROVIDER_WEB,
    REVISION_METADATA_KEYS,
)
from app.resources.upload_staging import StagedUpload
from app.resources.web_fetch import WebFetchError, WebFetchResult, fetch_web_page
from app.services.db_errors import is_external_object_unique_violation
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.job_queue_service import JobQueueService
from app.services.representation_service import RepresentationService


@dataclass(frozen=True)
class ResourceRegisterResult:
    object_id: UUID
    status: str
    kind: str
    title: str
    canonical_uri: str | None
    provider: str | None
    external_id: str | None
    jobs_enqueued: int
    representations_created: int


_METADATA_COMPARE_SKIP_KEYS = frozenset(
    {
        "content_revision",
        CONTENT_INGESTED_REVISION_KEY,
        "registered_at",
        "fetched_at",
        "upload_path",
        "upload_filename",
    }
)

_SYSTEM_METADATA_KEYS = frozenset(
    {
        "content_hash",
        "content_revision",
        CONTENT_INGESTED_REVISION_KEY,
        "upload_path",
        "upload_filename",
    }
)

_SYSTEM_METADATA_SKIP_ON_NEW_UPLOAD = frozenset(
    {"content_hash", "upload_path", "upload_filename"}
)


class ResourceRegistrationService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        job_queue: JobQueueService,
        upload_root: Path | None = None,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._job_queue = job_queue
        self._upload_root = upload_root or Path("/tmp/secretary-uploads")

    def register(
        self,
        data: ResourceRegisterRequest,
        staged_upload: StagedUpload | None = None,
    ) -> ResourceRegisterResult:
        provider = self._resolve_provider(data)
        external_id = self._resolve_external_id(data)
        metadata = dict(data.metadata)
        metadata.setdefault("registered_at", datetime.now(UTC).isoformat())
        if data.local_path_metadata:
            metadata["local_path_metadata"] = data.local_path_metadata

        if staged_upload is not None:
            metadata["content_hash"] = staged_upload.content_hash
            metadata["upload_filename"] = staged_upload.original_filename
            if provider is None:
                provider = PROVIDER_UPLOAD
            if external_id is None:
                external_id = staged_upload.content_hash

        if data.text and not any(metadata.get(key) for key in REVISION_METADATA_KEYS):
            metadata.setdefault(
                "content_hash",
                hashlib.sha256(data.text.encode("utf-8")).hexdigest(),
            )

        if data.text is not None and len(data.text) > MAX_REGISTER_TEXT_CHARS:
            raise ValidationError("register text exceeds size limit")

        existing = self._find_existing(data.kind, provider, external_id, data.canonical_uri)
        if existing is not None:
            self._preserve_system_metadata(
                metadata,
                existing.metadata_ or {},
                new_upload=staged_upload is not None,
            )

        revision = self._revision_signature(metadata)
        if revision is not None:
            metadata["content_revision"] = revision

        metadata_changed = (
            existing is not None and self._metadata_differs(existing, data, metadata)
        )
        same_revision = (
            existing is not None
            and revision is not None
            and (existing.metadata_ or {}).get("content_revision") == revision
        )

        if existing is not None and same_revision and not metadata_changed:
            filename_updated = False
            if staged_upload is not None:
                prior = existing.metadata_ or {}
                if (
                    prior.get("content_hash") == staged_upload.content_hash
                    and prior.get("upload_filename") != staged_upload.original_filename
                ):
                    updated_meta = dict(prior)
                    updated_meta["upload_filename"] = staged_upload.original_filename
                    existing.metadata_ = updated_meta
                    self._session.flush()
                    filename_updated = True
            if not data.ingest_content or self._revision_already_ingested(existing, revision):
                if filename_updated:
                    return ResourceRegisterResult(
                        object_id=existing.id,
                        status="updated",
                        kind=existing.kind,
                        title=existing.title,
                        canonical_uri=existing.canonical_uri,
                        provider=existing.provider,
                        external_id=existing.external_id,
                        jobs_enqueued=0,
                        representations_created=0,
                    )
                return self._unchanged_result(existing)

        fetched: WebFetchResult | None = None
        needs_web_ingest = (
            data.kind == "web_page"
            and data.ingest_content
            and data.canonical_uri
            and (
                existing is None
                or not self._revision_already_ingested(existing, revision)
            )
        )
        if needs_web_ingest:
            self._ensure_no_open_transaction()
            try:
                fetched = fetch_web_page(data.canonical_uri)
            except WebFetchError as exc:
                raise ValidationError(exc.message) from exc

        created = existing is None
        obj = existing or self._create_object(data, provider, external_id, metadata)
        if not created:
            self._apply_metadata_update(obj, data, provider, external_id, metadata)

        ingested_marker = (obj.metadata_ or {}).get(CONTENT_INGESTED_REVISION_KEY)
        should_ingest = data.ingest_content and not self._revision_already_ingested(
            obj, revision
        )
        if ingested_marker is not None:
            metadata.setdefault(CONTENT_INGESTED_REVISION_KEY, ingested_marker)

        content_changed = False
        representations_created = 0
        stored_upload_path: Path | None = None
        newly_persisted_upload: Path | None = None

        try:
            if data.text is not None:
                bounded = data.text
                if obj.body != bounded:
                    obj.body = bounded
                if should_ingest and bounded:
                    representations_created = len(
                        self._representation_service().ingest_text_content(obj.id, bounded)
                    )
                    content_changed = True

            if staged_upload is not None:
                prior_meta = obj.metadata_ or {}
                prior_hash = prior_meta.get("content_hash")
                same_content = (
                    not created
                    and prior_hash is not None
                    and staged_upload.content_hash == prior_hash
                )
                if same_content:
                    prior_path = prior_meta.get("upload_path")
                    if prior_path:
                        metadata["upload_path"] = prior_path
                        stored_upload_path = Path(prior_path)
                    metadata["upload_filename"] = staged_upload.original_filename
                    store_upload = False
                else:
                    store_upload = created or staged_upload.content_hash != prior_hash
                if store_upload:
                    try:
                        stored_upload_path, was_new_file = self._store_upload(
                            obj.id, staged_upload
                        )
                    except Exception:
                        self._cleanup_pending_upload_files(obj.id)
                        raise
                    if was_new_file:
                        newly_persisted_upload = stored_upload_path
                    metadata["upload_path"] = str(stored_upload_path)
                    metadata["upload_filename"] = staged_upload.original_filename
                    obj.provider = provider or PROVIDER_UPLOAD
                    obj.external_id = external_id or staged_upload.content_hash

            if should_ingest:
                file_path = stored_upload_path or self._resolve_upload_path(obj, metadata)
                if file_path is not None and data.text is None:
                    representations_created = len(
                        self._representation_service().ingest_file(obj.id, file_path)
                    )
                    content_changed = True

            if fetched is not None and should_ingest:
                if fetched.title and (created or obj.title == data.title):
                    obj.title = fetched.title
                obj.body = fetched.text
                obj.canonical_uri = fetched.final_url
                metadata["fetched_at"] = datetime.now(UTC).isoformat()
                representations_created = len(
                    self._representation_service().ingest_text_content(obj.id, fetched.text)
                )
                content_changed = True
        except Exception:
            if newly_persisted_upload is not None:
                newly_persisted_upload.unlink(missing_ok=True)
            raise

        if content_changed and revision is not None:
            metadata[CONTENT_INGESTED_REVISION_KEY] = revision

        if content_changed:
            from app.services.representation_generation import (
                bump_representation_generation,
                get_representation_generation,
            )

            metadata = bump_representation_generation(metadata)

        obj.metadata_ = dict(metadata)

        jobs_enqueued = 0
        if content_changed:
            from app.services.pipeline_enqueue import enqueue_summarize_resource

            enqueue_summarize_resource(
                self._session,
                obj.id,
                self._user_id,
                revision,
                get_representation_generation(obj.metadata_),
            )
            jobs_enqueued = 1
        elif (
            not data.ingest_content or not self._revision_already_ingested(obj, revision)
        ) and (
            created
            or metadata_changed
            or (revision is not None and not same_revision)
        ):
            from app.services.pipeline_enqueue import enqueue_embed_object

            enqueue_embed_object(self._session, obj.id, self._user_id)
            jobs_enqueued = 1

        self._session.flush()

        if created:
            status = "created"
        elif content_changed or metadata_changed:
            status = "updated"
        else:
            status = "unchanged"

        return ResourceRegisterResult(
            object_id=obj.id,
            status=status,
            kind=obj.kind,
            title=obj.title,
            canonical_uri=obj.canonical_uri,
            provider=obj.provider,
            external_id=obj.external_id,
            jobs_enqueued=jobs_enqueued,
            representations_created=representations_created,
        )

    def _unchanged_result(self, obj: Object) -> ResourceRegisterResult:
        return ResourceRegisterResult(
            object_id=obj.id,
            status="unchanged",
            kind=obj.kind,
            title=obj.title,
            canonical_uri=obj.canonical_uri,
            provider=obj.provider,
            external_id=obj.external_id,
            jobs_enqueued=0,
            representations_created=0,
        )

    def _ensure_no_open_transaction(self) -> None:
        if self._session.in_transaction():
            self._session.commit()

    def _representation_service(self) -> RepresentationService:
        return RepresentationService(self._session, self._user_id)

    def _resolve_upload_path(self, obj: Object, metadata: dict[str, Any]) -> Path | None:
        raw_path = metadata.get("upload_path") or (obj.metadata_ or {}).get("upload_path")
        if not raw_path:
            return None
        path = Path(raw_path)
        if not path.is_file():
            return None
        return path

    def _resolve_provider(self, data: ResourceRegisterRequest) -> str | None:
        if data.provider:
            return data.provider
        provider = data.metadata.get("provider")
        if isinstance(provider, str):
            return provider
        if data.kind == "web_page":
            return PROVIDER_WEB
        return None

    def _resolve_external_id(self, data: ResourceRegisterRequest) -> str | None:
        if data.external_id:
            return data.external_id
        external_id = data.metadata.get("external_id")
        if isinstance(external_id, str):
            return external_id
        return None

    def _preserve_system_metadata(
        self,
        metadata: dict[str, Any],
        prior: dict[str, Any],
        new_upload: bool,
    ) -> None:
        for key in _SYSTEM_METADATA_KEYS:
            if new_upload and key in _SYSTEM_METADATA_SKIP_ON_NEW_UPLOAD:
                continue
            if metadata.get(key) is None and prior.get(key) is not None:
                metadata[key] = prior[key]

    def _revision_signature(self, metadata: dict[str, Any]) -> str | None:
        parts = {
            key: metadata[key]
            for key in REVISION_METADATA_KEYS
            if metadata.get(key) is not None
        }
        if not parts:
            return None
        return json.dumps(parts, sort_keys=True, default=str)

    def _revision_already_ingested(self, obj: Object, revision: str | None) -> bool:
        ingested = (obj.metadata_ or {}).get(CONTENT_INGESTED_REVISION_KEY)
        if revision is None:
            return ingested is not None
        return ingested == revision

    def _metadata_differs(
        self,
        obj: Object,
        data: ResourceRegisterRequest,
        metadata: dict[str, Any],
    ) -> bool:
        if obj.title != data.title:
            return True
        if data.canonical_uri is not None and obj.canonical_uri != data.canonical_uri:
            return True
        old_meta = {
            key: value
            for key, value in (obj.metadata_ or {}).items()
            if key not in _METADATA_COMPARE_SKIP_KEYS
        }
        new_meta = {
            key: value
            for key, value in metadata.items()
            if key not in _METADATA_COMPARE_SKIP_KEYS
        }
        return old_meta != new_meta

    def _find_existing(
        self,
        kind: str,
        provider: str | None,
        external_id: str | None,
        canonical_uri: str | None,
    ) -> Object | None:
        if provider and external_id:
            return self._session.scalar(
                select(Object).where(
                    Object.user_id == self._user_id,
                    Object.provider == provider,
                    Object.kind == kind,
                    Object.external_id == external_id,
                )
            )
        if canonical_uri:
            return self._session.scalar(
                select(Object).where(
                    Object.user_id == self._user_id,
                    Object.kind == kind,
                    Object.canonical_uri == canonical_uri,
                )
            )
        return None

    def _create_object(
        self,
        data: ResourceRegisterRequest,
        provider: str | None,
        external_id: str | None,
        metadata: dict[str, Any],
    ) -> Object:
        if provider in CLOUD_PROVIDERS and not external_id:
            raise ValidationError("cloud resources require external_id")
        obj = Object(
            user_id=self._user_id,
            kind=data.kind,
            title=data.title,
            origin="user",
            state="confirmed",
            body=data.text if data.text else None,
            provider=provider,
            external_id=external_id,
            canonical_uri=data.canonical_uri,
            metadata_=dict(metadata),
        )
        self._session.add(obj)
        try:
            self._session.flush()
        except Exception as exc:
            if is_external_object_unique_violation(exc):
                raise ConflictError("external object already exists") from exc
            raise
        return obj

    def _apply_metadata_update(
        self,
        obj: Object,
        data: ResourceRegisterRequest,
        provider: str | None,
        external_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        obj.title = data.title
        obj.canonical_uri = data.canonical_uri or obj.canonical_uri
        if provider:
            obj.provider = provider
        if external_id:
            obj.external_id = external_id

    def _store_upload(self, object_id: UUID, staged: StagedUpload) -> tuple[Path, bool]:
        suffix = Path(staged.original_filename).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            raise ValidationError(f"unsupported upload format: {suffix or '(none)'}")
        if staged.size > MAX_UPLOAD_BYTES:
            raise ValidationError("upload exceeds size limit")
        target_dir = self._upload_root / str(self._user_id) / str(object_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{staged.content_hash}{suffix}"
        if target_path.is_file():
            return target_path, False
        pending_path = target_dir / f".pending-{uuid.uuid4().hex}{suffix}"
        try:
            shutil.copyfile(staged.path, pending_path)
            pending_path.replace(target_path)
        except Exception:
            pending_path.unlink(missing_ok=True)
            raise
        return target_path, True

    def _cleanup_pending_upload_files(self, object_id: UUID) -> None:
        target_dir = self._upload_root / str(self._user_id) / str(object_id)
        if not target_dir.is_dir():
            return
        for path in target_dir.glob(".pending-*"):
            path.unlink(missing_ok=True)

    def get_object_for_user(self, object_id: UUID) -> Object:
        obj = self._session.scalar(
            select(Object).where(Object.id == object_id, Object.user_id == self._user_id)
        )
        if obj is None:
            raise NotFoundError("object", object_id)
        return obj
