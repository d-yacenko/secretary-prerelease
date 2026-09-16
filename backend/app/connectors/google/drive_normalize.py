from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

from app.connectors.google.constants import (
    GOOGLE_DRIVE_FOLDER_MIME,
    GOOGLE_DRIVE_MAX_PARENTS,
    GOOGLE_DRIVE_PROVIDER,
)


def build_canonical_uri(file_id: str) -> str:
    return f"https://drive.google.com/open?id={quote(file_id, safe='')}"


def _parse_drive_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _bounded_parents(parents: list[str] | None) -> list[str]:
    if not parents:
        return []
    bounded: list[str] = []
    for parent in parents[:GOOGLE_DRIVE_MAX_PARENTS]:
        parent_id = str(parent).strip()
        if parent_id:
            bounded.append(parent_id)
    return bounded


def drive_kind_for_mime(mime_type: str | None) -> str:
    if mime_type == GOOGLE_DRIVE_FOLDER_MIME:
        return "folder"
    return "file"


def normalize_drive_file(
    file: dict[str, Any],
    account_id: UUID,
    intake_mode: str | None = None,
) -> dict[str, Any] | None:
    file_id = str(file.get("id") or "").strip()
    if not file_id:
        return None

    mime_type = file.get("mimeType")
    mime_str = str(mime_type) if mime_type is not None else None
    created_time = file.get("createdTime")
    modified_time = file.get("modifiedTime")
    size = file.get("size")
    md5_checksum = file.get("md5Checksum")
    parents_raw = file.get("parents")
    parents = _bounded_parents(parents_raw if isinstance(parents_raw, list) else None)
    drive_id = file.get("driveId")
    web_view_link = file.get("webViewLink")

    version = file.get("version")
    metadata: dict[str, Any] = {
        "account_id": str(account_id),
        "file_id": file_id,
        "mime_type": mime_str,
        "created_time": str(created_time) if created_time is not None else None,
        "modified_time": str(modified_time) if modified_time is not None else None,
        "size": int(size) if size is not None else None,
        "md5_checksum": str(md5_checksum) if md5_checksum is not None else None,
        "version": str(version) if version is not None else None,
        "parents": parents,
        "drive_id": str(drive_id) if drive_id is not None else None,
        "web_view_link": str(web_view_link) if web_view_link is not None else None,
    }
    if intake_mode is not None:
        metadata["intake_mode"] = intake_mode

    title = str(file.get("name") or f"Drive file {file_id}")
    occurred_at = _parse_drive_datetime(
        str(modified_time) if modified_time is not None else None
    )

    return {
        "external_id": file_id,
        "kind": drive_kind_for_mime(mime_str),
        "provider": GOOGLE_DRIVE_PROVIDER,
        "origin": "source",
        "state": "observed",
        "title": title,
        "body": None,
        "occurred_at": occurred_at,
        "canonical_uri": build_canonical_uri(file_id),
        "metadata": metadata,
        "trashed": bool(file.get("trashed")),
    }
