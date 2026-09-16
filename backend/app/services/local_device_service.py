from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LocalDevice, LocalRoot
from app.local.constants import DEFAULT_LOCAL_POLICY, LOCAL_POLICIES
from app.local.device_keys import validate_device_key
from app.local.paths import LocalPathResolver, normalize_relative_path
from app.services.errors import NotFoundError, ValidationError
from app.services.folder_object_service import FolderObjectService


@dataclass(frozen=True)
class LocalDeviceResult:
    device_id: UUID
    device_key: str
    display_name: str
    created: bool


@dataclass(frozen=True)
class LocalRootResult:
    root_id: UUID
    device_key: str
    root_path: str
    default_policy: str
    created: bool


class LocalDeviceService:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        path_resolver: LocalPathResolver,
    ) -> None:
        self._session = session
        self._user_id = user_id
        self._path_resolver = path_resolver

    def register_device(
        self,
        device_key: str,
        display_name: str,
        update_existing_display_name: bool = True,
    ) -> LocalDeviceResult:
        normalized_key = validate_device_key(device_key)
        existing = self._session.scalar(
            select(LocalDevice).where(
                LocalDevice.user_id == self._user_id,
                LocalDevice.device_key == normalized_key,
            )
        )
        if existing is not None:
            if (
                update_existing_display_name
                and existing.display_name != display_name
            ):
                existing.display_name = display_name
                self._session.flush()
            return LocalDeviceResult(
                device_id=existing.id,
                device_key=existing.device_key,
                display_name=existing.display_name,
                created=False,
            )

        device = LocalDevice(
            user_id=self._user_id,
            device_key=normalized_key,
            display_name=display_name,
        )
        self._session.add(device)
        self._session.flush()
        device_mirror = self._path_resolver.device_mirror_root(self._user_id, normalized_key)
        device_mirror.mkdir(parents=True, exist_ok=True)
        return LocalDeviceResult(
            device_id=device.id,
            device_key=device.device_key,
            display_name=device.display_name,
            created=True,
        )

    def register_root(
        self,
        device_key: str,
        root_path: str,
        default_policy: str = DEFAULT_LOCAL_POLICY,
        client_source_path: str | None = None,
        ensure_folder_object: bool = True,
        preserve_existing_policy: bool = False,
    ) -> LocalRootResult:
        if default_policy not in LOCAL_POLICIES:
            raise ValidationError(f"unsupported local policy: {default_policy}")
        device = self._get_device(device_key)
        normalized_root = normalize_relative_path(root_path)
        resolved = self._path_resolver.resolve_root_path(
            self._user_id, device.device_key, normalized_root
        )
        resolved.mkdir(parents=True, exist_ok=True)

        existing = self._session.scalar(
            select(LocalRoot).where(
                LocalRoot.user_id == self._user_id,
                LocalRoot.device_id == device.id,
                LocalRoot.root_path == normalized_root,
            )
        )
        if existing is not None:
            if (
                not preserve_existing_policy
                and existing.default_policy != default_policy
            ):
                existing.default_policy = default_policy
                self._session.flush()
            if ensure_folder_object:
                FolderObjectService(self._session, self._user_id).ensure_folder_for_root(
                    device, existing, client_source_path=client_source_path
                )
            return LocalRootResult(
                root_id=existing.id,
                device_key=device.device_key,
                root_path=existing.root_path,
                default_policy=existing.default_policy,
                created=False,
            )

        root = LocalRoot(
            user_id=self._user_id,
            device_id=device.id,
            root_path=normalized_root,
            default_policy=default_policy,
        )
        self._session.add(root)
        self._session.flush()
        if ensure_folder_object:
            FolderObjectService(self._session, self._user_id).ensure_folder_for_root(
                device, root, client_source_path=client_source_path
            )
        return LocalRootResult(
            root_id=root.id,
            device_key=device.device_key,
            root_path=root.root_path,
            default_policy=root.default_policy,
            created=True,
        )

    def get_root_for_user(self, root_id: UUID) -> LocalRoot:
        root = self._session.scalar(
            select(LocalRoot).where(LocalRoot.id == root_id, LocalRoot.user_id == self._user_id)
        )
        if root is None:
            raise NotFoundError("local_root", root_id)
        return root

    def get_device_for_user(self, device_key: str) -> LocalDevice:
        return self._get_device(device_key)

    def _get_device(self, device_key: str) -> LocalDevice:
        normalized_key = device_key.strip()
        device = self._session.scalar(
            select(LocalDevice).where(
                LocalDevice.user_id == self._user_id,
                LocalDevice.device_key == normalized_key,
            )
        )
        if device is None:
            raise NotFoundError("local_device", normalized_key)
        return device
