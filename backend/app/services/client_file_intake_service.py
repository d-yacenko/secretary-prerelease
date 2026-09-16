"""Client-assisted local file intake into canonical objects."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LocalRoot, Object, Representation
from app.domain.object_visibility import restore_object_from_explicit_intake
from app.local.client_paths import (
    build_client_source_external_id,
    compute_client_content_revision,
    normalize_client_source_path,
)
from app.local.constants import (
    POLICY_INDEX_TEXT,
    POLICY_METADATA_ONLY,
    PROVIDER_LOCAL_DEVICE,
    build_local_external_id,
    build_personal_file_uri,
    infer_local_kind,
)
from app.local.paths import normalize_relative_path
from app.services.client_intake_constants import (
    CLIENT_INDEXABLE_SUFFIXES,
    CLIENT_REPRESENTATION_KINDS,
    LEGACY_METADATA_ONLY_SUFFIXES,
)
from app.services.client_representation_service import ClientRepresentationPersistence
from app.services.embedding_index import clear_object_embedding
from app.services.errors import NotFoundError, ValidationError
from app.services.folder_containment_service import FolderContainmentService
from app.services.folder_object_service import EXPLICIT_LOCAL_INTAKE_MODE, FolderObjectService
from app.services.local_device_service import LocalDeviceService
from app.services.pipeline_enqueue import enqueue_embed_object, enqueue_summarize_resource
from app.services.representation_generation import (
    bump_representation_generation,
    get_representation_generation,
)
from app.services.semantic_summary_service import invalidate_semantic_summary_metadata


@dataclass(frozen=True)
class ClientFileIntakeResult:
    object_id: UUID
    status: str
    jobs_enqueued: int
    representations_created: int
    metadata_only: bool


class ClientFileIntakeService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        device_service: LocalDeviceService,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._devices = device_service
        self._representations = ClientRepresentationPersistence(session, user_id)

    def intake(
        self,
        device_key: str,
        source_path: str,
        filename: str,
        size: int,
        modified_at: str,
        content_revision: str,
        representations: list[dict] | None = None,
        content_hash: str | None = None,
        metadata_only: bool = False,
        root_path: str | None = None,
        client_absolute_path: str | None = None,
        intake_mode: str | None = None,
    ) -> ClientFileIntakeResult:
        if intake_mode is not None and intake_mode != EXPLICIT_LOCAL_INTAKE_MODE:
            raise ValidationError(f"unsupported intake mode: {intake_mode}")

        is_explicit = intake_mode == EXPLICIT_LOCAL_INTAKE_MODE
        device = self._devices.get_device_for_user(device_key)
        if device is None:
            raise NotFoundError("local_device", device_key)

        reps = representations or []
        if metadata_only and reps:
            raise ValidationError("metadata_only intake cannot include representations")

        filename_value = Path(filename).name if root_path else filename
        suffix = Path(filename_value).suffix.lower()
        if not metadata_only:
            if suffix not in CLIENT_INDEXABLE_SUFFIXES:
                raise ValidationError(
                    "unsupported file format requires metadata_only intake"
                )
            if not reps:
                raise ValidationError("indexed intake requires mechanical representations")

        normalized_root: str | None = None
        normalized_rel: str | None = None
        if root_path:
            normalized_root = normalize_relative_path(root_path)
            normalized_rel = normalize_relative_path(source_path)
            external_id = build_local_external_id(
                device_key, normalized_root, normalized_rel
            )
            client_locator = normalize_client_source_path(
                client_absolute_path or source_path
            )
        else:
            client_locator = normalize_client_source_path(source_path)
            external_id = build_client_source_external_id(device_key, client_locator)

        expected_revision = compute_client_content_revision(
            client_locator, size, modified_at, content_hash
        )
        if content_revision != expected_revision:
            raise ValidationError("invalid client revision")

        kind = infer_local_kind(suffix) if suffix in CLIENT_INDEXABLE_SUFFIXES else "file"

        incoming_policy = POLICY_METADATA_ONLY if metadata_only else POLICY_INDEX_TEXT
        has_content = not metadata_only and len(reps) > 0

        existing = self._session.scalar(
            select(Object)
            .where(
                Object.user_id == self._user_id,
                Object.provider == PROVIDER_LOCAL_DEVICE,
                Object.external_id == external_id,
            )
            .with_for_update()
        )

        prior_meta: dict[str, Any] = dict(existing.metadata_ or {}) if existing else {}
        prior_revision = prior_meta.get("content_revision")
        prior_policy = prior_meta.get("indexing_policy")
        prior_registered_at = prior_meta.get("registered_at")
        had_mechanical_reps = (
            self._has_mechanical_representations(existing.id) if existing else False
        )

        revision_changed = existing is not None and prior_revision != expected_revision
        policy_changed = existing is not None and prior_policy != incoming_policy
        created = existing is None

        if existing is not None and is_explicit:
            restore_object_from_explicit_intake(existing)

        metadata: dict[str, Any] = {
            "device_key": device_key,
            "client_source_path": client_locator,
            "filename": filename_value,
            "size": size,
            "modified_at": modified_at,
            "content_revision": expected_revision,
            "indexing_policy": incoming_policy,
        }
        if normalized_root and normalized_rel:
            metadata["local_root_path"] = normalized_root
            metadata["local_relative_path"] = normalized_rel
        if content_hash:
            metadata["content_hash"] = content_hash
        if is_explicit:
            metadata["intake_mode"] = EXPLICIT_LOCAL_INTAKE_MODE
        if prior_registered_at:
            metadata["registered_at"] = prior_registered_at
        else:
            metadata["registered_at"] = datetime.now(UTC).isoformat()

        if existing is None:
            obj = Object(
                user_id=self._user_id,
                kind=kind,
                title=filename_value,
                origin="source" if is_explicit else "user",
                state="observed" if is_explicit else "confirmed",
                provider=PROVIDER_LOCAL_DEVICE,
                external_id=external_id,
                canonical_uri=build_personal_file_uri(device_key, external_id),
                metadata_=dict(metadata),
            )
            self._session.add(obj)
            self._session.flush()
            obj.canonical_uri = build_personal_file_uri(device_key, str(obj.id))
        else:
            merged = dict(prior_meta)
            if revision_changed or is_explicit:
                merged = invalidate_semantic_summary_metadata(merged)
            merged.update(metadata)
            existing.title = filename_value
            existing.kind = kind
            existing.metadata_ = merged
            if is_explicit:
                existing.origin = "source"
                existing.state = "observed"
            existing.canonical_uri = build_personal_file_uri(device_key, str(existing.id))
            obj = existing

        if normalized_root:
            root = self._session.scalar(
                select(LocalRoot).where(
                    LocalRoot.user_id == self._user_id,
                    LocalRoot.device_id == device.id,
                    LocalRoot.root_path == normalized_root,
                )
            )
            if root is None:
                raise NotFoundError("local_root", normalized_root)
            folder_objects = FolderObjectService(self._session, self._user_id)
            folder_obj = folder_objects.ensure_folder_for_root(device, root)
            FolderContainmentService(self._session, self._user_id).link_files_to_folder(
                folder_obj.id, [obj.id]
            )

        representations_created = 0
        jobs_enqueued = 0
        status = "created"

        if metadata_only:
            if had_mechanical_reps or prior_policy == POLICY_INDEX_TEXT:
                self._representations.delete_all_for_object(obj.id)
                obj.metadata_ = bump_representation_generation(
                    invalidate_semantic_summary_metadata(dict(obj.metadata_ or {}))
                )
                clear_object_embedding(obj)
                enqueue_embed_object(self._session, obj.id, self._user_id)
                jobs_enqueued = 1
                status = "updated" if existing else "created"
            elif created:
                enqueue_embed_object(self._session, obj.id, self._user_id)
                jobs_enqueued = 1
                status = "created"
            elif is_explicit:
                enqueue_embed_object(self._session, obj.id, self._user_id)
                jobs_enqueued = 1
                status = "updated"
            elif revision_changed or policy_changed:
                enqueue_embed_object(self._session, obj.id, self._user_id)
                jobs_enqueued = 1
                status = "updated"
            else:
                status = "unchanged"
        elif has_content:
            truly_unchanged = (
                not is_explicit
                and not created
                and not revision_changed
                and not policy_changed
                and prior_policy == POLICY_INDEX_TEXT
                and had_mechanical_reps
            )
            if truly_unchanged:
                status = "unchanged"
            else:
                obj.metadata_ = bump_representation_generation(dict(obj.metadata_ or {}))
                self._session.flush()
                representations_created = self._representations.replace_for_object(
                    obj.id,
                    filename_value,
                    reps,
                    metadata_only=False,
                )
                enqueue_summarize_resource(
                    self._session,
                    obj.id,
                    self._user_id,
                    expected_revision,
                    get_representation_generation(obj.metadata_),
                )
                jobs_enqueued = 1
                status = "created" if created else "updated"
        elif created:
            enqueue_embed_object(self._session, obj.id, self._user_id)
            jobs_enqueued = 1
            status = "created"

        self._session.flush()
        return ClientFileIntakeResult(
            object_id=obj.id,
            status=status,
            jobs_enqueued=jobs_enqueued,
            representations_created=representations_created,
            metadata_only=metadata_only or not has_content,
        )

    def _has_mechanical_representations(self, object_id: UUID) -> bool:
        row = self._session.scalar(
            select(Representation.id).where(
                Representation.object_id == object_id,
                Representation.kind.in_(CLIENT_REPRESENTATION_KINDS),
            ).limit(1)
        )
        return row is not None
