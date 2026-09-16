"""Conversation Stack presentation grouping for Inbox communication objects."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from app.db.models import Object
from app.services.conversation_projection import (
    ConversationProjection,
    project_inbox_object,
)
from app.services.inbox_review_marker import ReviewMarkerRecord, feed_tuple_is_newer
from app.services.recent_source_service import inbox_feed_at

CONVERSATION_BURST_MAX_GAP = timedelta(minutes=15)
STACK_FINGERPRINT_VERSION = "conversation_stack_v1"
# Exact frozen-snapshot conversation_count is computed in-process only at/under this size.
CONVERSATION_COUNT_EXACT_MAX_OBJECTS = 200

PROVIDER_FALLBACK_LABELS = {
    "gmail": "Gmail",
    "yandex_mail": "Yandex",
    "telegram": "Telegram",
    "teams": "Teams",
    "mattermost": "Mattermost",
}


@dataclass
class _UnionFind:
    parent: dict[int, int] = field(default_factory=dict)

    def find(self, item: int) -> int:
        self.parent.setdefault(item, item)
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, left: int, right: int) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


@dataclass(frozen=True)
class StackedObject:
    obj: Object
    projection: ConversationProjection | None
    grouping_key: str | None
    marker_side: Literal["new", "reviewed", "unmarked"]


@dataclass(frozen=True)
class ConversationStack:
    stack_id: str
    fingerprint: str
    object_ids: tuple[UUID, ...]
    display_object_ids: tuple[UUID, ...]
    provider: str
    conversation_key: str
    conversation_label: str
    participants: tuple[str, ...]
    message_count: int
    start_at: datetime
    end_at: datetime
    fallback_summary: str
    semantic_summary: str | None = None
    summary_status: Literal["current", "pending", "fallback", "stale"] = "fallback"
    marker_side: Literal["new", "reviewed", "unmarked"] = "unmarked"


@dataclass(frozen=True)
class ConversationGroupItem:
    item_type: Literal["stack", "singleton"]
    object_ids: tuple[UUID, ...]
    stack: ConversationStack | None = None
    is_communication: bool = False


def stack_content_fingerprint(obj: Object) -> str:
    body = obj.body or ""
    occurred = obj.occurred_at.isoformat() if obj.occurred_at else ""
    raw = f"{obj.title}\n{body}\n{occurred}".encode()
    return hashlib.sha256(raw).hexdigest()


def compute_stack_fingerprint(
    *,
    conversation_key: str,
    members: list[Object],
) -> str:
    parts = [
        f"{obj.id}:{stack_content_fingerprint(obj)}"
        for obj in sorted(members, key=lambda item: str(item.id))
    ]
    payload = "|".join([STACK_FINGERPRINT_VERSION, conversation_key, *parts])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def marker_side_for(
    obj: Object,
    marker: ReviewMarkerRecord | None,
) -> Literal["new", "reviewed", "unmarked"]:
    if marker is None:
        return "unmarked"
    feed_at = inbox_feed_at(obj)
    if feed_tuple_is_newer(feed_at, obj.id, marker.anchor_feed_at, marker.anchor_object_id):
        return "new"
    return "reviewed"


def _resolve_grouping_keys(projections: list[ConversationProjection | None]) -> list[str | None]:
    yandex_indexes = [
        index
        for index, projection in enumerate(projections)
        if projection is not None and projection.provider == "yandex_mail"
    ]
    union = _UnionFind()
    rfc_index: dict[str, int] = {}
    for index in yandex_indexes:
        projection = projections[index]
        assert projection is not None
        for rfc_id in projection.rfc_ids:
            prior = rfc_index.get(rfc_id)
            if prior is None:
                rfc_index[rfc_id] = index
            else:
                union.union(prior, index)
    roots: dict[int, str] = {}
    keys: list[str | None] = []
    for index, projection in enumerate(projections):
        if projection is None:
            keys.append(None)
            continue
        if projection.provider != "yandex_mail":
            keys.append(projection.grouping_seed)
            continue
        if projection.rfc_ids:
            root = union.find(index)
            if root not in roots:
                roots[root] = (
                    f"yandex_mail:{projection.account_scope}:chain:{min(projection.rfc_ids)}"
                )
            keys.append(roots[root])
            continue
        keys.append(projection.grouping_seed)
    return keys


def _participants_compatible(
    current: list[ConversationProjection],
    incoming: ConversationProjection,
    previous_locked_cohort: frozenset[str] | None,
) -> bool:
    if not incoming.unthreaded_public_channel:
        return True
    authors = {item.sender_id for item in current if item.sender_id}
    if not incoming.sender_id:
        return False
    if incoming.sender_id in authors:
        return True
    if len(authors) >= 2:
        return False
    return not (
        previous_locked_cohort
        and incoming.sender_id in previous_locked_cohort
        and authors
        and authors.isdisjoint(previous_locked_cohort)
    )


def _same_conversation(
    current: list[ConversationProjection],
    incoming: ConversationProjection,
    current_key: str,
    incoming_key: str,
    previous_locked_cohort: frozenset[str] | None,
) -> bool:
    if current_key != incoming_key:
        return False
    last = current[-1]
    if last.provider != incoming.provider:
        return False
    if last.account_scope != incoming.account_scope:
        return False
    gap = abs(incoming.feed_at - last.feed_at)
    if gap > CONVERSATION_BURST_MAX_GAP:
        return False
    return _participants_compatible(current, incoming, previous_locked_cohort)


def _stack_from_members(
    members: list[StackedObject],
) -> ConversationStack:
    projections = [item.projection for item in members if item.projection is not None]
    assert projections
    objects = [item.obj for item in members]
    chronological = sorted(objects, key=lambda obj: (inbox_feed_at(obj), obj.id))
    conversation_key = members[0].grouping_key or projections[0].grouping_seed
    fingerprint = compute_stack_fingerprint(
        conversation_key=conversation_key,
        members=chronological,
    )
    labels = []
    seen_labels: set[str] = set()
    for projection in projections:
        for label in (projection.sender_label, *projection.participant_labels, projection.conversation_label):
            if label and label not in seen_labels:
                seen_labels.add(label)
                labels.append(label)
    conversation_label = projections[0].conversation_label
    start_at = inbox_feed_at(chronological[0])
    end_at = inbox_feed_at(chronological[-1])
    fallback = deterministic_fallback_summary(
        provider=projections[0].provider,
        conversation_label=conversation_label,
        message_count=len(chronological),
        start_at=start_at,
        end_at=end_at,
        participant_count=len({p.sender_id for p in projections if p.sender_id}),
        subject=conversation_label if projections[0].provider in {"gmail", "yandex_mail"} else None,
    )
    return ConversationStack(
        stack_id=fingerprint,
        fingerprint=fingerprint,
        object_ids=tuple(obj.id for obj in chronological),
        display_object_ids=tuple(obj.id for obj in objects),
        provider=projections[0].provider,
        conversation_key=conversation_key,
        conversation_label=conversation_label,
        participants=tuple(labels),
        message_count=len(chronological),
        start_at=start_at,
        end_at=end_at,
        fallback_summary=fallback,
        marker_side=members[0].marker_side,
    )


def deterministic_fallback_summary(
    *,
    provider: str,
    conversation_label: str,
    message_count: int,
    start_at: datetime,
    end_at: datetime,
    participant_count: int = 0,
    subject: str | None = None,
) -> str:
    provider_label = PROVIDER_FALLBACK_LABELS.get(provider, provider)
    start_hm = start_at.strftime("%H:%M")
    end_hm = end_at.strftime("%H:%M")
    clock = start_hm if start_hm == end_hm else f"{start_hm}–{end_hm}"
    if provider in {"gmail", "yandex_mail"}:
        title = subject or conversation_label
        clipped = title if len(title) <= 80 else title[:77].rstrip() + "…"
        return f"{provider_label}, {message_count} сообщений в переписке «{clipped}», {clock}."
    if provider == "mattermost" and participant_count:
        noun = "участника" if participant_count == 1 else "участников"
        return (
            f"{provider_label}, {message_count} сообщений от {participant_count} {noun}, {clock}."
        )
    label = conversation_label.strip() or provider_label
    return f"{provider_label}, {label}, {message_count} сообщений, {clock}."


def group_inbox_conversation_items(
    objects: list[Object],
    *,
    marker: ReviewMarkerRecord | None = None,
) -> list[ConversationGroupItem]:
    projections = [project_inbox_object(obj) for obj in objects]
    grouping_keys = _resolve_grouping_keys(projections)
    stacked = [
        StackedObject(
            obj=obj,
            projection=projection,
            grouping_key=key,
            marker_side=marker_side_for(obj, marker),
        )
        for obj, projection, key in zip(objects, projections, grouping_keys, strict=True)
    ]
    groups: list[ConversationGroupItem] = []
    open_members: list[StackedObject] = []
    previous_locked_cohort: frozenset[str] | None = None

    def flush() -> None:
        nonlocal open_members, previous_locked_cohort
        if not open_members:
            return
        if len(open_members) == 1 or open_members[0].projection is None:
            for item in open_members:
                groups.append(
                    ConversationGroupItem(
                        item_type="singleton",
                        object_ids=(item.obj.id,),
                        is_communication=item.projection is not None,
                    )
                )
        else:
            stack = _stack_from_members(open_members)
            groups.append(
                ConversationGroupItem(
                    item_type="stack",
                    object_ids=stack.display_object_ids,
                    stack=stack,
                    is_communication=True,
                )
            )
            authors = {
                member.projection.sender_id
                for member in open_members
                if member.projection and member.projection.sender_id
            }
            if len(authors) >= 2:
                previous_locked_cohort = frozenset(authors)
        open_members = []

    for item in stacked:
        if item.projection is None or item.grouping_key is None:
            flush()
            groups.append(
                ConversationGroupItem(
                    item_type="singleton",
                    object_ids=(item.obj.id,),
                    is_communication=False,
                )
            )
            continue
        if not open_members:
            open_members = [item]
            continue
        head = open_members[0]
        if (
            head.projection is None
            or head.grouping_key is None
            or head.marker_side != item.marker_side
            or not _same_conversation(
                [member.projection for member in open_members if member.projection],
                item.projection,
                head.grouping_key,
                item.grouping_key,
                previous_locked_cohort,
            )
        ):
            flush()
            open_members = [item]
            continue
        open_members.append(item)
    flush()
    return groups


def overlay_covers_objects(groups: list[ConversationGroupItem], objects: list[Object]) -> bool:
    covered: list[UUID] = []
    for group in groups:
        covered.extend(group.object_ids)
    return covered == [obj.id for obj in objects]


def conversation_unit_count(groups: list[ConversationGroupItem]) -> int:
    return sum(1 for group in groups if group.is_communication)


def compact_review_units(groups: list[ConversationGroupItem]) -> int:
    """Stacks count as one conversation; every overlay item is one narration unit."""
    return len(groups)


def stack_to_dict(stack: ConversationStack) -> dict[str, Any]:
    return {
        "stack_id": stack.stack_id,
        "fingerprint": stack.fingerprint,
        "object_ids": [str(item) for item in stack.object_ids],
        "display_object_ids": [str(item) for item in stack.display_object_ids],
        "provider": stack.provider,
        "conversation_key": stack.conversation_key,
        "conversation_label": stack.conversation_label,
        "participants": list(stack.participants),
        "message_count": stack.message_count,
        "start_at": stack.start_at,
        "end_at": stack.end_at,
        "summary": stack.semantic_summary,
        "fallback_summary": stack.fallback_summary,
        "summary_status": stack.summary_status,
        "marker_side": stack.marker_side,
    }


def groups_to_overlay(groups: list[ConversationGroupItem]) -> list[dict[str, Any]]:
    overlay: list[dict[str, Any]] = []
    for group in groups:
        if group.item_type == "stack" and group.stack is not None:
            overlay.append({"type": "stack", "stack": stack_to_dict(group.stack)})
        else:
            overlay.append(
                {
                    "type": "singleton",
                    "object_id": str(group.object_ids[0]),
                }
            )
    return overlay
