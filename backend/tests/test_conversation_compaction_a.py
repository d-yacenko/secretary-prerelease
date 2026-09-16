"""Unified Conversation & Inbox Compaction A — projection, burst, marker, pagination, summary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Job, Object, Representation
from app.jobs.constants import (
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_TYPE_SUMMARIZE_CONVERSATION_STACK,
)
from app.services.conversation_projection import project_inbox_object
from app.services.conversation_stack import (
    CONVERSATION_BURST_MAX_GAP,
    ConversationStack,
    compute_stack_fingerprint,
    conversation_unit_count,
    group_inbox_conversation_items,
    overlay_covers_objects,
)
from app.services.conversation_stack_summary import (
    SUMMARY_RETRY_COOLDOWN,
    ConversationStackSummaryService,
    enqueue_summarize_conversation_stack,
    find_current_stack_summary,
    persist_stack_summary,
)
from app.services.domain_tool_service import DomainToolService
from app.services.inbox_conversation_overlay import build_inbox_conversation_groups
from app.services.inbox_review_marker import InboxReviewMarkerService, ReviewMarkerRecord
from app.services.job_queue_service import is_job_error_retryable
from app.services.recent_source_service import inbox_feed_at
from app.services.representation_service import KIND_CONVERSATION_STACK_SUMMARY
from app.tools.schemas import ListInboxSinceReviewMarkerInput
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _stamp(obj: Object, when: datetime) -> Object:
    obj.created_at = when
    obj.updated_at = when
    obj.occurred_at = when
    return obj


def _base(
    db_session: Session,
    *,
    kind: str,
    provider: str,
    title: str,
    when: datetime,
    metadata: dict,
    body: str | None = None,
    user_id: UUID | None = None,
) -> Object:
    obj = Object(
        id=uuid.uuid4(),
        user_id=user_id or BOOTSTRAP_USER_ID,
        kind=kind,
        title=title,
        body=body or title,
        origin="source",
        state="observed",
        provider=provider,
        external_id=f"ext-{uuid.uuid4()}",
        metadata_=metadata,
    )
    db_session.add(obj)
    db_session.flush()
    return _stamp(obj, when)


def _gmail(db_session, title, when, thread_id, *, sender, recipients, labels, body=None, account="acc-1"):
    return _base(
        db_session,
        kind="email",
        provider="gmail",
        title=title,
        when=when,
        body=body,
        metadata={
            "account_id": account,
            "thread_id": thread_id,
            "sender": sender,
            "recipients": recipients,
            "cc": [],
            "subject": title,
            "labels": labels,
            "headers": {},
        },
    )


def _yandex(db_session, title, when, *, sender, recipients, headers, folder="INBOX", account="acc-y"):
    return _base(
        db_session,
        kind="email",
        provider="yandex_mail",
        title=title,
        when=when,
        metadata={
            "account_id": account,
            "folder": folder,
            "sender": sender,
            "recipients": recipients,
            "cc": [],
            "subject": title,
            "message_id": headers.get("message-id"),
            "headers": headers,
        },
    )


def _telegram(db_session, title, when, chat_id, *, sender="u1", name="BrainTor", account="tg-1", body=None):
    return _base(
        db_session,
        kind="chat_message",
        provider="telegram",
        title=title,
        when=when,
        body=body,
        metadata={
            "account_id": account,
            "chat_id": chat_id,
            "from_user_id": sender,
            "from_display_name": name,
            "chat_display_name": name,
            "direction": "inbound",
        },
    )


def _teams(db_session, title, when, chat_id, *, sender="s1", account="teams-1"):
    return _base(
        db_session,
        kind="chat_message",
        provider="teams",
        title=title,
        when=when,
        metadata={
            "account_id": account,
            "chat_id": chat_id,
            "sender_id": sender,
            "sender_display_name": sender,
            "chat_display_title": "Work chat",
            "direction": "inbound",
        },
    )


def _mm(
    db_session,
    title,
    when,
    *,
    channel_id,
    author,
    author_name,
    channel_type="O",
    root_id=None,
    account="mm-1",
):
    return _base(
        db_session,
        kind="chat_message",
        provider="mattermost",
        title=title,
        when=when,
        metadata={
            "account_id": account,
            "channel_id": channel_id,
            "channel_type": channel_type,
            "channel_display_name": "town-square",
            "author_user_id": author,
            "author_display_name": author_name,
            "root_id": root_id,
            "post_id": str(uuid.uuid4()),
        },
    )


def _newest_first(items: list[Object]) -> list[Object]:
    return sorted(items, key=lambda obj: (inbox_feed_at(obj), obj.id), reverse=True)


def test_burst_threshold_is_fifteen_minutes() -> None:
    assert CONVERSATION_BURST_MAX_GAP == timedelta(minutes=15)


def test_gmail_same_thread_role_reversal_groups(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 14, 8, tzinfo=UTC)
    thread = "thread-role"
    incoming = _gmail(
        db_session, "Fable", t0, thread, sender="Ada <ada@x.test>", recipients=["me@x.test"], labels=["INBOX"]
    )
    outgoing = _gmail(
        db_session,
        "Re: Fable",
        t0 + timedelta(minutes=6),
        thread,
        sender="Me <me@x.test>",
        recipients=["ada@x.test"],
        labels=["SENT"],
    )
    incoming2 = _gmail(
        db_session,
        "Re: Fable",
        t0 + timedelta(minutes=12),
        thread,
        sender="Ada <ada@x.test>",
        recipients=["me@x.test"],
        labels=["INBOX"],
    )
    assert project_inbox_object(incoming).grouping_seed == project_inbox_object(outgoing).grouping_seed
    groups = group_inbox_conversation_items(_newest_first([incoming, outgoing, incoming2]))
    stacks = [item for item in groups if item.item_type == "stack"]
    assert len(stacks) == 1
    assert stacks[0].stack.message_count == 3


def test_gmail_different_thread_never_merges(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 14, 8, tzinfo=UTC)
    a = _gmail(db_session, "A", t0, "t1", sender="a@x.test", recipients=["me@x.test"], labels=["INBOX"])
    b = _gmail(
        db_session, "B", t0 + timedelta(minutes=1), "t2", sender="a@x.test", recipients=["me@x.test"], labels=["INBOX"]
    )
    groups = group_inbox_conversation_items(_newest_first([a, b]))
    assert all(item.item_type == "singleton" for item in groups)


def test_yandex_references_chain_same_conversation(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 10, tzinfo=UTC)
    root = _yandex(
        db_session,
        "Hosts",
        t0,
        sender="ann@y.test",
        recipients=["me@y.test"],
        headers={"message-id": "<root@y>", "in-reply-to": "", "references": ""},
    )
    reply = _yandex(
        db_session,
        "Re: Hosts",
        t0 + timedelta(minutes=3),
        sender="me@y.test",
        recipients=["ann@y.test"],
        headers={"message-id": "<r1@y>", "in-reply-to": "<root@y>", "references": "<root@y>"},
    )
    reply2 = _yandex(
        db_session,
        "Re: Hosts",
        t0 + timedelta(minutes=6),
        sender="ann@y.test",
        recipients=["me@y.test"],
        headers={"message-id": "<r2@y>", "in-reply-to": "<r1@y>", "references": "<root@y> <r1@y>"},
    )
    groups = group_inbox_conversation_items(_newest_first([root, reply, reply2]))
    stacks = [item for item in groups if item.item_type == "stack"]
    assert len(stacks) == 1
    assert set(stacks[0].object_ids) == {root.id, reply.id, reply2.id}


def test_yandex_insufficient_evidence_conservative_split(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 10, tzinfo=UTC)
    a = _yandex(
        db_session,
        "Invoice",
        t0,
        sender="a@y.test",
        recipients=["me@y.test"],
        headers={},
    )
    b = _yandex(
        db_session,
        "Invoice",
        t0 + timedelta(minutes=2),
        sender="b@y.test",
        recipients=["other@y.test"],
        headers={},
    )
    groups = group_inbox_conversation_items(_newest_first([a, b]))
    assert all(item.item_type == "singleton" for item in groups)


def test_telegram_same_chat_close_in_time_stacks(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, 6, tzinfo=UTC)
    rows = [
        _telegram(db_session, f"tg {i}", t0 + timedelta(seconds=20 * i), "chat-brain")
        for i in range(4)
    ]
    groups = group_inbox_conversation_items(_newest_first(rows))
    stacks = [item for item in groups if item.item_type == "stack"]
    assert len(stacks) == 1
    assert stacks[0].stack.message_count == 4
    assert "BrainTor" in stacks[0].stack.fallback_summary


def test_telegram_different_chat_split(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, 6, tzinfo=UTC)
    a = _telegram(db_session, "a", t0, "c1")
    b = _telegram(db_session, "b", t0 + timedelta(seconds=30), "c2", name="Other")
    groups = group_inbox_conversation_items(_newest_first([a, b]))
    assert all(item.item_type == "singleton" for item in groups)


def test_teams_same_chat_close_in_time_stacks(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 11, tzinfo=UTC)
    rows = [_teams(db_session, f"tm {i}", t0 + timedelta(minutes=i), "chat-t") for i in range(3)]
    groups = group_inbox_conversation_items(_newest_first(rows))
    assert len([item for item in groups if item.item_type == "stack"]) == 1


def test_mattermost_same_root_thread_stacks(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 12, tzinfo=UTC)
    root = "root-1"
    rows = [
        _mm(db_session, f"th {i}", t0 + timedelta(minutes=i), channel_id="ch1", author="a", author_name="A", root_id=root)
        for i in range(3)
    ]
    groups = group_inbox_conversation_items(_newest_first(rows))
    assert len([item for item in groups if item.item_type == "stack"]) == 1


def test_mattermost_different_root_split(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 12, tzinfo=UTC)
    a = _mm(db_session, "a", t0, channel_id="ch1", author="a", author_name="A", root_id="r1")
    b = _mm(db_session, "b", t0 + timedelta(minutes=1), channel_id="ch1", author="a", author_name="A", root_id="r2")
    groups = group_inbox_conversation_items(_newest_first([a, b]))
    assert all(item.item_type == "singleton" for item in groups)


def test_mattermost_unthreaded_interleaving_not_absorbed(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 12, 41, tzinfo=UTC)
    a1 = _mm(db_session, "A1", t0, channel_id="town", author="ann", author_name="Ann")
    b1 = _mm(db_session, "B1", t0 + timedelta(minutes=1), channel_id="town", author="bob", author_name="Bob")
    a2 = _mm(db_session, "A2", t0 + timedelta(minutes=2), channel_id="town", author="ann", author_name="Ann")
    x = _mm(db_session, "unrelated X", t0 + timedelta(minutes=3), channel_id="town", author="xeno", author_name="Xeno")
    b2 = _mm(db_session, "B2", t0 + timedelta(minutes=4), channel_id="town", author="bob", author_name="Bob")
    a3 = _mm(db_session, "A3", t0 + timedelta(minutes=5), channel_id="town", author="ann", author_name="Ann")
    groups = group_inbox_conversation_items(_newest_first([a1, b1, a2, x, b2, a3]))
    stacks = [item for item in groups if item.item_type == "stack"]
    assert len(stacks) == 2
    assert any(item.item_type == "singleton" and item.object_ids == (x.id,) for item in groups)
    covered = [oid for item in groups for oid in item.object_ids]
    assert covered == [obj.id for obj in _newest_first([a1, b1, a2, x, b2, a3])]
    assert x.id in [item.object_ids[0] for item in groups if item.item_type == "singleton"]


def test_gap_below_threshold_stacks_and_above_splits(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, tzinfo=UTC)
    close_a = _telegram(db_session, "c1", t0, "chat-g")
    close_b = _telegram(db_session, "c2", t0 + timedelta(minutes=14), "chat-g")
    far = _telegram(db_session, "c3", t0 + timedelta(minutes=30), "chat-g")
    grouped_close = group_inbox_conversation_items(_newest_first([close_a, close_b]))
    assert grouped_close[0].item_type == "stack"
    grouped_far = group_inbox_conversation_items(_newest_first([close_b, far]))
    assert all(item.item_type == "singleton" for item in grouped_far)


def test_singleton_remains_singleton(db_session: Session) -> None:
    row = _telegram(db_session, "one", datetime(2026, 9, 15, 16, tzinfo=UTC), "solo")
    groups = group_inbox_conversation_items([row])
    assert groups[0].item_type == "singleton"


def test_role_alternation_does_not_split(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 12, tzinfo=UTC)
    rows = []
    for i, author in enumerate(["ann", "bob", "ann", "bob"]):
        rows.append(
            _mm(
                db_session,
                f"m{i}",
                t0 + timedelta(minutes=i),
                channel_id="dm",
                author=author,
                author_name=author,
                channel_type="D",
            )
        )
    groups = group_inbox_conversation_items(_newest_first(rows))
    assert len(groups) == 1
    assert groups[0].stack.message_count == 4


def test_calendar_not_grouped(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, tzinfo=UTC)
    event = _base(
        db_session,
        kind="event",
        provider="google_calendar",
        title="Meet",
        when=t0,
        metadata={},
    )
    tg = _telegram(db_session, "hi", t0, "c")
    groups = group_inbox_conversation_items(_newest_first([event, tg]))
    assert all(item.item_type == "singleton" for item in groups)


def test_marker_split_never_hides_boundary(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, tzinfo=UTC)
    older = _telegram(db_session, "old", t0, "chat-m")
    newer = _telegram(db_session, "new", t0 + timedelta(minutes=1), "chat-m")
    marker = ReviewMarkerRecord(
        anchor_feed_at=inbox_feed_at(older),
        anchor_object_id=older.id,
        updated_at=t0,
    )
    groups = group_inbox_conversation_items(_newest_first([older, newer]), marker=marker)
    assert all(item.item_type == "singleton" for item in groups)
    assert overlay_covers_objects(groups, _newest_first([older, newer]))


def test_marker_entirely_new_or_reviewed(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, tzinfo=UTC)
    a = _telegram(db_session, "a", t0, "chat-n")
    b = _telegram(db_session, "b", t0 + timedelta(minutes=1), "chat-n")
    below = ReviewMarkerRecord(
        anchor_feed_at=inbox_feed_at(b),
        anchor_object_id=b.id,
        updated_at=t0,
    )
    reviewed = group_inbox_conversation_items(_newest_first([a, b]), marker=below)
    assert reviewed[0].item_type == "stack"
    assert reviewed[0].stack.marker_side == "reviewed"
    above = ReviewMarkerRecord(
        anchor_feed_at=t0 - timedelta(minutes=5),
        anchor_object_id=uuid.uuid4(),
        updated_at=t0,
    )
    fresh = group_inbox_conversation_items(_newest_first([a, b]), marker=above)
    assert fresh[0].stack.marker_side == "new"


def test_pagination_no_loss_or_duplicate(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, tzinfo=UTC)
    rows = [_telegram(db_session, f"p{i}", t0 + timedelta(seconds=i), "page-chat") for i in range(4)]
    ordered = _newest_first(rows)
    first = group_inbox_conversation_items(ordered[:2])
    second = group_inbox_conversation_items(ordered[2:])
    covered = [oid for group in first + second for oid in group.object_ids]
    assert covered == [obj.id for obj in ordered]
    assert len(set(covered)) == 4


def test_fingerprint_stable_and_changes_on_edit_or_member(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, tzinfo=UTC)
    a = _telegram(db_session, "a", t0, "fp")
    b = _telegram(db_session, "b", t0 + timedelta(seconds=30), "fp")
    key = project_inbox_object(a).grouping_seed
    first = compute_stack_fingerprint(conversation_key=key, members=[a, b])
    second = compute_stack_fingerprint(conversation_key=key, members=[b, a])
    assert first == second
    b.body = "edited body"
    db_session.flush()
    edited = compute_stack_fingerprint(conversation_key=key, members=[a, b])
    assert edited != first
    c = _telegram(db_session, "c", t0 + timedelta(seconds=40), "fp")
    added = compute_stack_fingerprint(conversation_key=key, members=[a, b, c])
    assert added != first


def test_stale_summary_rejected_and_fallback_used(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, 6, tzinfo=UTC)
    rows = [_telegram(db_session, f"s{i}", t0 + timedelta(seconds=i), "sum") for i in range(2)]
    groups = group_inbox_conversation_items(_newest_first(rows))
    stack = groups[0].stack
    persist_stack_summary(
        db_session,
        stack=stack,
        objects=list(reversed(_newest_first(rows))),
        text="Обсуждали новую модель Fable.",
    )
    hydrated = build_inbox_conversation_groups(
        _newest_first(rows), session=db_session, user_id=BOOTSTRAP_USER_ID, enqueue_summaries=False
    )
    assert hydrated[0].stack.semantic_summary == "Обсуждали новую модель Fable."
    rows[0].body = "changed"
    db_session.flush()
    stale = build_inbox_conversation_groups(
        _newest_first(rows), session=db_session, user_id=BOOTSTRAP_USER_ID, enqueue_summaries=False
    )
    assert stale[0].stack.semantic_summary is None
    assert "сообщений" in stale[0].stack.fallback_summary


def test_failed_summary_job_cooldown_then_retry(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, tzinfo=UTC)
    rows = [_telegram(db_session, f"r{i}", t0 + timedelta(seconds=i), "retry") for i in range(2)]
    stack = group_inbox_conversation_items(_newest_first(rows))[0].stack
    failed = Job(
        user_id=BOOTSTRAP_USER_ID,
        type=JOB_TYPE_SUMMARIZE_CONVERSATION_STACK,
        payload={"stack_fingerprint": stack.fingerprint},
        status=JOB_STATUS_FAILED,
        attempts=3,
    )
    db_session.add(failed)
    db_session.flush()
    for _ in range(10):
        assert enqueue_summarize_conversation_stack(db_session, BOOTSTRAP_USER_ID, stack) is None
        build_inbox_conversation_groups(
            _newest_first(rows), session=db_session, user_id=BOOTSTRAP_USER_ID
        )
    pending = db_session.scalars(
        select(Job).where(
            Job.type == JOB_TYPE_SUMMARIZE_CONVERSATION_STACK,
            Job.status == JOB_STATUS_PENDING,
            Job.user_id == BOOTSTRAP_USER_ID,
        )
    ).all()
    assert pending == []
    old = datetime.now(UTC) - SUMMARY_RETRY_COOLDOWN - timedelta(minutes=1)
    db_session.execute(
        update(Job).where(Job.id == failed.id).values(updated_at=old, created_at=old)
    )
    db_session.flush()
    job = enqueue_summarize_conversation_stack(db_session, BOOTSTRAP_USER_ID, stack)
    assert job is not None
    assert job.status == JOB_STATUS_PENDING
    again = enqueue_summarize_conversation_stack(db_session, BOOTSTRAP_USER_ID, stack)
    assert again.id == job.id
    third = enqueue_summarize_conversation_stack(db_session, BOOTSTRAP_USER_ID, stack)
    assert third.id == job.id


def test_summary_generation_writes_representation(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, tzinfo=UTC)
    rows = [_telegram(db_session, f"g{i}", t0 + timedelta(seconds=i), "gen", body="хосты для экшенов") for i in range(2)]
    ordered = list(reversed(_newest_first(rows)))
    stack = group_inbox_conversation_items(_newest_first(rows))[0].stack
    ConversationStackSummaryService(db_session, BOOTSTRAP_USER_ID).generate_for_payload(
        {
            "stack_fingerprint": stack.fingerprint,
            "conversation_key": stack.conversation_key,
            "object_ids": [str(obj.id) for obj in ordered],
        }
    )
    stored = db_session.scalar(
        select(Representation).where(Representation.kind == KIND_CONVERSATION_STACK_SUMMARY)
    )
    assert stored is not None
    assert stored.metadata_["stack_fingerprint"] == stack.fingerprint


def test_empty_summary_is_retryable_failure_not_done(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, tzinfo=UTC)
    rows = [
        _telegram(db_session, f"e{i}", t0 + timedelta(seconds=i), "empty", body="хосты")
        for i in range(2)
    ]
    ordered = list(reversed(_newest_first(rows)))
    stack = group_inbox_conversation_items(_newest_first(rows))[0].stack
    payload = {
        "stack_fingerprint": stack.fingerprint,
        "conversation_key": stack.conversation_key,
        "object_ids": [str(obj.id) for obj in ordered],
    }

    class BlankSummarizer:
        def __init__(self, text: str) -> None:
            self._text = text

        def summarize(self, text: str) -> str:
            return self._text

    for blank in ("", "  \n"):
        with pytest.raises(ValueError, match="empty conversation stack summary") as caught:
            ConversationStackSummaryService(
                db_session, BOOTSTRAP_USER_ID, summarizer=BlankSummarizer(blank)
            ).generate_for_payload(payload)
        assert is_job_error_retryable(caught.value) is True
    assert is_job_error_retryable(caught.value) is True
    stored = db_session.scalars(
        select(Representation).where(Representation.kind == KIND_CONVERSATION_STACK_SUMMARY)
    ).all()
    assert stored == []
    first = enqueue_summarize_conversation_stack(db_session, BOOTSTRAP_USER_ID, stack)
    assert first is not None
    assert first.status == JOB_STATUS_PENDING
    second = enqueue_summarize_conversation_stack(db_session, BOOTSTRAP_USER_ID, stack)
    assert second.id == first.id
    hydrated = build_inbox_conversation_groups(
        _newest_first(rows), session=db_session, user_id=BOOTSTRAP_USER_ID
    )
    assert hydrated[0].stack.semantic_summary is None
    assert "сообщений" in hydrated[0].stack.fallback_summary
    first.status = JOB_STATUS_FAILED
    db_session.flush()
    for _ in range(10):
        assert enqueue_summarize_conversation_stack(db_session, BOOTSTRAP_USER_ID, stack) is None
    pending = db_session.scalars(
        select(Job).where(
            Job.type == JOB_TYPE_SUMMARIZE_CONVERSATION_STACK,
            Job.status == JOB_STATUS_PENDING,
            Job.user_id == BOOTSTRAP_USER_ID,
        )
    ).all()
    assert pending == []



def test_realistic_gmail_role_reversal_over_twenty_minutes(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 14, 8, tzinfo=UTC)
    thread = "fable-thread"
    times = [0, 5, 11, 18]
    labels_cycle = [["INBOX"], ["SENT"], ["INBOX"], ["SENT"]]
    senders = ["Ada <ada@x.test>", "Me <me@x.test>", "Ada <ada@x.test>", "Me <me@x.test>"]
    recips = [["me@x.test"], ["ada@x.test"], ["me@x.test"], ["ada@x.test"]]
    rows = [
        _gmail(
            db_session,
            "Fable model",
            t0 + timedelta(minutes=offset),
            thread,
            sender=senders[i],
            recipients=recips[i],
            labels=labels_cycle[i],
        )
        for i, offset in enumerate(times)
    ]
    groups = group_inbox_conversation_items(_newest_first(rows))
    assert len(groups) == 1
    assert groups[0].stack.message_count == 4


def test_overlay_exact_coverage(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, tzinfo=UTC)
    rows = [_telegram(db_session, f"o{i}", t0 + timedelta(seconds=i), "cov") for i in range(3)]
    event = _base(
        db_session,
        kind="event",
        provider="google_calendar",
        title="event",
        when=t0 + timedelta(seconds=10),
        metadata={},
    )
    ordered = _newest_first([*rows, event])
    groups = group_inbox_conversation_items(ordered)
    assert overlay_covers_objects(groups, ordered)
    assert conversation_unit_count(groups) == 1


def test_inbox_api_keeps_flat_feed_and_optional_overlay(auth_client, db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 16, tzinfo=UTC)
    rows = [_telegram(db_session, f"api{i}", t0 + timedelta(seconds=i), "api-chat") for i in range(4)]
    db_session.flush()
    first = auth_client.get("/inbox", params={"recent_limit": 2})
    assert first.status_code == 200
    body = first.json()
    assert len(body["recent_source_objects"]) == 2
    assert "conversation_groups" in body
    ids = [item["id"] for item in body["recent_source_objects"]]
    overlay_ids = []
    for group in body["conversation_groups"]:
        if group["type"] == "stack":
            overlay_ids.extend(group["stack"]["display_object_ids"])
        else:
            overlay_ids.append(group["object_id"])
    assert overlay_ids == ids
    cursor = body["recent_next_cursor"]
    assert cursor
    second = auth_client.get("/inbox/feed", params={"cursor": cursor, "limit": 2})
    assert second.status_code == 200
    feed = second.json()
    feed_ids = [item["id"] for item in feed["items"]]
    assert not set(ids) & set(feed_ids)
    all_ids = ids + feed_ids
    assert len(all_ids) == 4
    assert set(all_ids) == {str(row.id) for row in rows}


def test_inspect_limit_one_uses_global_conversation_count(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 10, tzinfo=UTC)
    anchor = _telegram(db_session, "anchor", t0, "anchor-chat")
    sizes = [9, 7, 5, 5, 4, 2]
    n = 0
    for index, size in enumerate(sizes):
        for _ in range(size):
            n += 1
            _telegram(
                db_session,
                f"m{n}",
                t0 + timedelta(minutes=1, seconds=n),
                f"conv-{index}",
                name=f"Chat{index}",
            )
    InboxReviewMarkerService(db_session, BOOTSTRAP_USER_ID).set_marker(anchor.id)
    db_session.flush()
    page = DomainToolService(db_session, BOOTSTRAP_USER_ID, None).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="inspect", limit=1)
    )
    assert page.total_count == 32
    assert page.returned_count == 1
    assert page.page_conversation_count == 1
    assert page.conversation_count == 6
    assert page.conversation_count_exact is True


def test_split_pages_count_as_one_global_conversation(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 11, tzinfo=UTC)
    anchor = _telegram(db_session, "anchor", t0, "split-anchor")
    for i in range(5):
        _telegram(db_session, f"same {i}", t0 + timedelta(minutes=1, seconds=i), "one-chat")
    InboxReviewMarkerService(db_session, BOOTSTRAP_USER_ID).set_marker(anchor.id)
    db_session.flush()
    tools = DomainToolService(db_session, BOOTSTRAP_USER_ID, None)
    first = tools.list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=2)
    )
    second = tools.list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=2, cursor=first.next_cursor)
    )
    assert first.total_count == second.total_count == 5
    assert first.page_conversation_count == 1
    assert second.page_conversation_count == 1
    assert first.conversation_count == second.conversation_count == 1
    assert first.conversation_count_exact is True
    assert second.conversation_count_exact is True


def test_same_anchor_keeps_independent_summary_fingerprints(db_session: Session) -> None:
    t0 = datetime(2026, 9, 15, 12, tzinfo=UTC)
    rows = [_telegram(db_session, f"fp{i}", t0 + timedelta(seconds=i), "anchor-fp") for i in range(30)]
    newest_first = _newest_first(rows)
    full = group_inbox_conversation_items(newest_first)[0].stack
    chronological = list(reversed(newest_first))
    subset = chronological[10:]
    fingerprint_b = compute_stack_fingerprint(
        conversation_key=full.conversation_key, members=subset
    )
    stack_b = ConversationStack(
        stack_id=fingerprint_b,
        fingerprint=fingerprint_b,
        object_ids=tuple(obj.id for obj in subset),
        display_object_ids=tuple(obj.id for obj in reversed(subset)),
        provider=full.provider,
        conversation_key=full.conversation_key,
        conversation_label=full.conversation_label,
        participants=full.participants,
        message_count=len(subset),
        start_at=full.start_at,
        end_at=full.end_at,
        fallback_summary=full.fallback_summary,
    )
    persist_stack_summary(db_session, stack=full, objects=chronological, text="summary-A")
    persist_stack_summary(db_session, stack=stack_b, objects=subset, text="summary-B")
    found_a = find_current_stack_summary(db_session, full)
    found_b = find_current_stack_summary(db_session, stack_b)
    assert found_a is not None and found_b is not None
    assert found_a.id != found_b.id
    assert found_a.text == "summary-A"
    assert found_b.text == "summary-B"
    assert found_a.metadata_["stack_fingerprint"] == full.fingerprint
    assert found_b.metadata_["stack_fingerprint"] == fingerprint_b

