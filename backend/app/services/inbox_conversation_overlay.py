"""Attach summaries and enqueue missing conversation-stack summary jobs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import Object
from app.services.conversation_stack import (
    ConversationGroupItem,
    ConversationStack,
    group_inbox_conversation_items,
)
from app.services.conversation_stack_summary import (
    apply_summary_to_stack,
    enqueue_summarize_conversation_stack,
)
from app.services.inbox_review_marker import ReviewMarkerRecord


def build_inbox_conversation_groups(
    objects: list[Object],
    *,
    marker: ReviewMarkerRecord | None = None,
    session: Session | None = None,
    user_id: UUID | None = None,
    enqueue_summaries: bool = True,
) -> list[ConversationGroupItem]:
    groups = group_inbox_conversation_items(objects, marker=marker)
    if session is None:
        return groups
    decorated: list[ConversationGroupItem] = []
    for group in groups:
        if group.item_type != "stack" or group.stack is None:
            decorated.append(group)
            continue
        stack = apply_summary_to_stack(session, group.stack)
        if enqueue_summaries and user_id is not None and stack.semantic_summary is None:
            job = enqueue_summarize_conversation_stack(session, user_id, stack)
            if job is not None and stack.summary_status != "current":
                stack = ConversationStack(
                    stack_id=stack.stack_id,
                    fingerprint=stack.fingerprint,
                    object_ids=stack.object_ids,
                    display_object_ids=stack.display_object_ids,
                    provider=stack.provider,
                    conversation_key=stack.conversation_key,
                    conversation_label=stack.conversation_label,
                    participants=stack.participants,
                    message_count=stack.message_count,
                    start_at=stack.start_at,
                    end_at=stack.end_at,
                    fallback_summary=stack.fallback_summary,
                    semantic_summary=None,
                    summary_status="pending",
                    marker_side=stack.marker_side,
                )
        decorated.append(
            ConversationGroupItem(
                item_type="stack",
                object_ids=group.object_ids,
                stack=stack,
                is_communication=True,
            )
        )
    return decorated
