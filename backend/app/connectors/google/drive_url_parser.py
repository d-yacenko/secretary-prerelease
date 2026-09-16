import re
from urllib.parse import parse_qs, urlparse

from app.services.explicit_link_intake_errors import ExplicitLinkIntakeError

_ALLOWED_HOSTS = frozenset({"drive.google.com", "docs.google.com"})
GOOGLE_DRIVE_URL_HOSTS = _ALLOWED_HOSTS
_FILE_PATH_RE = re.compile(r"(?:/u/\d+)?/file/d/([^/?#]+)")
_FOLDER_PATH_RE = re.compile(r"(?:/u/\d+)?/drive/folders/([^/?#]+)")
_DOCS_PATH_RE = re.compile(r"/(?:document|spreadsheets|presentation)/d/([^/?#]+)")


def parse_google_drive_file_id(url: str) -> str:
    raw = url.strip()
    if not raw:
        raise ExplicitLinkIntakeError("invalid link url")

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ExplicitLinkIntakeError("unsupported link url")
    if parsed.username or parsed.password:
        raise ExplicitLinkIntakeError("unsupported link url")

    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise ExplicitLinkIntakeError("unsupported link url")

    path = parsed.path or ""
    for pattern in (_FILE_PATH_RE, _FOLDER_PATH_RE, _DOCS_PATH_RE):
        match = pattern.search(path)
        if match:
            file_id = match.group(1).strip()
            if file_id:
                return file_id
            raise ExplicitLinkIntakeError("invalid link url")

    if host == "drive.google.com" and path.rstrip("/").endswith("/open"):
        query_ids = parse_qs(parsed.query).get("id")
        if query_ids and str(query_ids[0]).strip():
            return str(query_ids[0]).strip()
        raise ExplicitLinkIntakeError("invalid link url")

    raise ExplicitLinkIntakeError("unsupported link url")
