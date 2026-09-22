"""Provider-neutral Inbox conversation projection.

This normalizes existing Object metadata for Inbox/Voice grouping only.
It does not create Objects, rewrite historical rows, or change acquisition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.db.models import Object
from app.services.recent_source_service import RecentSourceService, inbox_feed_at

COMMUNICATION_KINDS = frozenset({"email", "chat_message", "message"})
DIRECTION_INBOUND = "inbound"
DIRECTION_OUTBOUND = "outbound"
DIRECTION_UNKNOWN = "unknown"

_EMAIL_ADDR_RE = re.compile(r"<([^>]+)>")
_ANGLE_ID_RE = re.compile(r"<[^>]+>")
_RE_PREFIX_RE = re.compile(r"^\s*((re|fw|fwd|aw|отв)\s*:\s*)+", re.IGNORECASE)
_MATTERMOST_STRONG_CHANNELS = frozenset({"D", "G"})


@dataclass(frozen=True)
class ConversationProjection:
    object_id: UUID
    provider: str
    account_scope: str
    conversation_scope_key: str
    strong_thread_key: str | None
    grouping_seed: str
    sender_id: str | None
    sender_label: str | None
    participant_ids: frozenset[str]
    participant_labels: tuple[str, ...]
    direction: str
    occurred_at: datetime
    feed_at: datetime
    reply_ref: str | None
    title: str
    body: str | None
    excerpt: str | None
    identity_strength: Literal["strong", "coarse"]
    rfc_ids: frozenset[str]
    conversation_label: str
    subject_key: str | None
    unthreaded_public_channel: bool


def project_inbox_object(obj: Object) -> ConversationProjection | None:
    if obj.kind not in COMMUNICATION_KINDS:
        return None
    provider = (obj.provider or "").strip()
    if not provider:
        return None
    meta = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    feed_at = inbox_feed_at(obj)
    occurred = obj.occurred_at or feed_at
    if provider == "gmail":
        return _project_gmail(obj, meta, feed_at, occurred)
    if provider == "yandex_mail":
        return _project_yandex(obj, meta, feed_at, occurred)
    if provider == "telegram":
        if _meta_text(meta, "transport") == "mtproto":
            return _project_telegram_mtproto(obj, meta, feed_at, occurred)
        return _project_chat(obj, meta, feed_at, occurred, provider="telegram", label_keys=("chat_display_name", "from_display_name"))
    if provider == "teams":
        return _project_chat(obj, meta, feed_at, occurred, provider="teams", label_keys=("chat_display_title", "sender_display_name"))
    if provider == "mattermost":
        return _project_mattermost(obj, meta, feed_at, occurred)
    return None


def _meta_text(meta: dict[str, Any], key: str) -> str | None:
    raw = meta.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _account_scope(provider: str, meta: dict[str, Any]) -> str:
    account = _meta_text(meta, "account_id")
    return account or "_"


def _normalize_addr(value: str | None) -> str | None:
    if not value:
        return None
    match = _EMAIL_ADDR_RE.search(value)
    addr = (match.group(1) if match else value).strip().lower()
    return addr or None


def _display_name(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    match = _EMAIL_ADDR_RE.search(stripped)
    if match:
        name = stripped[: match.start()].strip().strip('"')
        return name or match.group(1)
    return stripped


def _rfc_ids(*values: object) -> frozenset[str]:
    found: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value)
        angled = _ANGLE_ID_RE.findall(text)
        if angled:
            for token in angled:
                found.add(token.strip().lower())
            continue
        compact = text.strip().lower()
        if compact:
            found.add(compact if compact.startswith("<") else f"<{compact}>")
    return frozenset(found)


def _normalize_subject(subject: str | None) -> str | None:
    if not subject:
        return None
    cleaned = _RE_PREFIX_RE.sub("", subject).strip().lower()
    return cleaned or None


def _gmail_direction(meta: dict[str, Any]) -> str:
    labels = meta.get("labels") or []
    names = {str(item).upper() for item in labels}
    if "SENT" in names:
        return DIRECTION_OUTBOUND
    if "INBOX" in names or "UNREAD" in names:
        return DIRECTION_INBOUND
    return DIRECTION_UNKNOWN


def _yandex_direction(meta: dict[str, Any]) -> str:
    folder = (_meta_text(meta, "folder") or "").lower()
    if folder in {"sent", "sent items", "отправленные"}:
        return DIRECTION_OUTBOUND
    if folder in {"inbox", "входящие"}:
        return DIRECTION_INBOUND
    return DIRECTION_UNKNOWN


def _project_gmail(
    obj: Object, meta: dict[str, Any], feed_at: datetime, occurred: datetime
) -> ConversationProjection | None:
    thread_id = _meta_text(meta, "thread_id")
    if not thread_id:
        return None
    account = _account_scope("gmail", meta)
    sender_raw = _meta_text(meta, "sender")
    sender_id = _normalize_addr(sender_raw)
    recipients = [_normalize_addr(str(item)) for item in (meta.get("recipients") or [])]
    cc = [_normalize_addr(str(item)) for item in (meta.get("cc") or [])]
    participant_ids = frozenset(item for item in [sender_id, *recipients, *cc] if item)
    headers = meta.get("headers") if isinstance(meta.get("headers"), dict) else {}
    subject = _meta_text(meta, "subject") or obj.title
    label = _display_name(sender_raw) or subject or "Gmail"
    return ConversationProjection(
        object_id=obj.id,
        provider="gmail",
        account_scope=account,
        conversation_scope_key=f"gmail:{account}:thread:{thread_id}",
        strong_thread_key=thread_id,
        grouping_seed=f"gmail:{account}:thread:{thread_id}",
        sender_id=sender_id,
        sender_label=_display_name(sender_raw),
        participant_ids=participant_ids,
        participant_labels=tuple(sorted(participant_ids)),
        direction=_gmail_direction(meta),
        occurred_at=occurred,
        feed_at=feed_at,
        reply_ref=_meta_text(headers, "in-reply-to"),
        title=obj.title,
        body=obj.body,
        excerpt=RecentSourceService.excerpt(obj.body),
        identity_strength="strong",
        rfc_ids=_rfc_ids(headers.get("message-id"), headers.get("in-reply-to"), headers.get("references")),
        conversation_label=subject or label,
        subject_key=_normalize_subject(subject),
        unthreaded_public_channel=False,
    )


def _project_yandex(
    obj: Object, meta: dict[str, Any], feed_at: datetime, occurred: datetime
) -> ConversationProjection | None:
    account = _account_scope("yandex_mail", meta)
    headers = meta.get("headers") if isinstance(meta.get("headers"), dict) else {}
    message_id = _meta_text(meta, "message_id") or _meta_text(headers, "message-id")
    rfc_ids = _rfc_ids(message_id, headers.get("in-reply-to"), headers.get("references"))
    sender_raw = _meta_text(meta, "sender")
    sender_id = _normalize_addr(sender_raw)
    recipients = [_normalize_addr(str(item)) for item in (meta.get("recipients") or [])]
    cc = [_normalize_addr(str(item)) for item in (meta.get("cc") or [])]
    participant_ids = frozenset(item for item in [sender_id, *recipients, *cc] if item)
    subject = _meta_text(meta, "subject") or obj.title
    subject_key = _normalize_subject(subject)
    if rfc_ids:
        seed = f"yandex_mail:{account}:rfc:{min(rfc_ids)}"
        strength: Literal["strong", "coarse"] = "strong"
    elif subject_key and participant_ids:
        people = ",".join(sorted(participant_ids))
        seed = f"yandex_mail:{account}:fallback:{subject_key}:{people}"
        strength = "coarse"
    else:
        seed = f"yandex_mail:{account}:object:{obj.id}"
        strength = "coarse"
    return ConversationProjection(
        object_id=obj.id,
        provider="yandex_mail",
        account_scope=account,
        conversation_scope_key=f"yandex_mail:{account}",
        strong_thread_key=min(rfc_ids) if rfc_ids else None,
        grouping_seed=seed,
        sender_id=sender_id,
        sender_label=_display_name(sender_raw),
        participant_ids=participant_ids,
        participant_labels=tuple(sorted(participant_ids)),
        direction=_yandex_direction(meta),
        occurred_at=occurred,
        feed_at=feed_at,
        reply_ref=_meta_text(headers, "in-reply-to"),
        title=obj.title,
        body=obj.body,
        excerpt=RecentSourceService.excerpt(obj.body),
        identity_strength=strength,
        rfc_ids=rfc_ids,
        conversation_label=subject or _display_name(sender_raw) or "Yandex",
        subject_key=subject_key,
        unthreaded_public_channel=False,
    )


def _project_chat(
    obj: Object,
    meta: dict[str, Any],
    feed_at: datetime,
    occurred: datetime,
    *,
    provider: str,
    label_keys: tuple[str, ...],
) -> ConversationProjection | None:
    chat_id = _meta_text(meta, "chat_id")
    if not chat_id:
        return None
    account = _account_scope(provider, meta)
    direction = (_meta_text(meta, "direction") or DIRECTION_UNKNOWN).lower()
    if direction not in {DIRECTION_INBOUND, DIRECTION_OUTBOUND}:
        direction = DIRECTION_UNKNOWN
    sender_id = _meta_text(meta, "from_user_id") or _meta_text(meta, "sender_id")
    sender_label = None
    for key in ("from_display_name", "sender_display_name", *label_keys):
        sender_label = _meta_text(meta, key)
        if sender_label:
            break
    conversation_label = None
    for key in label_keys:
        conversation_label = _meta_text(meta, key)
        if conversation_label:
            break
    conversation_label = conversation_label or sender_label or provider
    participants = frozenset(item for item in [sender_id, chat_id] if item)
    return ConversationProjection(
        object_id=obj.id,
        provider=provider,
        account_scope=account,
        conversation_scope_key=f"{provider}:{account}:chat:{chat_id}",
        strong_thread_key=chat_id,
        grouping_seed=f"{provider}:{account}:chat:{chat_id}",
        sender_id=sender_id,
        sender_label=sender_label,
        participant_ids=participants,
        participant_labels=tuple(sorted(x for x in [sender_label, conversation_label] if x)),
        direction=direction,
        occurred_at=occurred,
        feed_at=feed_at,
        reply_ref=_meta_text(meta, "reply_to_message_id") or _meta_text(meta, "quoted_message_id"),
        title=obj.title,
        body=obj.body,
        excerpt=RecentSourceService.excerpt(obj.body),
        identity_strength="strong",
        rfc_ids=frozenset(),
        conversation_label=conversation_label,
        subject_key=None,
        unthreaded_public_channel=False,
    )


def _project_telegram_mtproto(
    obj: Object, meta: dict[str, Any], feed_at: datetime, occurred: datetime
) -> ConversationProjection | None:
    """Project canonical MTProto metadata without legacy Bot chat aliases."""
    peer_id = _meta_text(meta, "peer_id")
    if not peer_id:
        return None
    account = _account_scope("telegram", meta)
    topic_id = _meta_text(meta, "topic_id")
    topic_suffix = f":topic:{topic_id}" if topic_id else ""
    scope = f"telegram:{account}:peer:{peer_id}{topic_suffix}"
    direction = (_meta_text(meta, "direction") or DIRECTION_UNKNOWN).lower()
    if direction not in {DIRECTION_INBOUND, DIRECTION_OUTBOUND}:
        direction = DIRECTION_UNKNOWN
    sender_id = _meta_text(meta, "sender_peer_id")
    conversation_label = None
    for key in ("peer_title", "group_title", "peer_username", "group_username", "username"):
        conversation_label = _meta_text(meta, key)
        if conversation_label:
            break
    conversation_label = conversation_label or "Telegram"
    participants = frozenset(item for item in [sender_id, peer_id] if item)
    return ConversationProjection(
        object_id=obj.id,
        provider="telegram",
        account_scope=account,
        conversation_scope_key=scope,
        strong_thread_key=peer_id if not topic_id else f"{peer_id}:topic:{topic_id}",
        grouping_seed=scope,
        sender_id=sender_id,
        sender_label=sender_id,
        participant_ids=participants,
        participant_labels=(conversation_label,),
        direction=direction,
        occurred_at=occurred,
        feed_at=feed_at,
        reply_ref=_meta_text(meta, "reply_to_message_id"),
        title=obj.title,
        body=obj.body,
        excerpt=RecentSourceService.excerpt(obj.body),
        identity_strength="strong",
        rfc_ids=frozenset(),
        conversation_label=conversation_label,
        subject_key=None,
        unthreaded_public_channel=False,
    )


def _project_mattermost(
    obj: Object, meta: dict[str, Any], feed_at: datetime, occurred: datetime
) -> ConversationProjection | None:
    channel_id = _meta_text(meta, "channel_id")
    if not channel_id:
        return None
    account = _account_scope("mattermost", meta)
    channel_type = (_meta_text(meta, "channel_type") or "").upper()
    root_id = _meta_text(meta, "root_id")
    sender_id = _meta_text(meta, "author_user_id")
    sender_label = (
        _meta_text(meta, "author_display_name")
        or _meta_text(meta, "author_username")
        or sender_id
    )
    channel_label = _meta_text(meta, "channel_display_name") or _meta_text(meta, "channel_name")
    unthreaded_public = channel_type not in _MATTERMOST_STRONG_CHANNELS and not root_id
    if root_id:
        grouping_seed = f"mattermost:{account}:thread:{channel_id}:{root_id}"
        strength: Literal["strong", "coarse"] = "strong"
        strong_thread_key = root_id
    elif channel_type in _MATTERMOST_STRONG_CHANNELS:
        grouping_seed = f"mattermost:{account}:channel:{channel_id}"
        strength = "strong"
        strong_thread_key = channel_id
    else:
        grouping_seed = f"mattermost:{account}:channel:{channel_id}"
        strength = "coarse"
        strong_thread_key = None
    conversation_label = sender_label or channel_label or "Mattermost"
    if channel_type in _MATTERMOST_STRONG_CHANNELS and channel_label:
        conversation_label = channel_label
    return ConversationProjection(
        object_id=obj.id,
        provider="mattermost",
        account_scope=account,
        conversation_scope_key=f"mattermost:{account}:channel:{channel_id}",
        strong_thread_key=strong_thread_key,
        grouping_seed=grouping_seed,
        sender_id=sender_id,
        sender_label=sender_label,
        participant_ids=frozenset(item for item in [sender_id] if item),
        participant_labels=tuple(item for item in [sender_label] if item),
        direction=DIRECTION_UNKNOWN,
        occurred_at=occurred,
        feed_at=feed_at,
        reply_ref=root_id,
        title=obj.title,
        body=obj.body,
        excerpt=RecentSourceService.excerpt(obj.body),
        identity_strength=strength,
        rfc_ids=frozenset(),
        conversation_label=conversation_label,
        subject_key=None,
        unthreaded_public_channel=unthreaded_public,
    )
