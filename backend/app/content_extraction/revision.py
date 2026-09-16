"""Provider content revision derivation for explicit cloud resources."""

import hashlib
from typing import Any

from app.connectors.google.constants import (
    GOOGLE_DRIVE_FOLDER_MIME,
    GOOGLE_DRIVE_PROVIDER,
)
from app.connectors.yandex.constants import YANDEX_DISK_PROVIDER
from app.content_extraction.constants import EXTRACTION_VERSION
from app.content_extraction.metadata_keys import CONTENT_EXTRACTION_VERSION
from app.resources.constants import PROVIDER_GOOGLE_DRIVE, PROVIDER_WEB, PROVIDER_YANDEX_DISK


def derive_google_drive_content_revision(metadata: dict[str, Any]) -> str | None:
    mime = metadata.get("mime_type")
    if mime == GOOGLE_DRIVE_FOLDER_MIME:
        return None
    md5 = metadata.get("md5_checksum")
    if md5:
        return f"gdrive:md5:{md5}"
    file_id = metadata.get("file_id")
    mime = metadata.get("mime_type")
    version = metadata.get("version")
    if (
        file_id
        and version
        and mime
        and str(mime).startswith("application/vnd.google-apps.")
        and mime != GOOGLE_DRIVE_FOLDER_MIME
    ):
        return f"gdrive:version:{file_id}:{version}"
    modified = metadata.get("modified_time")
    size = metadata.get("size")
    file_id = metadata.get("file_id")
    if file_id and modified is not None:
        size_part = str(size) if size is not None else "unknown"
        return f"gdrive:fallback:{file_id}:{modified}:{size_part}"
    return None


def derive_yandex_disk_content_revision(metadata: dict[str, Any]) -> str | None:
    if metadata.get("resource_type") == "dir":
        return None
    md5 = metadata.get("md5")
    if md5:
        return f"yandex:md5:{md5}"
    resource_id = metadata.get("resource_id")
    modified = metadata.get("modified_time")
    size = metadata.get("size")
    revision = metadata.get("revision")
    if resource_id and modified is not None:
        parts = [str(resource_id), str(modified), str(size or ""), str(revision or "")]
        digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]
        return f"yandex:fallback:{digest}"
    return None


def derive_web_content_revision(metadata: dict[str, Any]) -> str | None:
    remote = derive_web_remote_content_revision(metadata)
    if remote is not None:
        return remote
    content_hash = metadata.get("content_hash")
    if content_hash:
        return f"web:sha256:{content_hash}"
    return None


def derive_web_remote_content_revision(metadata: dict[str, Any]) -> str | None:
    etag = metadata.get("etag")
    if etag:
        return f"web:etag:{etag}"
    last_modified = metadata.get("last_modified")
    content_length = metadata.get("content_length")
    if last_modified is not None and content_length is not None:
        return f"web:lm-cl:{last_modified}:{content_length}"
    return None


def derive_explicit_cloud_content_revision(provider: str, metadata: dict[str, Any]) -> str | None:
    if provider == PROVIDER_GOOGLE_DRIVE or provider == GOOGLE_DRIVE_PROVIDER:
        return derive_google_drive_content_revision(metadata)
    if provider == PROVIDER_YANDEX_DISK or provider == YANDEX_DISK_PROVIDER:
        return derive_yandex_disk_content_revision(metadata)
    if provider == PROVIDER_WEB:
        return derive_web_content_revision(metadata)
    return None


def extraction_version_marker() -> str:
    return EXTRACTION_VERSION


def metadata_extraction_version(metadata: dict[str, Any]) -> str | None:
    value = metadata.get(CONTENT_EXTRACTION_VERSION)
    return str(value) if value is not None else None


def content_pipeline_complete(
    metadata: dict[str, Any],
    content_revision: str,
) -> bool:
    from app.content_extraction.metadata_keys import (
        CONTENT_EXTRACTION_STATUS,
        STATUS_READY,
    )
    from app.services.correlation_constants import SEMANTIC_SUMMARY_REVISION_KEY

    if metadata.get("content_revision") != content_revision:
        return False
    if metadata.get(CONTENT_EXTRACTION_STATUS) != STATUS_READY:
        return False
    if metadata_extraction_version(metadata) != EXTRACTION_VERSION:
        return False
    return metadata.get(SEMANTIC_SUMMARY_REVISION_KEY) == content_revision
