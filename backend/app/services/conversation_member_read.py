"""Read-only reconstruction of one presentation Conversation Stack's members."""

from __future__ import annotations

import base64
import json
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import Object
from app.services.conversation_projection import project_inbox_object
from app.services.conversation_stack import (
    ConversationStack,
    compute_stack_fingerprint,
    deterministic_fallback_summary,
    group_inbox_conversation_items,
)
from app.services.errors import NotFoundError, ValidationError
from app.services.inbox_review_marker import InboxReviewMarkerService
from app.services.inbox_review_snapshot_cursor import feed_at_iso, parse_feed_at
from app.services.recent_source_service import (
    RecentSourceService,
    inbox_feed_at,
    inbox_feed_at_sql,
)

CONVERSATION_MEMBERS_DEFAULT_LIMIT = 20
CONVERSATION_MEMBERS_MAX_LIMIT = 50
CONVERSATION_MEMBERS_EXCERPT_CHARS = 280
_WINDOW_HALF = 80
_WINDOW_HALF_MAX = 320
_CURSOR_VERSION = 1

_VOICE_MEDIA = frozenset({"voice", "audio", "video_note"})
_MEDIA_PLACEHOLDERS = {
    "voice": "голосовое сообщение без расшифровки",
    "audio": "аудио без расшифровки",
    "video_note": "видеосообщение без расшифровки",
    "photo": "фото",
    "video": "видео",
    "document": "документ",
    "sticker": "стикер",
    "animation": "анимация",
}


def _usable_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.replace("\n", " ").split())
    return text or None


def member_narration(obj: Object) -> tuple[str, str | None, str | None]:
    """Return (narration, excerpt, media_type)."""
    meta = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    media_type = str(meta.get("message_type") or "").strip() or None
    text = _usable_text(obj.body)
    if not text:
        for key in ("transcription", "transcript", "caption"):
            text = _usable_text(str(meta.get(key)) if meta.get(key) is not None else None)
            if text:
                break
    if text:
        excerpt = text
        if len(excerpt) > CONVERSATION_MEMBERS_EXCERPT_CHARS:
            excerpt = excerpt[: CONVERSATION_MEMBERS_EXCERPT_CHARS - 1].rstrip() + "…"
        return excerpt, excerpt, media_type
    if media_type in _VOICE_MEDIA:
        placeholder = _MEDIA_PLACEHOLDERS.get(media_type, "голосовое сообщение без расшифровки")
        return placeholder, None, media_type
    if media_type and media_type != "text":
        placeholder = _MEDIA_PLACEHOLDERS.get(media_type, f"{media_type} без текста")
        return placeholder, None, media_type
    title = _usable_text(obj.title) or "сообщение без текста"
    return title, None, media_type


