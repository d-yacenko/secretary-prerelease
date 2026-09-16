"""Folder object mapping for registered local roots."""

from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ObjectCreate
from app.db.models import LocalDevice, LocalRoot, Object
from app.domain.object_visibility import restore_object_from_explicit_intake
from app.local.constants import PROVIDER_LOCAL_DEVICE
from app.local.paths import normalize_relative_path
from app.services.correlation_constants import FOLDER_KIND
from app.services.graph_service import GraphService
from app.services.provenance import CONFIRMED_STATE

EXPLICIT_LOCAL_INTAKE_MODE = "explicit_local"


def build_folder_external_id(device_key: str, root_path: str) -> str:
    normalized = normalize_relative_path(root_path)
    return f"folder:{device_key}:{normalized}"


def folder_title_from_root_path(root_path: str) -> str:
    normalized = normalize_relative_path(root_path)
    name = Path(normalized).name
    return name or normalized or "Папка"


class FolderObjectService:
    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        self._graph = GraphService(session, user_id)

    def ensure_folder_for_root(
        self,
        device: LocalDevice,
        root: LocalRoot,
        client_source_path: str | None = None,
    ) -> Object:
        obj, _ = self._upsert_folder_object(
            device,
            root,
            client_source_path=client_source_path,
            intake_mode=None,
        )
        return obj

    def ensure_folder_for_explicit_intake(
        self,
        device: LocalDevice,
        root: LocalRoot,
        client_source_path: str,
    ) -> tuple[Object, str]:
        return self._upsert_folder_object(
            device,
            root,
            client_source_path=client_source_path,
            intake_mode=EXPLICIT_LOCAL_INTAKE_MODE,
        )

    def _upsert_folder_object(
        self,
        device: LocalDevice,
        root: LocalRoot,
        client_source_path: str | None,
        intake_mode: str | None,
    ) -> tuple[Object, str]:
        external_id = build_folder_external_id(device.device_key, root.root_path)
        existing = self._session.scalar(
            select(Object).where(
                Object.user_id == self._user_id,
                Object.provider == PROVIDER_LOCAL_DEVICE,
                Object.external_id == external_id,
            )
        )
        title = folder_title_from_root_path(root.root_path)
        folder_meta_update: dict[str, object] = {
            "device_key": device.device_key,
            "local_root_path": root.root_path,
            "default_policy": root.default_policy,
        }
        if client_source_path:
            folder_meta_update["client_source_path"] = client_source_path
        if intake_mode is not None:
            folder_meta_update["intake_mode"] = intake_mode

        is_explicit = intake_mode == EXPLICIT_LOCAL_INTAKE_MODE
        explicit_origin = "source"
        explicit_state = "observed"

        if existing is not None:
            if is_explicit:
                restore_object_from_explicit_intake(existing)
            metadata = dict(existing.metadata_ or {})
            new_metadata = dict(metadata)
            new_metadata.update(folder_meta_update)
            changed = (
                existing.title != title
                or existing.metadata_ != new_metadata
            )
            if is_explicit and (
                existing.origin != explicit_origin or existing.state != explicit_state
            ):
                changed = True
            if changed:
                existing.title = title
                existing.metadata_ = new_metadata
                if is_explicit:
                    existing.origin = explicit_origin
                    existing.state = explicit_state
                self._session.flush()
                return existing, "updated"
            return existing, "unchanged"

        metadata = dict(folder_meta_update)
        obj = self._graph.create_object(
            ObjectCreate(
                kind=FOLDER_KIND,
                title=title,
                origin=explicit_origin if is_explicit else "user",
                state=explicit_state if is_explicit else CONFIRMED_STATE,
                provider=PROVIDER_LOCAL_DEVICE,
                external_id=external_id,
                metadata=metadata,
            )
        )
        return obj, "created"

    def get_folder_for_root(self, device_key: str, root_path: str) -> Object | None:
        external_id = build_folder_external_id(device_key, root_path)
        return self._session.scalar(
            select(Object).where(
                Object.user_id == self._user_id,
                Object.provider == PROVIDER_LOCAL_DEVICE,
                Object.external_id == external_id,
                Object.kind == FOLDER_KIND,
            )
        )
