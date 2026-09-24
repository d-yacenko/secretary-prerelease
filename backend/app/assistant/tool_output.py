import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.assistant.canonical_uri import sanitize_canonical_uri_for_assistant
from app.assistant.constants import (
    MAX_ASSISTANT_BODY_EXCERPT,
    MAX_ASSISTANT_CONTEXT_CHARS,
    MAX_ASSISTANT_LIST_RESULTS,
    MAX_ASSISTANT_NEIGHBOR_RESULTS,
    MAX_ASSISTANT_QUERY_OBJECT_TITLE_CHARS,
    MAX_ASSISTANT_QUERY_OBJECTS_RESULTS,
    MAX_ASSISTANT_RETRIEVE_EXCERPT,
    MAX_ASSISTANT_RETRIEVE_RESULTS,
    MAX_ASSISTANT_SEARCH_RESULTS,
    MAX_ASSISTANT_TOOL_OUTPUT_CHARS,
)


def bounded_body_excerpt(body: str | None) -> str | None:
    if body is None:
        return None
    normalized = body.replace("\n", " ").strip()
    if len(normalized) <= MAX_ASSISTANT_BODY_EXCERPT:
        return normalized
    return normalized[:MAX_ASSISTANT_BODY_EXCERPT] + "… [truncated]"


def _bounded_query_title(title: str | None) -> str:
    if not title:
        return ""
    normalized = title.replace("\n", " ").strip()
    if len(normalized) <= MAX_ASSISTANT_QUERY_OBJECT_TITLE_CHARS:
        return normalized
    return normalized[:MAX_ASSISTANT_QUERY_OBJECT_TITLE_CHARS] + "…"


def _bounded_query_object_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "object_id": row.get("object_id"),
        "title": _bounded_query_title(row.get("title")),
        "kind": row.get("kind"),
        "provider": row.get("provider"),
        "state": row.get("state"),
        "status": row.get("status"),
        "due_at": row.get("due_at"),
        "start_at": row.get("start_at"),
        "occurred_at": row.get("occurred_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


_SEMANTIC_TEXT_CHARS = 240
_SEMANTIC_KEYS = (
    "sender",
    "from",
    "recipients",
    "to",
    "cc",
    "subject",
    "source_account_email",
    "location",
    "organizer",
    "attendees",
    "calendar_summary",
    "author_username",
    "author_display_name",
    "from_username",
    "from_display_name",
    "chat_display_name",
    "chat_display_title",
    "sender_display_name",
    "direction",
    "filename",
    "name",
    "path",
    "semantic_summary",
    "participants",
    "tags",
    "category",
    "labels",
    "folder",
)
_SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
    "api_key",
    "session",
    "cookie",
)


def _sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _clip_semantic_text(value: object, max_chars: int = _SEMANTIC_TEXT_CHARS) -> str | None:
    text = " ".join(str(value).replace("\n", " ").split())
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _clip_semantic_value(value: object) -> object | None:
    if isinstance(value, str):
        return _clip_semantic_text(value)
    if isinstance(value, list):
        items = []
        for item in value[:8]:
            if isinstance(item, str):
                clipped = _clip_semantic_text(item, 120)
            elif isinstance(item, dict):
                clipped = _clip_semantic_mapping(item)
            else:
                clipped = _clip_semantic_text(item, 120)
            if clipped:
                items.append(clipped)
        return items or None
    if isinstance(value, dict):
        return _clip_semantic_mapping(value)
    return _clip_semantic_text(value, 120)


def _clip_semantic_mapping(value: dict[str, Any]) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    for key, item in list(value.items())[:12]:
        name = str(key)
        if _sensitive_key(name):
            continue
        clipped = _clip_semantic_value(item)
        if clipped:
            payload[name] = clipped
    return payload or None


def _semantic_metadata(obj: dict[str, Any]) -> dict[str, Any] | None:
    metadata = obj.get("metadata")
    if not isinstance(metadata, dict):
        return None
    payload: dict[str, Any] = {}
    if obj.get("kind") == "email" or obj.get("provider") in {"gmail", "yandex_mail"}:
        email = _email_envelope(metadata, obj.get("title"))
        if email:
            payload["email"] = email
    for key in _SEMANTIC_KEYS:
        if _sensitive_key(key) or key not in metadata:
            continue
        if (
            key in {"sender", "recipients", "cc", "subject", "source_account_email"}
            and "email" in payload
        ):
            continue
        clipped = _clip_semantic_value(metadata.get(key))
        if clipped:
            payload[key] = clipped
    return payload or None


