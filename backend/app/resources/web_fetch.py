import hashlib
import ipaddress
import re
import socket
from dataclasses import dataclass
from enum import Enum
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from app.content_extraction.bounded_download import (
    DownloadTooLargeError,
    read_bounded_response_body,
)
from app.content_extraction.constants import (
    MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES,
    MAX_EXTRACTED_TEXT_CHARS,
    SUPPORTED_BINARY_SUFFIXES,
)
from app.content_extraction.format_resolver import MIME_SUFFIX_MAP, detect_supported_file_suffix
from app.resources.constants import (
    MAX_WEB_FETCH_BYTES,
    MAX_WEB_REDIRECTS,
    REDIRECT_STATUS_CODES,
    WEB_FETCH_TIMEOUT_SECONDS,
)


class WebFetchError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class WebResourceClass(str, Enum):
    HTML_PAGE = "html_page"
    SUPPORTED_FILE = "supported_file"
    UNSUPPORTED_BINARY = "unsupported_binary"


WEB_CLASSIFY_PREFIX_BYTES = 8192


@dataclass(frozen=True)
class WebFetchResult:
    title: str | None
    text: str
    final_url: str
    content_type: str | None = None
    is_binary: bool = False
    content_hash: str | None = None
    is_direct_file: bool = False
    detected_suffix: str | None = None
    content_length: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    file_too_large: bool = False


TEXTUAL_CONTENT_TYPES = frozenset(
    {
        "text/html",
        "text/plain",
        "application/xhtml+xml",
        "application/xml",
        "text/xml",
        "application/json",
    }
)

BINARY_CONTENT_TYPES = frozenset(
    {
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "application/gzip",
        "application/x-gzip",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
    }
)


def _is_binary_signature(raw: bytes) -> bool:
    if len(raw) < 4:
        return False
    if raw.startswith(b"%PDF"):
        return True
    if raw.startswith(b"PK\x03\x04"):
        return True
    if raw.startswith(bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])):
        return True
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    return bool(raw.startswith(b"\xff\xd8\xff"))


def _is_binary_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    main = content_type.split(";")[0].strip().lower()
    if main in TEXTUAL_CONTENT_TYPES or main.startswith("text/"):
        return False
    if main in BINARY_CONTENT_TYPES:
        return True
    if main.startswith(("image/", "audio/", "video/")):
        return True
    return main.startswith("application/") and main not in {
        "application/json",
        "application/xml",
        "application/xhtml+xml",
    }


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast:
        return True
    if ip.is_reserved or ip.is_unspecified:
        return True
    if ip.is_multicast:
        return True
    return bool(hasattr(ip, "is_global") and not ip.is_global)


def _hostname_literal_blocked(hostname: str) -> bool:
    lowered = hostname.lower().rstrip(".")
    if lowered in {"localhost", "0.0.0.0"} or lowered.endswith(".local"):
        return True
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return _ip_is_blocked(hostname)


