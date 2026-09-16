"""Resolve explicit cloud resource content format and extraction eligibility."""

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.connectors.google.constants import (
    GOOGLE_DRIVE_PROVIDER,
)
from app.connectors.yandex.constants import YANDEX_DISK_PROVIDER
from app.content_extraction.constants import SUPPORTED_BINARY_SUFFIXES
from app.resources.constants import PROVIDER_WEB

GOOGLE_APPS_DOCUMENT = "application/vnd.google-apps.document"
GOOGLE_APPS_SPREADSHEET = "application/vnd.google-apps.spreadsheet"
GOOGLE_APPS_PRESENTATION = "application/vnd.google-apps.presentation"

MIME_SUFFIX_MAP = {
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/x-parquet": ".parquet",
    "application/parquet": ".parquet",
}


class ContentExtractionPlan:
    def __init__(
        self,
        eligible: bool,
        status: str,
        content_format: str | None = None,
        suffix: str | None = None,
        google_export_mime: str | None = None,
    ) -> None:
        self.eligible = eligible
        self.status = status
        self.content_format = content_format
        self.suffix = suffix
        self.google_export_mime = google_export_mime


def _suffix_from_title(title: str | None) -> str:
    if not title:
        return ""
    return Path(title).suffix.lower()


def _suffix_from_url(url: str | None) -> str:
    if not url:
        return ""
    return Path(urlparse(url).path).suffix.lower()


def _mime_to_supported_suffix(mime: str | None) -> str | None:
    if not mime:
        return None
    mime_main = mime.split(";")[0].strip().lower()
    suffix = MIME_SUFFIX_MAP.get(mime_main)
    if suffix and suffix in SUPPORTED_BINARY_SUFFIXES:
        return suffix
    return None


def _resolve_supported_suffix(
    *,
    title: str | None = None,
    url: str | None = None,
    mime_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    title_suffix = _suffix_from_title(title)
    if not title_suffix and metadata:
        title_suffix = _suffix_from_title(metadata.get("filename"))
    if not title_suffix:
        title_suffix = _suffix_from_url(url)

    mime_suffix = _mime_to_supported_suffix(mime_type)
    if mime_suffix is None and metadata:
        detected = metadata.get("detected_suffix")
        if detected and str(detected) in SUPPORTED_BINARY_SUFFIXES:
            mime_suffix = str(detected)
        else:
            mime_suffix = _mime_to_supported_suffix(
                str(metadata.get("mime_type") or metadata.get("content_format") or "")
            )

    title_supported = title_suffix in SUPPORTED_BINARY_SUFFIXES
    mime_supported = mime_suffix is not None

    if title_supported and mime_supported and title_suffix != mime_suffix:
        return None
    if title_supported:
        return title_suffix
    if mime_supported:
        return mime_suffix
    return None


def detect_supported_file_suffix(
    *,
    content_type: str | None,
    prefix: bytes,
    url: str | None = None,
    title: str | None = None,
) -> str | None:
    if prefix.startswith(b"%PDF"):
        mime_suffix = _mime_to_supported_suffix(content_type)
        title_suffix = _suffix_from_title(title) or _suffix_from_url(url)
        if title_suffix == ".pdf" or mime_suffix == ".pdf":
            if title_suffix == ".pdf" and mime_suffix and mime_suffix != ".pdf":
                return None
            if mime_suffix == ".pdf" and title_suffix and title_suffix != ".pdf":
                return None
            return ".pdf"

    mime_suffix = _mime_to_supported_suffix(content_type)
    title_suffix = _suffix_from_title(title) or _suffix_from_url(url)
    title_supported = title_suffix in SUPPORTED_BINARY_SUFFIXES

    if title_supported and mime_suffix and title_suffix != mime_suffix:
        return None
    if mime_suffix:
        return mime_suffix
    if title_supported:
        return title_suffix

    if prefix.startswith(b"PK\x03\x04"):
        return None
    return None


def _suffix_from_metadata(metadata: dict[str, Any]) -> str:
    return _resolve_supported_suffix(metadata=metadata) or ""


def resolve_content_extraction_plan(
    provider: str,
    kind: str,
    metadata: dict[str, Any],
    title: str | None = None,
) -> ContentExtractionPlan:
    if kind == "folder":
        return ContentExtractionPlan(
            eligible=False,
            status="metadata_only",
            content_format="folder",
        )

    if provider in {GOOGLE_DRIVE_PROVIDER, "google_drive"}:
        return _resolve_google_plan(metadata, title)
    if provider in {YANDEX_DISK_PROVIDER, "yandex_disk"}:
        return _resolve_yandex_plan(metadata, title)
    if provider in {PROVIDER_WEB, "web"}:
        return _resolve_web_plan(metadata, title)

    return ContentExtractionPlan(eligible=False, status="unsupported")


def _resolve_google_plan(metadata: dict[str, Any], title: str | None) -> ContentExtractionPlan:
    mime = metadata.get("mime_type")
    mime_str = str(mime) if mime is not None else None

    if mime_str == GOOGLE_APPS_DOCUMENT:
        return ContentExtractionPlan(
            eligible=True,
            status="pending",
            content_format="google_docs",
            suffix=".txt",
            google_export_mime="text/plain",
        )
    if mime_str == GOOGLE_APPS_SPREADSHEET:
        return ContentExtractionPlan(
            eligible=True,
            status="pending",
            content_format="google_sheets",
            suffix=".xlsx",
            google_export_mime=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
    if mime_str == GOOGLE_APPS_PRESENTATION:
        return ContentExtractionPlan(
            eligible=True,
            status="pending",
            content_format="google_slides",
            suffix=".pptx",
            google_export_mime=(
                "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            ),
        )

    suffix = _resolve_supported_suffix(title=title, mime_type=mime_str, metadata=metadata)
    if suffix in SUPPORTED_BINARY_SUFFIXES:
        return ContentExtractionPlan(
            eligible=True,
            status="pending",
            content_format=f"binary:{suffix}",
            suffix=suffix,
        )
    return ContentExtractionPlan(
        eligible=False,
        status="unsupported",
        content_format=mime_str or "unknown",
    )


def _resolve_yandex_plan(metadata: dict[str, Any], title: str | None) -> ContentExtractionPlan:
    if metadata.get("resource_type") == "dir":
        return ContentExtractionPlan(
            eligible=False,
            status="metadata_only",
            content_format="folder",
        )
    suffix = _resolve_supported_suffix(
        title=title,
        mime_type=str(metadata.get("mime_type") or ""),
        metadata=metadata,
    )
    if suffix in SUPPORTED_BINARY_SUFFIXES:
        return ContentExtractionPlan(
            eligible=True,
            status="pending",
            content_format=f"binary:{suffix}",
            suffix=suffix,
        )
    return ContentExtractionPlan(
        eligible=False,
        status="unsupported",
        content_format=str(metadata.get("mime_type") or "unknown"),
    )


def _resolve_web_plan(metadata: dict[str, Any], title: str | None) -> ContentExtractionPlan:
    suffix = _resolve_supported_suffix(
        title=title,
        mime_type=str(metadata.get("mime_type") or metadata.get("content_format") or ""),
        metadata=metadata,
    )
    if suffix in SUPPORTED_BINARY_SUFFIXES:
        return ContentExtractionPlan(
            eligible=True,
            status="pending",
            content_format=f"binary:{suffix}",
            suffix=suffix,
        )
    return ContentExtractionPlan(
        eligible=False,
        status="unsupported",
        content_format=str(metadata.get("mime_type") or metadata.get("content_format") or "unknown"),
    )