def encode_conversation_members_cursor(
    *,
    fingerprint: str,
    object_id: UUID,
    last_object_id: UUID,
    last_feed_at,
) -> str:
    """Opaque continuation bound to the stack fingerprint and last visible member."""
    payload = {
        "v": _CURSOR_VERSION,
        "fp": fingerprint,
        "oid": str(object_id),
        "last": str(last_object_id),
        "feed": feed_at_iso(last_feed_at),
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str) -> dict:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValidationError("invalid conversation members cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise ValidationError("invalid conversation members cursor")
    try:
        object_id = UUID(str(payload["oid"]))
        last_id = UUID(str(payload["last"]))
        fingerprint = str(payload["fp"])
        last_feed = parse_feed_at(payload["feed"])
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ValidationError("invalid conversation members cursor") from exc
    if not fingerprint:
        raise ValidationError("invalid conversation members cursor")
    return {
        "fingerprint": fingerprint,
        "object_id": object_id,
        "last_object_id": last_id,
        "last_feed_at": last_feed,
    }


def _exists_beyond(
    session: Session,
    user_id: UUID,
    *,
    newer: bool,
    feed_at,
    object_id: UUID,
) -> bool:
    svc = RecentSourceService(session, user_id)
    feed_sql = inbox_feed_at_sql()
    if newer:
        bound = or_(feed_sql > feed_at, and_(feed_sql == feed_at, Object.id > object_id))
    else:
        bound = or_(feed_sql < feed_at, and_(feed_sql == feed_at, Object.id < object_id))
    found = session.scalar(
        select(Object.id).where(svc._eligible_filters(), bound).limit(1)
    )
    return found is not None


def _load_window(session: Session, user_id: UUID, anchor: Object, half: int) -> list[Object]:
    svc = RecentSourceService(session, user_id)
    feed_sql = inbox_feed_at_sql()
    anchor_feed = inbox_feed_at(anchor)
    newer = list(
        session.scalars(
            select(Object)
            .where(
                svc._eligible_filters(),
                Object.id != anchor.id,
                or_(
                    feed_sql > anchor_feed,
                    and_(feed_sql == anchor_feed, Object.id > anchor.id),
                ),
            )
            .order_by(feed_sql.asc(), Object.id.asc())
            .limit(half)
        ).all()
    )
    older = list(
        session.scalars(
            select(Object)
            .where(
                svc._eligible_filters(),
                Object.id != anchor.id,
                or_(
                    feed_sql < anchor_feed,
                    and_(feed_sql == anchor_feed, Object.id < anchor.id),
                ),
            )
            .order_by(feed_sql.desc(), Object.id.desc())
            .limit(half)
        ).all()
    )
    combined = {obj.id: obj for obj in [*newer, *older, anchor]}
    return sorted(
        combined.values(),
        key=lambda obj: (inbox_feed_at(obj), obj.id),
        reverse=True,
    )


def reconstruct_stack_members(
    session: Session,
    user_id: UUID,
    object_id: UUID,
) -> tuple[Object, list[Object], str, str, str]:
    anchor = session.get(Object, object_id)
    if (
        anchor is None
        or anchor.user_id != user_id
        or anchor.deleted_at is not None
    ):
        raise NotFoundError("object not found")
    if project_inbox_object(anchor) is None:
        raise ValidationError("object is not a conversation member")
    marker = InboxReviewMarkerService(session, user_id).get_marker()
    half = _WINDOW_HALF
    while True:
        window = _load_window(session, user_id, anchor, half)
        groups = group_inbox_conversation_items(window, marker=marker)
        group = next((item for item in groups if object_id in item.object_ids), None)
        if group is None:
            raise ValidationError("conversation stack could not be reconstructed")
        by_id = {obj.id: obj for obj in window}
        member_ids = list(group.stack.object_ids) if group.stack is not None else list(group.object_ids)
        members = [by_id[item] for item in member_ids if item in by_id]
        if len(members) != len(member_ids):
            if half >= _WINDOW_HALF_MAX:
                raise ValidationError("conversation stack could not be reconstructed")
            half = min(half * 2, _WINDOW_HALF_MAX)
            continue
        edge_hit = False
        if window[0].id in member_ids and _exists_beyond(
            session, user_id, newer=True, feed_at=inbox_feed_at(window[0]), object_id=window[0].id
        ):
            edge_hit = True
        if window[-1].id in member_ids and _exists_beyond(
            session, user_id, newer=False, feed_at=inbox_feed_at(window[-1]), object_id=window[-1].id
        ):
            edge_hit = True
        if edge_hit and half < _WINDOW_HALF_MAX:
            half = min(half * 2, _WINDOW_HALF_MAX)
            continue
        if group.stack is not None:
            stack = group.stack
        else:
            chronological = sorted(members, key=lambda obj: (inbox_feed_at(obj), obj.id))
            projection = project_inbox_object(chronological[0])
            assert projection is not None
            fingerprint = compute_stack_fingerprint(
                conversation_key=projection.grouping_seed,
                members=chronological,
            )
            start_at = inbox_feed_at(chronological[0])
            end_at = inbox_feed_at(chronological[-1])
            stack = ConversationStack(
                stack_id=fingerprint,
                fingerprint=fingerprint,
                object_ids=tuple(obj.id for obj in chronological),
                display_object_ids=tuple(obj.id for obj in members),
                provider=projection.provider,
                conversation_key=projection.grouping_seed,
                conversation_label=projection.conversation_label,
                participants=(),
                message_count=len(chronological),
                start_at=start_at,
                end_at=end_at,
                fallback_summary=deterministic_fallback_summary(
                    provider=projection.provider,
                    conversation_label=projection.conversation_label,
                    message_count=len(chronological),
                    start_at=start_at,
                    end_at=end_at,
                ),
            )
        chronological = [by_id[item] for item in stack.object_ids]
        return anchor, chronological, stack.provider, stack.conversation_label, stack.fingerprint


def list_conversation_members_page(
    session: Session,
    user_id: UUID,
    *,
    object_id: UUID,
    limit: int,
    cursor: str | None,
):
    bounded = min(max(limit, 1), CONVERSATION_MEMBERS_MAX_LIMIT)
    decoded = _decode_cursor(cursor) if cursor else None
    if decoded is not None and decoded["object_id"] != object_id:
        raise ValidationError("conversation members cursor does not match object_id")
    _anchor, members, provider, label, fingerprint = reconstruct_stack_members(
        session, user_id, object_id
    )
    if decoded is not None and decoded["fingerprint"] != fingerprint:
        raise ValidationError("conversation stack changed; restart without cursor")
    start = 0
    if decoded is not None:
        try:
            last_index = next(
                index for index, obj in enumerate(members) if obj.id == decoded["last_object_id"]
            )
        except StopIteration as exc:
            raise ValidationError("conversation members cursor is outside this stack") from exc
        start = last_index + 1
    page = members[start : start + bounded]
    remaining = members[start + len(page) :]
    has_more = bool(remaining)
    next_cursor = None
    if has_more and page:
        next_cursor = encode_conversation_members_cursor(
            fingerprint=fingerprint,
            object_id=object_id,
            last_object_id=page[-1].id,
            last_feed_at=inbox_feed_at(page[-1]),
        )
    return {
        "provider": provider,
        "conversation_label": label,
        "object_id": object_id,
        "stack_fingerprint": fingerprint,
        "total_member_count": len(members),
        "members": page,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "returned_count": len(page),
        "remaining_count": len(remaining),
    }