def _email_envelope(metadata: dict[str, Any], title: object) -> dict[str, Any] | None:
    headers = metadata.get("headers") if isinstance(metadata.get("headers"), dict) else {}
    envelope: dict[str, Any] = {}
    sender = _clip_semantic_text(
        metadata.get("sender") or headers.get("from") or headers.get("From")
    )
    reply_to = _clip_semantic_text(headers.get("reply-to") or headers.get("Reply-To"))
    subject = _clip_semantic_text(metadata.get("subject") or title)
    to = _clip_semantic_value(metadata.get("recipients") or headers.get("to") or headers.get("To"))
    cc = _clip_semantic_value(metadata.get("cc") or headers.get("cc") or headers.get("Cc"))
    source_account = _clip_semantic_text(metadata.get("source_account_email"))
    message_id = _clip_semantic_text(headers.get("message-id") or headers.get("Message-ID"), 200)
    thread_id = _clip_semantic_text(metadata.get("thread_id"), 200)
    if sender:
        envelope["from"] = sender
    if reply_to:
        envelope["reply_to"] = reply_to
    if to:
        envelope["to"] = to
    if cc:
        envelope["cc"] = cc
    if subject:
        envelope["subject"] = subject
    if source_account:
        envelope["source_account_email"] = source_account
    if message_id:
        envelope["message_id"] = message_id
    if thread_id:
        envelope["thread_id"] = thread_id
    return envelope or None


def _bounded_object(obj: dict[str, Any]) -> dict[str, Any]:
    safe_uri = sanitize_canonical_uri_for_assistant(obj.get("canonical_uri"))
    payload: dict[str, Any] = {
        "id": obj.get("id"),
        "kind": obj.get("kind"),
        "title": obj.get("title"),
        "body": bounded_body_excerpt(obj.get("body")),
        "provider": obj.get("provider"),
        "status": obj.get("status"),
        "origin": obj.get("origin"),
        "state": obj.get("state"),
    }
    semantic = _semantic_metadata(obj)
    if semantic:
        payload["semantic"] = semantic
    if safe_uri is not None:
        payload["canonical_uri"] = safe_uri
    return payload


def _bounded_retrieve_excerpt(excerpt: str | None) -> str:
    if not excerpt:
        return ""
    normalized = excerpt.replace("\n", " ").strip()
    if len(normalized) <= MAX_ASSISTANT_RETRIEVE_EXCERPT:
        return normalized
    return normalized[:MAX_ASSISTANT_RETRIEVE_EXCERPT] + "… [truncated]"


_CONVERSATION_MEMBER_LABEL_CHARS = 80
_CONVERSATION_MEMBER_NARRATION_MIN_CHARS = 80


def _clip_member_text(value: object, max_chars: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).replace("\n", " ").split())
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _bounded_conversation_member(row: dict[str, Any], *, minimal: bool = False) -> dict[str, Any]:
    from app.services.conversation_member_read import CONVERSATION_MEMBERS_EXCERPT_CHARS

    narration_cap = (
        _CONVERSATION_MEMBER_NARRATION_MIN_CHARS if minimal else CONVERSATION_MEMBERS_EXCERPT_CHARS
    )
    narration = _clip_member_text(row.get("narration"), narration_cap) or "сообщение"
    payload: dict[str, Any] = {
        "object_id": row.get("object_id"),
        "occurred_at": row.get("occurred_at"),
        "feed_at": row.get("feed_at"),
        "media_type": row.get("media_type"),
        "narration": narration,
    }
    if minimal:
        return payload
    sender = _clip_member_text(row.get("sender"), _CONVERSATION_MEMBER_LABEL_CHARS)
    title = _clip_member_text(row.get("title"), _CONVERSATION_MEMBER_LABEL_CHARS)
    if sender:
        payload["sender"] = sender
    if title:
        payload["title"] = title
    excerpt = _clip_member_text(row.get("excerpt"), CONVERSATION_MEMBERS_EXCERPT_CHARS)
    if excerpt and excerpt != narration:
        payload["excerpt"] = excerpt
    return payload


