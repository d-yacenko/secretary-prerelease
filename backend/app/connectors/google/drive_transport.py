from typing import Any
from urllib.parse import quote

import httpx

from app.connectors.google.api_errors import raise_for_google_response
from app.connectors.google.constants import DRIVE_API_BASE, DRIVE_FILE_METADATA_FIELDS
from app.content_extraction.bounded_download import read_bounded_response_body


class DriveTransport:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.Client(timeout=30.0)

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()

    def get_file_metadata(self, access_token: str, file_id: str) -> dict[str, Any]:
        encoded_file_id = quote(file_id, safe="")
        response = self._http.get(
            f"{DRIVE_API_BASE}/files/{encoded_file_id}",
            params={
                "fields": DRIVE_FILE_METADATA_FIELDS,
                "supportsAllDrives": "true",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        raise_for_google_response(response, "get_file_metadata")
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("drive file metadata response invalid")
        return payload

    def export_file(
        self,
        access_token: str,
        file_id: str,
        export_mime: str,
        *,
        max_bytes: int,
    ) -> bytes:
        encoded_file_id = quote(file_id, safe="")
        with self._http.stream(
            "GET",
            f"{DRIVE_API_BASE}/files/{encoded_file_id}/export",
            params={"mimeType": export_mime},
            headers={"Authorization": f"Bearer {access_token}"},
            follow_redirects=False,
        ) as response:
            raise_for_google_response(response, "export_file")
            return read_bounded_response_body(response, max_bytes)

    def download_file_media(
        self,
        access_token: str,
        file_id: str,
        *,
        max_bytes: int,
    ) -> bytes:
        encoded_file_id = quote(file_id, safe="")
        with self._http.stream(
            "GET",
            f"{DRIVE_API_BASE}/files/{encoded_file_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            follow_redirects=False,
        ) as response:
            raise_for_google_response(response, "download_file_media")
            return read_bounded_response_body(response, max_bytes)
