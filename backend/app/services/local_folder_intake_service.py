"""Explicit local folder intake — one folder Object, no child import."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.local.constants import POLICY_METADATA_ONLY
from app.services.folder_object_service import FolderObjectService
from app.services.local_device_service import LocalDeviceService


@dataclass(frozen=True)
class LocalFolderIntakeResult:
    object_id: UUID
    status: str


class LocalFolderIntakeService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        device_service: LocalDeviceService,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._device_service = device_service
        self._folder_objects = FolderObjectService(session, user_id)

    def intake_folder(
        self,
        device_key: str,
        root_path: str,
        client_source_path: str,
        display_name: str | None = None,
    ) -> LocalFolderIntakeResult:
        self._device_service.register_device(
            device_key=device_key,
            display_name=display_name or device_key,
            update_existing_display_name=False,
        )
        root_result = self._device_service.register_root(
            device_key=device_key,
            root_path=root_path,
            default_policy=POLICY_METADATA_ONLY,
            client_source_path=client_source_path,
            ensure_folder_object=False,
            preserve_existing_policy=True,
        )
        device = self._device_service.get_device_for_user(device_key)
        root = self._device_service.get_root_for_user(root_result.root_id)
        folder_obj, folder_status = self._folder_objects.ensure_folder_for_explicit_intake(
            device,
            root,
            client_source_path=client_source_path,
        )
        return LocalFolderIntakeResult(object_id=folder_obj.id, status=folder_status)
