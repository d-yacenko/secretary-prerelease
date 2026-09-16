"""Download explicit Google Drive file/export bytes."""

from typing import Any

from app.connectors.google.drive_transport import DriveTransport
from app.content_extraction.constants import MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES
from app.content_extraction.format_resolver import ContentExtractionPlan


def fetch_google_drive_content(
    transport: DriveTransport,
    access_token: str,
    metadata: dict[str, Any],
    plan: ContentExtractionPlan,
) -> bytes:
    file_id = str(metadata.get("file_id") or "").strip()
    if not file_id:
        raise ValueError("missing google drive file_id")

    if plan.google_export_mime:
        return transport.export_file(
            access_token,
            file_id,
            plan.google_export_mime,
            max_bytes=MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES,
        )
    return transport.download_file_media(
        access_token,
        file_id,
        max_bytes=MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES,
    )
