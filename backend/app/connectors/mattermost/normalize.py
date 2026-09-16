import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import UUID

from app.connectors.mattermost.constants import (
    MAX_FILE_IDS_IN_METADATA,
    MAX_MENTIONED_USER_IDS_IN_METADATA,
    MAX_MESSAGE_BODY_CHARS,
    MAX_TITLE_CHARS,
    MENTION_ID_INSPECT_LIMIT,
)
from app.connectors.mattermost.errors import MattermostSecurityError


def normalize_server_url(server_url: str) -> str:
    raw = server_url.strip()
    if not raw:
        raise MattermostSecurityError("mattermost server_url is required")

    parsed = urlparse(raw)
    if parsed.username or parsed.password:
        raise MattermostSecurityError("mattermost server_url must not include userinfo")
    if parsed.query:
        raise MattermostSecurityError("mattermost server_url must not include query parameters")
    if parsed.fragment:
        raise MattermostSecurityError("mattermost server_url must not include a fragment")

    scheme = (parsed.scheme or "").lower()
    if scheme != "https":
        raise MattermostSecurityError("mattermost server_url must use https")

    host = parsed.hostname
    if not host:
        raise MattermostSecurityError("mattermost server_url must include a host")

    port = parsed.port
    netloc = host
    if port is not None:
        netloc = f"{host}:{port}"

    path = parsed.path or ""
    if path == "/":
        path = ""
    else:
        path = path.rstrip("/")

    return urlunparse(("https", netloc, path, "", "", ""))


def parse_allowed_base_urls(raw: str) -> frozenset[str]:
    if not raw.strip():
        return frozenset()
    values: set[str] = set()
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        values.add(normalize_server_url(candidate))
    return frozenset(values)


def validate_server_url_allowlist(server_url: str, allowed_urls: frozenset[str]) -> str:
    if not allowed_urls:
        raise MattermostSecurityError("mattermost connector is not configured")
    normalized = normalize_server_url(server_url)
    if normalized not in allowed_urls:
        raise MattermostSecurityError("mattermost server_url is not allowlisted")
    return normalized


def build_external_id(normalized_server_url: str, post_id: str) -> str:
    return f"{normalized_server_url}|{post_id}"


def _first_meaningful_line(message: str) -> str:
    for line in message.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:MAX_TITLE_CHARS]
    stripped = message.strip()
    if stripped:
        return stripped[:MAX_TITLE_CHARS]
    return "message"


def _bounded_body(message: str) -> str | None:
    stripped = message.strip()
    if not stripped:
        return None
    if len(stripped) <= MAX_MESSAGE_BODY_CHARS:
        return stripped
    return stripped[:MAX_MESSAGE_BODY_CHARS]


def _author_label(author: dict[str, Any] | None) -> str | None:
    if not author:
        return None
    display_name = str(author.get("display_name") or "").strip()
    if display_name:
        return display_name
    username = str(author.get("username") or "").strip()
    if username:
        return username
    return None


def _build_title(message: str, author: dict[str, Any] | None) -> str:
    line = _first_meaningful_line(message)
    author_label = _author_label(author)
    if author_label:
        title = f"{author_label}: {line}"
    else:
        title = f"Mattermost: {line}"
    if len(title) > MAX_TITLE_CHARS:
        return title[:MAX_TITLE_CHARS]
    return title


def _bounded_file_ids(file_ids: list[Any] | None) -> list[str]:
    if not file_ids:
        return []
    bounded: list[str] = []
    for item in file_ids:
        if len(bounded) >= MAX_FILE_IDS_IN_METADATA:
            break
        value = str(item).strip()
        if value:
            bounded.append(value)
    return bounded


def _bounded_mention_ids(post: dict[str, Any]) -> tuple[list[str], bool]:
    bounded: list[str] = []
    seen: set[str] = set()
    truncated = False
    for raw_seen, item in enumerate(_iter_mention_items(post), start=1):
        if len(bounded) >= MAX_MENTIONED_USER_IDS_IN_METADATA:
            truncated = True
            break
        token = _mention_token(item)
        if token is not None and token not in seen:
            seen.add(token)
            bounded.append(token)
        if raw_seen >= MENTION_ID_INSPECT_LIMIT:
            truncated = True
            break
    return bounded, truncated


def _iter_mention_items(post: dict[str, Any]):
    for raw in _mention_source_values(post):
        yield from _iter_mention_source(raw)


