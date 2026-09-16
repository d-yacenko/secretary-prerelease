from typing import Any

import httpx

from app.connectors.yandex.constants import YANDEX_DISK_API_BASE, YANDEX_DISK_PUBLIC_RESOURCE_FIELDS
from app.connectors.yandex.disk_api_errors import raise_for_yandex_disk_response
from app.content_extraction.trusted_download import bounded_get_safe_redirects


class YandexDiskTransport:
    def __init__(self, http_client: httpx.Client | None = None, timeout: float = 30.0) -> None:
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()

    def get_public_resource_metadata(self, public_key: str) -> dict[str, Any]:
        response = self._http.get(
            f"{YANDEX_DISK_API_BASE}/public/resources",
            params={
                "public_key": public_key,
                "fields": YANDEX_DISK_PUBLIC_RESOURCE_FIELDS,
            },
        )
        raise_for_yandex_disk_response(response, "get_public_resource_metadata")
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("yandex disk public resource response invalid")
        return payload

    def get_public_resource_download_url(self, public_key: str) -> str:
        response = self._http.get(
            f"{YANDEX_DISK_API_BASE}/public/resources/download",
            params={"public_key": public_key},
        )
        raise_for_yandex_disk_response(response, "get_public_resource_download_url")
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("yandex disk download response invalid")
        href = payload.get("href")
        if not href or not isinstance(href, str):
            raise ValueError("yandex disk download href missing")
        return href

    def download_bounded_url(self, url: str, *, max_bytes: int) -> bytes:
        return bounded_get_safe_redirects(self._http, url, max_bytes=max_bytes)