def _conversation_members_visible_payload(
    raw_output: dict[str, Any],
    visible_members: list[dict[str, Any]],
) -> dict[str, Any]:
    from app.services.conversation_member_read import encode_conversation_members_cursor
    from app.services.inbox_review_snapshot_cursor import parse_feed_at

    raw_members = list(raw_output.get("members") or [])
    original_remaining = int(raw_output.get("remaining_count") or 0)
    dropped = len(visible_members) < len(raw_members)
    remaining = max(len(raw_members) - len(visible_members), 0) + original_remaining
    has_more = remaining > 0
    next_cursor = raw_output.get("next_cursor")
    if dropped:
        next_cursor = None
        if has_more and visible_members:
            last = visible_members[-1]
            next_cursor = encode_conversation_members_cursor(
                fingerprint=str(raw_output.get("stack_fingerprint") or ""),
                object_id=UUID(str(raw_output.get("object_id"))),
                last_object_id=UUID(str(last.get("object_id"))),
                last_feed_at=parse_feed_at(last.get("feed_at")),
            )
    elif not has_more:
        next_cursor = None
    payload: dict[str, Any] = {
        "object_id": raw_output.get("object_id"),
        "provider": raw_output.get("provider"),
        "conversation_label": (
            _clip_member_text(
                raw_output.get("conversation_label"), _CONVERSATION_MEMBER_LABEL_CHARS
            )
            or raw_output.get("conversation_label")
        ),
        "stack_fingerprint": raw_output.get("stack_fingerprint"),
        "total_member_count": raw_output.get("total_member_count"),
        "returned_count": len(visible_members),
        "remaining_count": remaining,
        "members": visible_members,
        "has_more": has_more,
        "next_cursor": next_cursor,
    }
    if dropped:
        payload["truncated"] = True
        payload["message"] = (
            f"This conversation has {remaining} more members after this page "
            f"(total_member_count={raw_output.get('total_member_count')}). Pass the exact "
            "next_cursor to continue oldest-to-newest; do not invent it."
        )
    elif raw_output.get("message"):
        payload["message"] = raw_output.get("message")
    return payload


