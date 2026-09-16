"""Bounded streaming download helpers for explicit cloud resources."""

import httpx

from app.content_extraction.constants import MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES


class DownloadTooLargeError(Exception):
    def __init__(self, received: int, limit: int) -> None:
        self.received = received
        self.limit = limit
        super().__init__(f"download exceeded {limit} bytes (received {received})")


def read_bounded_response_body(response: httpx.Response, max_bytes: int) -> bytes:
    limit = min(max_bytes, MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES)
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise DownloadTooLargeError(total, limit)
        chunks.append(chunk)
    return b"".join(chunks)


def bounded_get(
    http: httpx.Client,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_bytes: int = MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES,
    follow_redirects: bool = False,
) -> bytes:
    with http.stream(
        "GET",
        url,
        headers=headers or {},
        follow_redirects=follow_redirects,
    ) as response:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = None
            if declared is not None and declared > max_bytes:
                raise DownloadTooLargeError(declared, max_bytes)
        return read_bounded_response_body(response, max_bytes)
