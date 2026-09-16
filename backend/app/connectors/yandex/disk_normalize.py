from datetime import datetime
from typing import Any

from app.connectors.yandex.constants import YANDEX_DISK_PROVIDER


def _parse_yandex_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def yandex_disk_kind_for_type(resource_type: str | None) -> str:
    if resource_type == "dir":
        return "folder"
    return "file"


def normalize_yandex_disk_resource(
    resource: dict[str, Any],
    intake_url: str,
    intake_mode: str | None = None,
) -> dict[str, Any] | None:
    resource_id = str(resource.get("resource_id") or "").strip()
    if not resource_id:
        return None

    resource_type = resource.get("type")
    resource_type_str = str(resource_type) if resource_type is not None else None
    created = resource.get("created")
    modified = resource.get("modified")
    size = resource.get("size")
    mime_type = resource.get("mime_type")
    md5 = resource.get("md5")
    sha256 = resource.get("sha256")
    revision = resource.get("revision")
    path = resource.get("path")
    public_url = resource.get("public_url")
    media_type = resource.get("media_type")

    metadata: dict[str, Any] = {
        "resource_id": resource_id,
        "resource_type": resource_type_str,
        "created_time": str(created) if created is not None else None,
        "modified_time": str(modified) if modified is not None else None,
        "size": int(size) if size is not None else None,
        "mime_type": str(mime_type) if mime_type is not None else None,
        "md5": str(md5) if md5 is not None else None,
        "sha256": str(sha256) if sha256 is not None else None,
        "revision": str(revision) if revision is not None else None,
        "path": str(path) if path is not None else None,
        "public_url": str(public_url) if public_url is not None else None,
        "intake_url": intake_url,
    }
    if media_type is not None:
        metadata["media_type"] = str(media_type)
    if intake_mode is not None:
        metadata["intake_mode"] = intake_mode

    title = str(resource.get("name") or f"Yandex Disk {resource_id}")
    occurred_at = _parse_yandex_datetime(
        str(modified) if modified is not None else None
    )
    canonical_uri = (
        str(public_url) if public_url is not None else intake_url
    )

    return {
        "external_id": resource_id,
        "kind": yandex_disk_kind_for_type(resource_type_str),
        "provider": YANDEX_DISK_PROVIDER,
        "origin": "source",
        "state": "observed",
        "title": title,
        "body": None,
        "occurred_at": occurred_at,
        "canonical_uri": canonical_uri,
        "metadata": metadata,
    }