def _mention_source_values(post: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    props = post.get("props")
    if isinstance(props, dict):
        values.append(props.get("mentions"))
        values.append(props.get("mentioned_users"))
    metadata = post.get("metadata")
    if isinstance(metadata, dict):
        values.append(metadata.get("mentions"))
    values.append(post.get("mention_ids"))
    return values


def _iter_mention_source(value: Any, depth: int = 0):
    if value is None or depth > 2:
        return
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except (TypeError, ValueError):
                yield stripped
                return
            yield from _iter_mention_source(parsed, depth + 1)
            return
        yield stripped
        return
    if isinstance(value, dict):
        yield value
        return
    iterator = None
    if not isinstance(value, (bytes, bytearray)):
        try:
            iterator = iter(value)
        except TypeError:
            return
    if iterator is None:
        return
    for item in iterator:
        yield from _iter_mention_source(item, depth + 1)


def _mention_token(item: Any) -> str | None:
    if isinstance(item, str):
        stripped = item.strip()
        return stripped or None
    if isinstance(item, dict):
        user_id = item.get("user_id") or item.get("id")
        if isinstance(user_id, str) and user_id.strip():
            return user_id.strip()
    return None


def create_at_to_datetime(create_at_ms: int) -> datetime:
    return datetime.fromtimestamp(create_at_ms / 1000.0, tz=UTC)


@dataclass(frozen=True)
class MattermostChannelContext:
    channel_id: str
    channel_name: str | None
    channel_display_name: str | None
    channel_type: str | None
    team_id: str | None
    team_name: str | None
    team_display_name: str | None


def should_skip_post(post: dict[str, Any]) -> bool:
    post_type = str(post.get("type") or "")
    if post_type.startswith("system_"):
        return True
    message = str(post.get("message") or "")
    file_ids = post.get("file_ids") or []
    return bool(not message.strip() and not file_ids)


def normalize_mattermost_post(
    post: dict[str, Any],
    normalized_server_url: str,
    account_id: UUID,
    channel: MattermostChannelContext,
    author: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if should_skip_post(post):
        return None

    post_id = str(post.get("id") or "").strip()
    if not post_id:
        return None

    message = str(post.get("message") or "")
    create_at_ms = int(post.get("create_at") or 0)
    update_at_ms = int(post.get("update_at") or 0)
    file_ids = _bounded_file_ids(post.get("file_ids"))
    mentioned_user_ids, mentions_truncated = _bounded_mention_ids(post)
    root_id = str(post.get("root_id") or "").strip() or None

    metadata: dict[str, Any] = {
        "server_url": normalized_server_url,
        "account_id": str(account_id),
        "post_id": post_id,
        "channel_id": channel.channel_id,
        "channel_name": channel.channel_name,
        "channel_display_name": channel.channel_display_name,
        "channel_type": channel.channel_type,
        "root_id": root_id,
        "create_at": create_at_ms,
        "update_at": update_at_ms,
        "post_type": str(post.get("type") or "") or None,
        "file_ids": file_ids,
    }
    if mentioned_user_ids:
        metadata["mentioned_user_ids"] = mentioned_user_ids
    if mentions_truncated:
        metadata["mentioned_user_ids_truncated"] = True
    if channel.team_id:
        metadata["team_id"] = channel.team_id
    if channel.team_name:
        metadata["team_name"] = channel.team_name
    if channel.team_display_name:
        metadata["team_display_name"] = channel.team_display_name

    author_user_id = str(post.get("user_id") or "").strip()
    if author_user_id:
        metadata["author_user_id"] = author_user_id
    if author:
        username = str(author.get("username") or "").strip()
        if username:
            metadata["author_username"] = username
        display_name = str(author.get("display_name") or "").strip()
        if display_name:
            metadata["author_display_name"] = display_name
    pending_post_id = str(post.get("pending_post_id") or "").strip()
    if pending_post_id:
        metadata["pending_post_id"] = pending_post_id

    return {
        "provider": "mattermost",
        "kind": "chat_message",
        "external_id": build_external_id(normalized_server_url, post_id),
        "origin": "source",
        "state": "observed",
        "title": _build_title(message, author),
        "body": _bounded_body(message),
        "metadata": metadata,
        "occurred_at": create_at_to_datetime(create_at_ms),
    }

