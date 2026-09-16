"""Download explicit public web file bytes for mechanical extraction."""

from typing import Any

from app.content_extraction.format_resolver import ContentExtractionPlan
from app.resources.web_fetch import WebFetchError, download_public_web_file


def fetch_web_public_content(
    metadata: dict[str, Any],
    plan: ContentExtractionPlan,
) -> bytes:
    url = (
        metadata.get("final_url")
        or metadata.get("canonical_uri")
        or metadata.get("requested_url")
        or metadata.get("normalized_requested_url")
    )
    if not url:
        raise ValueError("missing public web download url")
    try:
        return download_public_web_file(str(url))
    except WebFetchError as exc:
        if "download size limit" in exc.message:
            from app.content_extraction.bounded_download import DownloadTooLargeError

            raise DownloadTooLargeError(0, 0) from exc
        raise ValueError(exc.message) from exc
