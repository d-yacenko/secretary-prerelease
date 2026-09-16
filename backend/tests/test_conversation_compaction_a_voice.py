"""Voice/Assistant compaction tests for Unified Conversation A."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

import app.assistant.session as assistant_session_module
from app.assistant.inbox_review_progress import (
    InboxReviewTurnProgress,
    credited_object_ids_from_review_payload,
)
from app.assistant.reference_ids import (
    collect_object_ids_from_bounded_tool,
    collect_seen_object_ids_from_bounded_tool,
)
from app.assistant.tool_output import serialize_tool_output_for_assistant
from app.db.models import Object, User
from app.services.domain_tool_service import DomainToolService
from app.services.inbox_review_marker import InboxReviewMarkerService
from app.services.recent_source_service import inbox_feed_at
from app.tools.schemas import GetObjectInput, ListInboxSinceReviewMarkerInput


class _SessionProxy:
    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        return None

    def commit(self) -> None:
        self._session.flush()

    def rollback(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._session, name)


@pytest.fixture
def interactive_session(db_session, monkeypatch):
    monkeypatch.setattr(assistant_session_module, "SessionLocal", lambda: _SessionProxy(db_session))
    monkeypatch.setattr(
        "app.assistant.session.resolve_embedding_service_for_user",
        lambda session, user_id: None,
    )

    @contextmanager
    def _noop_trace(*args, **kwargs):
        yield

    monkeypatch.setattr("app.services.assistant_service.ai_trace_session", _noop_trace)
    return db_session


@pytest.fixture
def marker_user(db_session) -> UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="compaction-voice"))
    db_session.flush()
    return user_id


def _stamp(obj: Object, when: datetime) -> Object:
    obj.created_at = when
    obj.updated_at = when
    obj.occurred_at = when
    return obj


def _chat(
    session: Session,
    user_id: UUID,
    title: str,
    when: datetime,
    *,
    provider: str,
    chat_id: str,
    author: str,
    name: str,
    extra: dict | None = None,
) -> Object:
    metadata = {
        "account_id": "acc",
        "chat_id": chat_id,
        "from_user_id": author,
        "from_display_name": name,
        "chat_display_name": name,
        "direction": "inbound",
        **(extra or {}),
    }
    if provider == "mattermost":
        metadata.update(
            {
                "channel_id": chat_id,
                "channel_type": "D",
                "channel_display_name": name,
                "author_user_id": author,
                "author_display_name": name,
            }
        )
    obj = Object(
        id=uuid.uuid4(),
        user_id=user_id,
        kind="chat_message",
        title=title,
        body=title,
        origin="source",
        state="observed",
        provider=provider,
        external_id=f"ext-{uuid.uuid4()}",
        metadata_=metadata,
    )
    session.add(obj)
    session.flush()
    return _stamp(obj, when)


def _email_singleton(session: Session, user_id: UUID, title: str, when: datetime) -> Object:
    obj = Object(
        id=uuid.uuid4(),
        user_id=user_id,
        kind="email",
        title=title,
        body=title,
        origin="source",
        state="observed",
        provider="gmail",
        external_id=f"ext-{uuid.uuid4()}",
        metadata_={
            "account_id": "g",
            "thread_id": str(uuid.uuid4()),
            "sender": "solo@x.test",
            "recipients": ["me@x.test"],
            "labels": ["INBOX"],
            "subject": title,
            "headers": {},
        },
    )
    session.add(obj)
    session.flush()
    return _stamp(obj, when)


def _frozen_window(session: Session, user_id: UUID) -> tuple[Object, list[Object]]:
    t0 = datetime(2026, 9, 15, 12, tzinfo=UTC)
    anchor = _email_singleton(session, user_id, "anchor", t0)
    objects: list[Object] = []
    for i in range(9):
        objects.append(
            _chat(
                session,
                user_id,
                f"tg {i}",
                t0 + timedelta(minutes=1, seconds=i * 8),
                provider="telegram",
                chat_id="brain",
                author="u1",
                name="BrainTor",
            )
        )
    for i in range(7):
        author = "ann" if i % 2 == 0 else "bob"
        objects.append(
            _chat(
                session,
                user_id,
                f"mm {i}",
                t0 + timedelta(minutes=20, seconds=i * 40),
                provider="mattermost",
                chat_id="dm-ab",
                author=author,
                name=author,
            )
        )
    for i in range(3):
        objects.append(
            _email_singleton(
                session,
                user_id,
                f"solo {i}",
                t0 + timedelta(minutes=40 + i),
            )
        )
    InboxReviewMarkerService(session, user_id).set_marker(anchor.id)
    session.flush()
    return anchor, objects


def test_compact_review_narrates_stacks_not_every_message(interactive_session, marker_user: UUID) -> None:
    session = interactive_session
    _frozen_window(session, marker_user)
    page = DomainToolService(session, marker_user, None).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=50)
    )
    assert page.total_count == 19
    assert page.returned_count == 19
    assert len(page.items) == 19
    assert page.conversation_count == 5
    compact_types = [item.type for item in page.compact_items]
    assert compact_types.count("stack") == 2
    assert compact_types.count("singleton") == 3
    assert len(page.compact_items) == 5
    raw = page.model_dump(mode="json")
    model = serialize_tool_output_for_assistant("list_inbox_since_review_marker", raw)
    compact = model.model_visible_payload["compact_items"]
    assert len(compact) == 5
    stacked_ids = []
    for item in compact:
        if item["type"] == "stack":
            stacked_ids.extend(item["stack"]["object_ids"])
    assert len(stacked_ids) == 16
    candidates: list[UUID] = []
    collect_object_ids_from_bounded_tool(
        "list_inbox_since_review_marker", model.model_visible_payload, candidates, []
    )
    seen = collect_seen_object_ids_from_bounded_tool(
        "list_inbox_since_review_marker", model.model_visible_payload
    )
    assert len(set(candidates) - {page.anchor_object_id}) == 19
    assert page.snapshot_top_object_id in seen


def test_full_review_receipt_still_covers_raw_count(interactive_session, marker_user: UUID) -> None:
    session = interactive_session
    anchor, objects = _frozen_window(session, marker_user)
    tools = DomainToolService(session, marker_user, None)
    page = tools.list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=50)
    )
    progress = InboxReviewTurnProgress()
    progress.observe(
        arguments={"purpose": "review", "limit": 50},
        payload=serialize_tool_output_for_assistant(
            "list_inbox_since_review_marker", page.model_dump(mode="json")
        ).model_visible_payload,
    )
    receipt = progress.verified_receipt()
    assert receipt is not None
    assert receipt.total_count == 19
    assert receipt.anchor_before_object_id == anchor.id
    newest = max(objects, key=lambda obj: (inbox_feed_at(obj), obj.id))
    assert receipt.snapshot_top_object_id == newest.id


def test_inspect_count_does_not_move_marker(interactive_session, marker_user: UUID) -> None:
    session = interactive_session
    anchor, _objects = _frozen_window(session, marker_user)
    before = InboxReviewMarkerService(session, marker_user).get_marker()
    page = DomainToolService(session, marker_user, None).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="inspect", limit=50)
    )
    assert page.total_count == 19
    assert page.conversation_count == 5
    after = InboxReviewMarkerService(session, marker_user).get_marker()
    assert after.anchor_object_id == before.anchor_object_id == anchor.id


def test_new_arrival_after_frozen_top_excluded(interactive_session, marker_user: UUID) -> None:
    session = interactive_session
    _anchor, objects = _frozen_window(session, marker_user)
    tools = DomainToolService(session, marker_user, None)
    first = tools.list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=10)
    )
    assert first.total_count == 19
    assert first.has_more
    newest = max(objects, key=lambda obj: (inbox_feed_at(obj), obj.id))
    _email_singleton(
        session,
        marker_user,
        "after top",
        inbox_feed_at(newest) + timedelta(minutes=5),
    )
    second = tools.list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(
            purpose="review", limit=10, cursor=first.next_cursor
        )
    )
    assert second.total_count == 19
    titles = [item.title for item in first.items + second.items]
    assert "after top" not in titles


def test_stack_detail_resolves_underlying_objects(interactive_session, marker_user: UUID) -> None:
    session = interactive_session
    _frozen_window(session, marker_user)
    page = DomainToolService(session, marker_user, None).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=50)
    )
    stack = next(item.stack for item in page.compact_items if item.type == "stack")
    member = DomainToolService(session, marker_user, None).get_object(
        GetObjectInput(object_id=stack.object_ids[0])
    )
    assert member.object.id == stack.object_ids[0]


def _observe_serialized_review(tools, *, purpose: str, limit: int):
    progress = InboxReviewTurnProgress()
    cursor = None
    pages = []
    credited: set[UUID] = set()
    while True:
        page = tools.list_inbox_since_review_marker(
            ListInboxSinceReviewMarkerInput(purpose=purpose, limit=limit, cursor=cursor)
        )
        raw = page.model_dump(mode="json")
        visible = serialize_tool_output_for_assistant(
            "list_inbox_since_review_marker", raw
        ).model_visible_payload
        pages.append(visible)
        args = {"purpose": purpose, "limit": limit}
        if cursor:
            args["cursor"] = cursor
        progress.observe(arguments=args, payload=visible)
        credited |= credited_object_ids_from_review_payload(visible)
        if not visible.get("has_more"):
            break
        cursor = visible.get("next_cursor")
        assert cursor
        assert len(pages) < 80
    return progress, pages, credited


def test_long_singleton_truncation_receipt_covers_exactly_visible(
    interactive_session, marker_user: UUID, monkeypatch
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 15, 8, tzinfo=UTC)
    anchor = _email_singleton(session, marker_user, "anchor", t0)
    body = "word " * 400
    created = [
        _email_singleton(session, marker_user, f"solo-{i:02d}", t0 + timedelta(minutes=i + 1))
        for i in range(32)
    ]
    for obj in created:
        obj.body = body
        obj.title = f"{obj.title} " + ("title " * 40)
    InboxReviewMarkerService(session, marker_user).set_marker(anchor.id)
    session.flush()
    monkeypatch.setattr("app.assistant.tool_output.MAX_ASSISTANT_TOOL_OUTPUT_CHARS", 1800)
    tools = DomainToolService(session, marker_user, None)
    first = tools.list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=50)
    )
    visible = serialize_tool_output_for_assistant(
        "list_inbox_since_review_marker", first.model_dump(mode="json")
    ).model_visible_payload
    first_progress = InboxReviewTurnProgress()
    first_progress.observe(arguments={"purpose": "review"}, payload=visible)
    assert first_progress.verified_receipt() is None
    assert visible.get("has_more") is True
    assert visible.get("next_cursor")
    progress, pages, credited = _observe_serialized_review(tools, purpose="review", limit=50)
    receipt = progress.verified_receipt()
    assert receipt is not None
    assert receipt.total_count == 32
    assert credited == {obj.id for obj in created}
    assert len(pages) > 1
    all_ids = []
    for page in pages:
        all_ids.extend(credited_object_ids_from_review_payload(page))
    assert len(all_ids) == len(set(all_ids)) == 32


def test_compact_stack_credits_only_visible_object_ids(
    interactive_session, marker_user: UUID
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 15, 16, 6, tzinfo=UTC)
    anchor = _email_singleton(session, marker_user, "anchor", t0 - timedelta(minutes=1))
    created = [
        _chat(
            session,
            marker_user,
            f"burst {i}",
            t0 + timedelta(minutes=i),
            provider="telegram",
            chat_id="burst-32",
            author="u1",
            name="BrainTor",
        )
        for i in range(32)
    ]
    InboxReviewMarkerService(session, marker_user).set_marker(anchor.id)
    session.flush()
    from app.services.conversation_stack import group_inbox_conversation_items
    from app.services.conversation_stack_summary import persist_stack_summary

    full = group_inbox_conversation_items(list(reversed(created)))[0].stack
    persist_stack_summary(
        session,
        stack=full,
        objects=created,
        text="Обсуждали новую модель Fable.",
    )
    tools = DomainToolService(session, marker_user, None)
    first = tools.list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=50)
    )
    assert first.compact_items[0].stack.message_count == 32
    assert first.compact_items[0].stack.summary == "Обсуждали новую модель Fable."
    visible = serialize_tool_output_for_assistant(
        "list_inbox_since_review_marker", first.model_dump(mode="json")
    ).model_visible_payload
    compact = visible["compact_items"]
    assert len(compact) == 1
    stack = compact[0]["stack"]
    assert len(stack["object_ids"]) == 20
    assert stack["message_count"] == 20
    narration = compact[0]["narration"] or ""
    fallback = stack["fallback_summary"] or ""
    assert "20 сообщений" in narration
    assert "20 сообщений" in fallback
    assert "32" not in narration
    assert "32" not in fallback
    assert stack.get("summary") in (None, "")
    assert stack["summary_status"] == "fallback"
    assert "Fable" not in narration
    from app.services.inbox_review_snapshot_cursor import feed_at_iso

    assert stack["start_at"] == feed_at_iso(created[0].occurred_at)
    assert stack["end_at"] == feed_at_iso(created[19].occurred_at)
    first_ids = credited_object_ids_from_review_payload(visible)
    assert first_ids == {obj.id for obj in created[:20]}
    first_progress = InboxReviewTurnProgress()
    first_progress.observe(arguments={"purpose": "review"}, payload=visible)
    assert first_progress.verified_receipt() is None
    progress, pages, credited = _observe_serialized_review(tools, purpose="review", limit=50)
    assert len(pages) >= 2
    second_compact = pages[1]["compact_items"]
    assert second_compact
    second_stack = second_compact[0]["stack"]
    assert second_stack["message_count"] == 12
    assert len(second_stack["object_ids"]) == 12
    assert "12 сообщений" in (second_compact[0]["narration"] or "")
    assert "32" not in (second_compact[0]["narration"] or "")
    assert second_stack.get("summary") in (None, "")
    assert second_stack["start_at"] == feed_at_iso(created[20].occurred_at)
    assert second_stack["end_at"] == feed_at_iso(created[31].occurred_at)
    receipt = progress.verified_receipt()
    assert receipt is not None
    assert receipt.total_count == 32
    assert credited == {obj.id for obj in created}


def test_drop_compact_char_bound_is_fail_closed_until_visible(
    interactive_session, marker_user: UUID, monkeypatch
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 15, 7, tzinfo=UTC)
    anchor = _email_singleton(session, marker_user, "anchor", t0)
    created = [
        _email_singleton(session, marker_user, f"drop-{i:02d}", t0 + timedelta(minutes=i + 1))
        for i in range(32)
    ]
    for obj in created:
        obj.body = "word " * 400
        obj.title = f"{obj.title} " + ("title " * 40)
    InboxReviewMarkerService(session, marker_user).set_marker(anchor.id)
    session.flush()
    monkeypatch.setattr("app.assistant.tool_output.MAX_ASSISTANT_TOOL_OUTPUT_CHARS", 1600)
    tools = DomainToolService(session, marker_user, None)
    first = tools.list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=50)
    )
    visible = serialize_tool_output_for_assistant(
        "list_inbox_since_review_marker", first.model_dump(mode="json")
    ).model_visible_payload
    assert "compact_items" not in visible or not visible.get("compact_items")
    first_progress = InboxReviewTurnProgress()
    first_progress.observe(arguments={"purpose": "review"}, payload=visible)
    assert first_progress.verified_receipt() is None
    progress, _pages, credited = _observe_serialized_review(tools, purpose="review", limit=50)
    receipt = progress.verified_receipt()
    assert receipt is not None
    assert credited == {obj.id for obj in created}
    assert receipt.total_count == 32