def _normalize_review_object_id(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _compact_coverage_ids(item: dict[str, Any]) -> list[str]:
    if item.get("type") == "stack":
        stack = item.get("stack") or {}
        ids = []
        for object_id in stack.get("object_ids") or []:
            normalized = _normalize_review_object_id(object_id)
            if normalized:
                ids.append(normalized)
        return ids
    normalized = _normalize_review_object_id(item.get("object_id"))
    return [normalized] if normalized else []


def _visible_feed_range(covered: list[str], by_id: dict[str, dict[str, Any]]):
    from app.services.errors import ValidationError
    from app.services.inbox_review_snapshot_cursor import parse_feed_at

    times = []
    for object_id in covered:
        raw = (by_id.get(object_id) or {}).get("feed_at")
        try:
            times.append(parse_feed_at(raw))
        except (ValidationError, TypeError, ValueError):
            continue
    if not times:
        return None, None
    return min(times), max(times)


def _rebuild_partial_stack(
    item: dict[str, Any],
    covered: list[str],
    by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    from app.services.conversation_stack import deterministic_fallback_summary
    from app.services.inbox_review_snapshot_cursor import feed_at_iso

    stack = dict(item.get("stack") or {})
    original_ids = _compact_coverage_ids(item)
    stack["object_ids"] = covered
    stack["message_count"] = len(covered)
    if len(covered) != len(original_ids):
        start_at, end_at = _visible_feed_range(covered, by_id)
        provider = str(stack.get("provider") or "unknown")
        label = str(stack.get("conversation_label") or provider)
        if start_at is not None and end_at is not None:
            stack["start_at"] = feed_at_iso(start_at)
            stack["end_at"] = feed_at_iso(end_at)
            fallback = deterministic_fallback_summary(
                provider=provider,
                conversation_label=label,
                message_count=len(covered),
                start_at=start_at,
                end_at=end_at,
            )
        else:
            from app.services.conversation_stack import PROVIDER_FALLBACK_LABELS

            provider_label = PROVIDER_FALLBACK_LABELS.get(provider, provider)
            fallback = (
                f"{provider_label}, {label.strip() or provider_label}, {len(covered)} сообщений."
            )
        stack["summary"] = None
        stack["summary_status"] = "fallback"
        stack["fallback_summary"] = fallback
        return {"type": "stack", "narration": fallback, "stack": stack}
    return {**item, "stack": stack}


def _trim_compact_items_to_visible(
    compact_items: list[dict[str, Any]],
    visible_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    visible_ids = []
    by_id: dict[str, dict[str, Any]] = {}
    for item in visible_items:
        object_id = _normalize_review_object_id(item.get("object_id"))
        if not object_id:
            continue
        visible_ids.append(object_id)
        by_id[object_id] = item
    visible_set = set(visible_ids)
    trimmed: list[dict[str, Any]] = []
    for item in compact_items:
        covered = [
            object_id for object_id in _compact_coverage_ids(item) if object_id in visible_set
        ]
        if not covered:
            continue
        if item.get("type") == "stack" and len(covered) >= 2:
            trimmed.append(_rebuild_partial_stack(item, covered, by_id))
            continue
        if item.get("type") == "stack":
            source = by_id.get(covered[0], {})
            trimmed.append(
                {
                    "type": "singleton",
                    "object_id": covered[0],
                    "kind": source.get("kind"),
                    "provider": source.get("provider"),
                    "title": source.get("title"),
                    "feed_at": source.get("feed_at"),
                    "excerpt": source.get("excerpt"),
                    "narration": source.get("title"),
                }
            )
            continue
        trimmed.append(item)
    return trimmed


def _inbox_review_list_payload(
    raw_output: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    truncated: bool,
    include_compact: bool = True,
) -> dict[str, Any]:
    from app.services.errors import ValidationError
    from app.services.inbox_review_snapshot_cursor import (
        encode_inbox_review_snapshot_cursor,
        parse_feed_at,
        parse_object_id,
    )

    visible_items = [
        {
            "object_id": item.get("object_id"),
            "kind": item.get("kind"),
            "provider": item.get("provider"),
            "title": item.get("title"),
            "feed_at": item.get("feed_at"),
            "excerpt": item.get("excerpt"),
        }
        for item in items
    ]
    compact_items = list(raw_output.get("compact_items") or []) if include_compact else []
    visible_compact = []
    for item in compact_items:
        if item.get("type") == "stack":
            stack = item.get("stack") or {}
            visible_compact.append(
                {
                    "type": "stack",
                    "narration": item.get("narration"),
                    "stack": {
                        "stack_id": stack.get("stack_id"),
                        "object_ids": stack.get("object_ids"),
                        "provider": stack.get("provider"),
                        "conversation_label": stack.get("conversation_label"),
                        "message_count": stack.get("message_count"),
                        "start_at": stack.get("start_at"),
                        "end_at": stack.get("end_at"),
                        "summary": stack.get("summary"),
                        "fallback_summary": stack.get("fallback_summary"),
                        "summary_status": stack.get("summary_status"),
                    },
                }
            )
        else:
            visible_compact.append(
                {
                    "type": "singleton",
                    "object_id": item.get("object_id"),
                    "kind": item.get("kind"),
                    "provider": item.get("provider"),
                    "title": item.get("title"),
                    "feed_at": item.get("feed_at"),
                    "excerpt": item.get("excerpt"),
                    "narration": item.get("narration"),
                }
            )
    if include_compact:
        visible_compact = _trim_compact_items_to_visible(visible_compact, visible_items)
    has_more = bool(raw_output.get("has_more")) or truncated
    raw_remaining = raw_output.get("remaining_count")
    remaining = int(raw_remaining) if isinstance(raw_remaining, int) else 0
    raw_item_count = len(raw_output.get("items") or [])
    if truncated and raw_item_count > len(visible_items):
        remaining += raw_item_count - len(visible_items)
    next_cursor = raw_output.get("next_cursor")
    if truncated and visible_items:
        last = visible_items[-1]
        try:
            next_cursor = encode_inbox_review_snapshot_cursor(
                anchor_object_id=parse_object_id(raw_output.get("anchor_object_id")),
                anchor_feed_at=parse_feed_at(raw_output.get("anchor_feed_at")),
                snapshot_top_object_id=parse_object_id(raw_output.get("snapshot_top_object_id")),
                snapshot_top_feed_at=parse_feed_at(raw_output.get("snapshot_top_feed_at")),
                last_object_id=parse_object_id(last.get("object_id")),
                last_feed_at=parse_feed_at(last.get("feed_at")),
                direction="asc" if raw_output.get("purpose") == "review" else "desc",
            )
        except (ValidationError, TypeError, ValueError):
            next_cursor = None
            has_more = True
    elif truncated and not visible_items:
        next_cursor = None
        has_more = bool(raw_output.get("has_more")) or raw_item_count > 0
    if not has_more:
        next_cursor = None
    payload = {
        "marker_present": raw_output.get("marker_present"),
        "marker_not_set": raw_output.get("marker_not_set"),
        "purpose": raw_output.get("purpose"),
        "anchor_object_id": raw_output.get("anchor_object_id"),
        "anchor_feed_at": raw_output.get("anchor_feed_at"),
        "snapshot_top_object_id": raw_output.get("snapshot_top_object_id"),
        "snapshot_top_feed_at": raw_output.get("snapshot_top_feed_at"),
        "total_count": raw_output.get("total_count", 0),
        "returned_count": len(visible_items),
        "remaining_count": remaining,
        "page_conversation_count": raw_output.get("page_conversation_count", 0),
        "conversation_count_exact": bool(raw_output.get("conversation_count_exact")),
        "items": visible_items,
        "has_more": has_more,
    }
    if raw_output.get("conversation_count") is not None:
        payload["conversation_count"] = raw_output.get("conversation_count")
    if include_compact:
        payload["compact_items"] = visible_compact
    if next_cursor:
        payload["next_cursor"] = next_cursor
    if raw_output.get("message"):
        payload["message"] = raw_output.get("message")
    if truncated:
        payload["truncated"] = True
    return payload


def serialize_tool_output_for_model(tool_name: str, raw_output: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "retrieve":
        hits = raw_output.get("hits", [])[:MAX_ASSISTANT_RETRIEVE_RESULTS]
        truncated = len(raw_output.get("hits", [])) > len(hits)
        payload: dict[str, Any] = {
            "hits": [
                {
                    "object_id": hit.get("object_id"),
                    "title": hit.get("title"),
                    "kind": hit.get("kind"),
                    "provider": hit.get("provider"),
                    "state": hit.get("state"),
                    "status": hit.get("status"),
                    "occurred_at": hit.get("occurred_at"),
                    "relevance": hit.get("relevance"),
                    "reasons": hit.get("reasons", []),
                    "excerpt": _bounded_retrieve_excerpt(hit.get("excerpt")),
                }
                for hit in hits
            ],
            "time_scope_used": raw_output.get("time_scope_used"),
            "horizon_days": raw_output.get("horizon_days"),
        }
        if truncated:
            payload["truncated"] = True
        return payload

    if tool_name == "query_objects":
        objects = [
            _bounded_query_object_row(row)
            for row in raw_output.get("objects", [])[:MAX_ASSISTANT_QUERY_OBJECTS_RESULTS]
        ]
        truncated = len(raw_output.get("objects", [])) > len(objects)
        payload: dict[str, Any] = {"objects": objects}
        if truncated:
            payload["truncated"] = True
        return payload

    if tool_name == "search_objects":
        objects = raw_output.get("objects", [])[:MAX_ASSISTANT_SEARCH_RESULTS]
        truncated = len(raw_output.get("objects", [])) > len(objects)
        payload = {
            "objects": [_bounded_object(obj) for obj in objects],
        }
        if truncated:
            payload["truncated"] = True
            payload["total_before_truncation"] = len(raw_output.get("objects", []))
        return payload

    if tool_name == "get_object":
        obj = raw_output.get("object")
        return {"object": _bounded_object(obj) if obj else None}

    if tool_name == "get_context":
        items = raw_output.get("items", [])
        bounded_items: list[dict[str, Any]] = []
        total_chars = 0
        truncated = False
        for item in items:
            content = item.get("content", "")
            if total_chars + len(content) > MAX_ASSISTANT_CONTEXT_CHARS:
                remaining = MAX_ASSISTANT_CONTEXT_CHARS - total_chars
                if remaining > 0:
                    content = content[:remaining] + "… [truncated]"
                else:
                    truncated = True
                    break
            item_payload: dict[str, Any] = {
                "object_id": item.get("object_id"),
                "kind": item.get("kind"),
                "title": item.get("title"),
                "content": content,
                "origin": item.get("origin"),
                "state": item.get("state"),
                "why_included": item.get("why_included"),
            }
            safe_uri = sanitize_canonical_uri_for_assistant(item.get("canonical_uri"))
            if safe_uri is not None:
                item_payload["canonical_uri"] = safe_uri
            bounded_items.append(item_payload)
            total_chars += len(content)
            if total_chars >= MAX_ASSISTANT_CONTEXT_CHARS:
                truncated = True
                break
        if len(bounded_items) < len(items):
            truncated = True
        result: dict[str, Any] = {
            "items": bounded_items,
            "total_chars": total_chars,
            "truncated": truncated or raw_output.get("truncated", False),
        }
        return result

    if tool_name == "list_neighbors":
        neighbors = raw_output.get("neighbors", [])[:MAX_ASSISTANT_NEIGHBOR_RESULTS]
        truncated = len(raw_output.get("neighbors", [])) > len(neighbors)
        payload = {
            "object_id": raw_output.get("object_id"),
            "neighbors": [
                {
                    "object": _bounded_object(neighbor.get("object", {})),
                    "edge": {
                        "id": neighbor.get("edge", {}).get("id"),
                        "type": neighbor.get("edge", {}).get("type"),
                        "origin": neighbor.get("edge", {}).get("origin"),
                        "state": neighbor.get("edge", {}).get("state"),
                    },
                    "direction": neighbor.get("direction"),
                }
                for neighbor in neighbors
                if neighbor.get("object")
            ],
        }
        if truncated:
            payload["truncated"] = True
        return payload

    if tool_name == "list_labels":
        labels = raw_output.get("labels", [])[:MAX_ASSISTANT_LIST_RESULTS]
        truncated = len(raw_output.get("labels", [])) > len(labels)
        payload = {
            "labels": [
                {
                    "id": row.get("id"),
                    "title": row.get("title"),
                    "description": row.get("description"),
                    "object_count": row.get("object_count", 0),
                }
                for row in labels
            ],
        }
        if truncated:
            payload["truncated"] = True
        return payload

    if tool_name == "list_notifications":
        notifications = raw_output.get("notifications", [])[:MAX_ASSISTANT_LIST_RESULTS]
        truncated = len(raw_output.get("notifications", [])) > len(notifications)
        payload = {
            "notifications": [
                {
                    "id": row.get("id"),
                    "title": row.get("title"),
                    "body": bounded_body_excerpt(row.get("body")),
                    "priority": row.get("priority"),
                    "status": row.get("status"),
                    "source_object_id": row.get("source_object_id"),
                    "related_object_id": row.get("related_object_id"),
                    "proposal": row.get("proposal"),
                }
                for row in notifications
            ],
        }
        if truncated:
            payload["truncated"] = True
        return payload

    if tool_name == "list_inbox_since_review_marker":
        raw_items = list(raw_output.get("items") or [])
        items = raw_items[:MAX_ASSISTANT_LIST_RESULTS]
        truncated = len(raw_items) > len(items)
        payload = _inbox_review_list_payload(raw_output, items, truncated=truncated)
        return payload

    if tool_name == "list_conversation_members":
        raw_members = list(raw_output.get("members") or [])
        members = [
            _bounded_conversation_member(row) for row in raw_members[:MAX_ASSISTANT_LIST_RESULTS]
        ]
        return _conversation_members_visible_payload(raw_output, members)

    if tool_name in (
        "create_task",
        "update_task",
        "create_scheduled_activity",
        "create_recurring_scheduled_activity",
    ):
        obj = raw_output.get("object")
        payload: dict[str, Any] = {"object": _bounded_object(obj) if obj else None}
        if tool_name == "update_task":
            payload["changed"] = raw_output.get("changed", False)
            payload["evidence_edges_created"] = raw_output.get("evidence_edges_created", 0)
            payload["evidence_added_object_ids"] = raw_output.get("evidence_added_object_ids", [])
            payload["evidence_already_linked_object_ids"] = raw_output.get(
                "evidence_already_linked_object_ids", []
            )
        return payload

    if tool_name == "link_objects":
        edge = raw_output.get("edge")
        return {
            "edge": {
                "id": edge.get("id"),
                "source_id": edge.get("source_id"),
                "target_id": edge.get("target_id"),
                "type": edge.get("type"),
                "origin": edge.get("origin"),
                "state": edge.get("state"),
            }
            if edge
            else None,
            "created": raw_output.get("created", True),
        }

    if tool_name == "remove_relation":
        edge = raw_output.get("edge")
        return {
            "edge": {
                "id": edge.get("id"),
                "source_id": edge.get("source_id"),
                "target_id": edge.get("target_id"),
                "type": edge.get("type"),
                "origin": edge.get("origin"),
                "state": edge.get("state"),
            }
            if edge
            else None,
            "changed": raw_output.get("changed", False),
            "previous_state": raw_output.get("previous_state"),
            "new_state": raw_output.get("new_state"),
        }

    if tool_name in ("set_task_status", "delete_task", "cancel_scheduled_activity"):
        obj = raw_output.get("object")
        return {
            "object": _bounded_object(obj) if obj else None,
            "changed": raw_output.get("changed", False),
            "status": raw_output.get("status"),
        }

    if tool_name == "get_today":
        return raw_output

    if tool_name == "create_calendar_event":
        return {
            "provider": raw_output.get("provider"),
            "account_email": raw_output.get("account_email"),
            "calendar_id": raw_output.get("calendar_id"),
            "event_id": raw_output.get("event_id"),
            "summary": raw_output.get("summary"),
            "start_at": raw_output.get("start_at"),
            "end_at": raw_output.get("end_at"),
            "canonical_uri": raw_output.get("canonical_uri"),
            "changed": raw_output.get("changed", False),
        }

    if tool_name == "send_email":
        return {
            "provider": raw_output.get("provider"),
            "account_email": raw_output.get("account_email"),
            "to": raw_output.get("to"),
            "subject": raw_output.get("subject"),
            "provider_message_id": raw_output.get("provider_message_id"),
            "delivery_status": raw_output.get("delivery_status"),
            "changed": raw_output.get("changed", False),
            "sent_copy_status": raw_output.get("sent_copy_status"),
        }

    if tool_name == "send_message":
        return {
            "provider": raw_output.get("provider"),
            "mode": raw_output.get("mode"),
            "provider_message_id": raw_output.get("provider_message_id"),
            "object_id": raw_output.get("object_id"),
            "delivery_status": raw_output.get("delivery_status"),
            "changed": raw_output.get("changed", False),
        }

    return raw_output


@dataclass(frozen=True)
class AssistantToolModelOutput:
    model_output_json: str
    model_visible_payload: dict[str, Any]


def serialize_tool_output_for_assistant(
    tool_name: str, raw_output: dict[str, Any]
) -> AssistantToolModelOutput:
    """Single serialization path: JSON sent to the model and its exact parsed payload."""
    bounded = serialize_tool_output_for_model(tool_name, raw_output)
    if tool_name == "search_objects":
        objects = list(bounded.get("objects", []))
        while objects:
            candidate = dict(bounded)
            candidate["objects"] = objects
            text = json.dumps(candidate, ensure_ascii=False)
            if len(text) <= MAX_ASSISTANT_TOOL_OUTPUT_CHARS:
                return AssistantToolModelOutput(text, candidate)
            objects.pop()
        fallback = {"objects": [], "truncated": True}
        return AssistantToolModelOutput(
            json.dumps(fallback, ensure_ascii=False),
            fallback,
        )

    if tool_name == "query_objects":
        objects = list(bounded.get("objects", []))
        truncated_by_count = bounded.get("truncated", False)
        while objects:
            candidate = dict(bounded)
            candidate["objects"] = objects
            if truncated_by_count or len(objects) < len(raw_output.get("objects", [])):
                candidate["truncated"] = True
            text = json.dumps(candidate, ensure_ascii=False)
            if len(text) <= MAX_ASSISTANT_TOOL_OUTPUT_CHARS:
                return AssistantToolModelOutput(text, candidate)
            objects.pop()
        fallback = {"objects": [], "truncated": True}
        return AssistantToolModelOutput(
            json.dumps(fallback, ensure_ascii=False),
            fallback,
        )

    if tool_name == "list_labels":
        labels = list(bounded.get("labels", []))
        truncated_by_count = bounded.get("truncated", False)
        while labels:
            candidate = dict(bounded)
            candidate["labels"] = labels
            if truncated_by_count or len(labels) < len(raw_output.get("labels", [])):
                candidate["truncated"] = True
            text = json.dumps(candidate, ensure_ascii=False)
            if len(text) <= MAX_ASSISTANT_TOOL_OUTPUT_CHARS:
                return AssistantToolModelOutput(text, candidate)
            labels.pop()
        fallback = {"labels": [], "truncated": True}
        return AssistantToolModelOutput(
            json.dumps(fallback, ensure_ascii=False),
            fallback,
        )

    if tool_name == "list_inbox_since_review_marker":
        items = list(bounded.get("items", []))
        raw_items = list(raw_output.get("items") or [])
        include_compact = True
        while True:
            candidate = _inbox_review_list_payload(
                raw_output,
                items,
                truncated=len(items) < len(raw_items),
                include_compact=include_compact,
            )
            text = json.dumps(candidate, ensure_ascii=False)
            if len(text) <= MAX_ASSISTANT_TOOL_OUTPUT_CHARS:
                return AssistantToolModelOutput(text, candidate)
            if include_compact and candidate.get("compact_items"):
                include_compact = False
                continue
            if not items:
                metadata = {
                    key: candidate.get(key)
                    for key in (
                        "marker_present",
                        "marker_not_set",
                        "purpose",
                        "anchor_object_id",
                        "anchor_feed_at",
                        "snapshot_top_object_id",
                        "snapshot_top_feed_at",
                        "total_count",
                        "returned_count",
                        "remaining_count",
                        "conversation_count",
                        "page_conversation_count",
                        "conversation_count_exact",
                        "has_more",
                        "next_cursor",
                    )
                }
                metadata["items"] = []
                metadata["truncated"] = True
                return AssistantToolModelOutput(
                    json.dumps(metadata, ensure_ascii=False),
                    metadata,
                )
            items.pop()

    if tool_name == "list_conversation_members":
        members = list(bounded.get("members", []))
        if not members and raw_output.get("members"):
            members = [_bounded_conversation_member(raw_output["members"][0], minimal=True)]
        include_message = True
        minimal = False
        while True:
            visible = [
                _bounded_conversation_member(row, minimal=minimal) if minimal else row
                for row in members
            ]
            candidate = _conversation_members_visible_payload(raw_output, visible)
            if not include_message:
                candidate.pop("message", None)
            text = json.dumps(candidate, ensure_ascii=False)
            if len(text) <= MAX_ASSISTANT_TOOL_OUTPUT_CHARS:
                return AssistantToolModelOutput(text, candidate)
            if include_message and candidate.get("message"):
                include_message = False
                continue
            if len(members) > 1:
                members.pop()
                continue
            if not minimal:
                minimal = True
                continue
            candidate.pop("message", None)
            text = json.dumps(candidate, ensure_ascii=False)
            if len(text) <= MAX_ASSISTANT_TOOL_OUTPUT_CHARS:
                return AssistantToolModelOutput(text, candidate)
            # Last resort: keep essential fields of the first raw member.
            last_member = _bounded_conversation_member(
                (raw_output.get("members") or [{}])[0], minimal=True
            )
            fallback = _conversation_members_visible_payload(raw_output, [last_member])
            fallback.pop("message", None)
            return AssistantToolModelOutput(
                json.dumps(fallback, ensure_ascii=False),
                fallback,
            )

    text = json.dumps(bounded, ensure_ascii=False)
    if len(text) <= MAX_ASSISTANT_TOOL_OUTPUT_CHARS:
        return AssistantToolModelOutput(text, bounded)
    fallback = {"truncated": True, "preview_chars": len(text)}
    return AssistantToolModelOutput(
        json.dumps(fallback, ensure_ascii=False),
        fallback,
    )


def serialize_tool_output_json(tool_name: str, raw_output: dict[str, Any]) -> str:
    return serialize_tool_output_for_assistant(tool_name, raw_output).model_output_json