def _resolve_host_ips(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise WebFetchError("web url host resolution failed") from exc
    if not infos:
        raise WebFetchError("web url host resolution failed")
    return [info[4][0] for info in infos]


def _validate_url_target(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise WebFetchError("web url must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise WebFetchError("web url credentials are not allowed")
    hostname = parsed.hostname
    if not hostname:
        raise WebFetchError("web url hostname missing")
    if _hostname_literal_blocked(hostname):
        raise WebFetchError("web url host is not allowed")
    for resolved_ip in _resolve_host_ips(hostname):
        if _ip_is_blocked(resolved_ip):
            raise WebFetchError("web url host is not allowed")
    return url.strip()


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed


def _extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    title = unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return title or None


def _extract_text(html: str) -> str:
    stripped = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
    text = unescape(re.sub(r"\s+", " ", stripped)).strip()
    if len(text) > MAX_EXTRACTED_TEXT_CHARS:
        return text[:MAX_EXTRACTED_TEXT_CHARS]
    return text


_HEADER_SUFFIX_TEXT_MIMES = frozenset({"text/plain", "text/markdown"})
_HTML_MIMES = frozenset({"text/html", "application/xhtml+xml"})


def _classify_from_headers(
    content_type: str | None,
    url: str,
) -> tuple[WebResourceClass | None, str | None]:
    mime = content_type.split(";")[0].strip().lower() if content_type else None
    if mime in _HTML_MIMES:
        return None, None
    path_suffix = Path(urlparse(url).path).suffix.lower()
    if mime and mime in MIME_SUFFIX_MAP:
        suffix = MIME_SUFFIX_MAP[mime]
        if suffix in SUPPORTED_BINARY_SUFFIXES:
            if mime in _HEADER_SUFFIX_TEXT_MIMES:
                if path_suffix == suffix:
                    return WebResourceClass.SUPPORTED_FILE, suffix
            else:
                return WebResourceClass.SUPPORTED_FILE, suffix
    if path_suffix in SUPPORTED_BINARY_SUFFIXES:
        return WebResourceClass.SUPPORTED_FILE, path_suffix
    return None, None


def _classify_resource(
    content_type: str | None,
    content_length: int | None,
    prefix: bytes,
    url: str,
) -> tuple[WebResourceClass, str | None]:
    mime = content_type.split(";")[0].strip().lower() if content_type else None
    if mime in _HTML_MIMES:
        return WebResourceClass.HTML_PAGE, None

    detected_suffix = detect_supported_file_suffix(
        content_type=content_type,
        prefix=prefix,
        url=url,
    )
    if detected_suffix is not None:
        if mime and mime in MIME_SUFFIX_MAP:
            if mime in _HEADER_SUFFIX_TEXT_MIMES:
                path_suffix = Path(urlparse(url).path).suffix.lower()
                if path_suffix == MIME_SUFFIX_MAP[mime]:
                    return WebResourceClass.SUPPORTED_FILE, detected_suffix
            else:
                return WebResourceClass.SUPPORTED_FILE, detected_suffix
        path_suffix = Path(urlparse(url).path).suffix.lower()
        if path_suffix in SUPPORTED_BINARY_SUFFIXES:
            return WebResourceClass.SUPPORTED_FILE, detected_suffix
        if _is_binary_signature(prefix):
            return WebResourceClass.SUPPORTED_FILE, detected_suffix

    is_binary = _is_binary_content_type(content_type) or _is_binary_signature(prefix)
    if not is_binary:
        return WebResourceClass.HTML_PAGE, None

    if detected_suffix is not None:
        return WebResourceClass.SUPPORTED_FILE, detected_suffix
    return WebResourceClass.UNSUPPORTED_BINARY, None


_PROBE_CHUNK_SIZE = 4096


def _consume_response_body(
    response: httpx.Response,
    current_url: str,
    content_type: str | None,
    content_length: int | None,
) -> tuple[WebResourceClass, str | None, list[bytes]]:
    header_class, header_suffix = _classify_from_headers(content_type, current_url)
    if header_class == WebResourceClass.SUPPORTED_FILE:
        return header_class, header_suffix, []

    prefix_buf = bytearray()
    chunks: list[bytes] = []
    classified = False
    resource_class = WebResourceClass.HTML_PAGE
    detected_suffix: str | None = None
    total_html = 0

    for chunk in response.iter_bytes(chunk_size=_PROBE_CHUNK_SIZE):
        if not chunk:
            continue
        if not classified:
            prefix_buf.extend(chunk)
            if len(prefix_buf) >= WEB_CLASSIFY_PREFIX_BYTES:
                prefix = bytes(prefix_buf[:WEB_CLASSIFY_PREFIX_BYTES])
                resource_class, detected_suffix = _classify_resource(
                    content_type,
                    content_length,
                    prefix,
                    current_url,
                )
                classified = True
                if resource_class != WebResourceClass.HTML_PAGE:
                    break
                chunks = [bytes(prefix_buf)]
                total_html = len(prefix_buf)
        else:
            total_html += len(chunk)
            if total_html > MAX_WEB_FETCH_BYTES:
                raise WebFetchError("web fetch exceeded size limit")
            chunks.append(chunk)

    if not classified:
        prefix = bytes(prefix_buf)
        resource_class, detected_suffix = _classify_resource(
            content_type,
            content_length,
            prefix,
            current_url,
        )
        if resource_class == WebResourceClass.HTML_PAGE:
            chunks = [prefix] if prefix else []
        else:
            chunks = []

    return resource_class, detected_suffix, chunks


def _response_metadata(response: httpx.Response) -> tuple[str | None, int | None, str | None, str | None]:
    content_type = response.headers.get("Content-Type") or response.headers.get("content-type")
    content_length = _parse_content_length(
        response.headers.get("Content-Length") or response.headers.get("content-length")
    )
    etag = response.headers.get("ETag") or response.headers.get("etag")
    last_modified = response.headers.get("Last-Modified") or response.headers.get("last-modified")
    return content_type, content_length, etag, last_modified


def _process_final_response(response: httpx.Response, current_url: str) -> WebFetchResult:
    if response.status_code >= 400:
        raise WebFetchError(f"web fetch failed with status {response.status_code}")

    content_type, content_length, etag, last_modified = _response_metadata(response)
    resource_class, detected_suffix, chunks = _consume_response_body(
        response,
        current_url,
        content_type,
        content_length,
    )

    if resource_class == WebResourceClass.SUPPORTED_FILE:
        too_large = (
            content_length is not None
            and content_length > MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES
        )
        return WebFetchResult(
            title=None,
            text="",
            final_url=current_url,
            content_type=content_type,
            is_binary=True,
            is_direct_file=True,
            detected_suffix=detected_suffix,
            content_length=content_length,
            etag=etag,
            last_modified=last_modified,
            file_too_large=too_large,
        )

    if resource_class == WebResourceClass.UNSUPPORTED_BINARY:
        raw = b"".join(chunks)
        content_hash = hashlib.sha256(raw).hexdigest() if raw else None
        return WebFetchResult(
            title=None,
            text="",
            final_url=current_url,
            content_type=content_type,
            is_binary=True,
            content_hash=content_hash,
            content_length=content_length,
            etag=etag,
            last_modified=last_modified,
        )

    raw = b"".join(chunks)
    content_hash = hashlib.sha256(raw).hexdigest() if raw else None
    html = raw.decode("utf-8", errors="replace")
    title = _extract_title(html)
    text = _extract_text(html)
    if not text:
        text = title or current_url
    return WebFetchResult(
        title=title,
        text=text,
        final_url=current_url,
        content_type=content_type,
        is_binary=False,
        content_hash=content_hash,
        content_length=content_length,
        etag=etag,
        last_modified=last_modified,
    )


def _public_http_request(
    url: str,
    *,
    process_response,
) -> object:
    current_url = _validate_url_target(url)
    with httpx.Client(timeout=WEB_FETCH_TIMEOUT_SECONDS, follow_redirects=False) as client:
        for redirect_hop in range(MAX_WEB_REDIRECTS + 1):
            try:
                with client.stream("GET", current_url) as response:
                    if response.status_code in REDIRECT_STATUS_CODES:
                        if redirect_hop >= MAX_WEB_REDIRECTS:
                            raise WebFetchError("web fetch redirect limit exceeded")
                        location = response.headers.get("Location") or response.headers.get(
                            "location"
                        )
                        if not location:
                            raise WebFetchError("web fetch redirect missing location")
                        current_url = _validate_url_target(urljoin(current_url, location))
                        continue
                    return process_response(response, current_url)
            except httpx.TimeoutException as exc:
                raise WebFetchError("web fetch timed out") from exc
            except httpx.RequestError as exc:
                raise WebFetchError("web fetch request failed") from exc
        raise WebFetchError("web fetch redirect limit exceeded")


def fetch_web_page(url: str) -> WebFetchResult:
    return _public_http_request(url, process_response=_process_final_response)


def download_public_web_file(url: str, *, max_bytes: int = MAX_EXPLICIT_CLOUD_DOWNLOAD_BYTES) -> bytes:
    def _download(response: httpx.Response, current_url: str) -> bytes:
        if response.status_code >= 400:
            raise WebFetchError(f"web fetch failed with status {response.status_code}")
        try:
            return read_bounded_response_body(response, max_bytes)
        except DownloadTooLargeError as exc:
            raise WebFetchError("web file exceeded download size limit") from exc

    return _public_http_request(url, process_response=_download)
