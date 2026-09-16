"""Conversation Detail Read Corrective R4 — list_conversation_members."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

import app.assistant.session as assistant_session_module
from app.assistant.tool_output import serialize_tool_output_for_assistant
from app.assistant.tool_runner import BoundAssistantToolRunner, PerTurnToolBudget
from app.db.models import Object, User
from app.llm.openai_assistant_provider import SYSTEM_INSTRUCTIONS
from app.services.conversation_stack import group_inbox_conversation_items
from app.services.domain_tool_service import DomainToolService
from app.services.inbox_review_marker import InboxReviewMarkerService
from app.services.recent_source_service import inbox_feed_at
from app.tools.assistant_contracts import ASSISTANT_FUNCTION_SCHEMAS
from app.tools.schemas import (
    ListConversationMembersInput,
    ListInboxSinceReviewMarkerInput,
)


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
    return db_session


@pytest.fixture
def detail_user(db_session) -> UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="detail-read-r4"))
    db_session.flush()
    return user_id


def _stamp(obj: Object, when: datetime) -> Object:
    obj.created_at = when
    obj.updated_at = when
    obj.occurred_at = when
    return obj


def _base(
    session: Session,
    user_id: UUID,
    *,
    kind: str,
    provider: str,
    title: str,
    when: datetime,
    metadata: dict,
    body: str | None = None,
) -> Object:
    obj = Object(
        id=uuid.uuid4(),
        user_id=user_id,
        kind=kind,
        title=title,
        body=title if body is None else body,
        origin="source",
        state="observed",
        provider=provider,
        external_id=f"ext-{uuid.uuid4()}",
        metadata_=metadata,
    )
    session.add(obj)
    session.flush()
    return _stamp(obj, when)


def _telegram(
    session,
    user_id,
    title,
    when,
    chat_id,
    *,
    sender="u1",
    name="BrainTor",
    body=None,
    extra=None,
):
    metadata = {
        "account_id": "tg-1",
        "chat_id": chat_id,
        "from_user_id": sender,
        "from_display_name": name,
        "chat_display_name": name,
        "direction": "inbound",
        **(extra or {}),
    }
    return _base(
        session,
        user_id,
        kind="chat_message",
        provider="telegram",
        title=title,
        when=when,
        body=body,
        metadata=metadata,
    )


def _gmail(session, user_id, title, when, thread_id, *, sender, body=None):
    return _base(
        session,
        user_id,
        kind="email",
        provider="gmail",
        title=title,
        when=when,
        body=body,
        metadata={
            "account_id": "acc-1",
            "thread_id": thread_id,
            "sender": sender,
            "recipients": ["me@x.test"],
            "cc": [],
            "subject": title,
            "labels": ["INBOX"],
            "headers": {},
        },
    )


def _mm(session, user_id, title, when, *, channel_id, author, author_name, root_id=None, channel_type="O"):
    return _base(
        session,
        user_id,
        kind="chat_message",
        provider="mattermost",
        title=title,
        when=when,
        metadata={
            "account_id": "mm-1",
            "channel_id": channel_id,
            "channel_type": channel_type,
            "channel_display_name": "town-square",
            "author_user_id": author,
            "author_display_name": author_name,
            "root_id": root_id,
            "post_id": str(uuid.uuid4()),
        },
    )


def _tools(session, user_id) -> DomainToolService:
    return DomainToolService(session, user_id, None)


def _members(session, user_id, object_id, **kwargs):
    return _tools(session, user_id).list_conversation_members(
        ListConversationMembersInput(object_id=object_id, **kwargs)
    )


def test_telegram_six_message_stack_anchor_mid_returns_all_chronological(db_session, detail_user):
    t0 = datetime(2026, 9, 16, 10, tzinfo=UTC)
    rows = [
        _telegram(db_session, detail_user, f"m{i}", t0 + timedelta(minutes=i), "bt-six")
        for i in range(6)
    ]
    page = _members(db_session, detail_user, rows[2].id)
    assert page.total_member_count == 6
    assert page.has_more is False
    assert [item.object_id for item in page.members] == [row.id for row in rows]
    feeds = [item.feed_at for item in page.members]
    assert feeds == sorted(feeds)
    assert page.conversation_label == "BrainTor"
    assert page.provider == "telegram"


def test_two_braintor_bursts_do_not_merge_across_gap(db_session, detail_user):
    t0 = datetime(2026, 9, 16, 11, tzinfo=UTC)
    first = [
        _telegram(db_session, detail_user, f"first {i}", t0 + timedelta(minutes=i), "bt-gap")
        for i in range(3)
    ]
    second = [
        _telegram(
            db_session,
            detail_user,
            f"second {i}",
            t0 + timedelta(minutes=20 + i),
            "bt-gap",
        )
        for i in range(3)
    ]
    page = _members(db_session, detail_user, first[1].id)
    ids = {item.object_id for item in page.members}
    assert ids == {row.id for row in first}
    assert {row.id for row in second}.isdisjoint(ids)


def test_mattermost_interleaving_reuses_existing_grouping(db_session, detail_user):
    t0 = datetime(2026, 9, 16, 12, 41, tzinfo=UTC)
    a1 = _mm(db_session, detail_user, "A1", t0, channel_id="town", author="ann", author_name="Ann")
    b1 = _mm(
        db_session, detail_user, "B1", t0 + timedelta(minutes=1), channel_id="town", author="bob", author_name="Bob"
    )
    a2 = _mm(
        db_session, detail_user, "A2", t0 + timedelta(minutes=2), channel_id="town", author="ann", author_name="Ann"
    )
    x = _mm(
        db_session,
        detail_user,
        "unrelated X",
        t0 + timedelta(minutes=3),
        channel_id="town",
        author="xeno",
        author_name="Xeno",
    )
    b2 = _mm(
        db_session, detail_user, "B2", t0 + timedelta(minutes=4), channel_id="town", author="bob", author_name="Bob"
    )
    a3 = _mm(
        db_session, detail_user, "A3", t0 + timedelta(minutes=5), channel_id="town", author="ann", author_name="Ann"
    )
    rows = [a1, b1, a2, x, b2, a3]
    newest_first = sorted(rows, key=lambda obj: (inbox_feed_at(obj), obj.id), reverse=True)
    expected = next(
        item for item in group_inbox_conversation_items(newest_first) if a1.id in item.object_ids
    )
    page = _members(db_session, detail_user, a1.id)
    assert [item.object_id for item in page.members] == list(expected.stack.object_ids)
    assert x.id not in {item.object_id for item in page.members}
    assert a3.id not in {item.object_id for item in page.members}


def test_mattermost_rooted_thread_members(db_session, detail_user):
    t0 = datetime(2026, 9, 16, 13, tzinfo=UTC)
    rows = [
        _mm(
            db_session,
            detail_user,
            f"th {i}",
            t0 + timedelta(minutes=i),
            channel_id="ch1",
            author="a",
            author_name="A",
            root_id="root-r4",
        )
        for i in range(3)
    ]
    other = _mm(
        db_session,
        detail_user,
        "other root",
        t0 + timedelta(hours=1),
        channel_id="ch1",
        author="a",
        author_name="A",
        root_id="root-other",
    )
    page = _members(db_session, detail_user, rows[1].id)
    assert [item.object_id for item in page.members] == [row.id for row in rows]
    assert other.id not in {item.object_id for item in page.members}


def test_gmail_same_thread_burst_boundary(db_session, detail_user):
    t0 = datetime(2026, 9, 16, 14, tzinfo=UTC)
    thread = "thread-r4"
    first = _gmail(db_session, detail_user, "Hello", t0, thread, sender="Ada <ada@x.test>")
    second = _gmail(
        db_session,
        detail_user,
        "Hello",
        t0 + timedelta(minutes=16),
        thread,
        sender="Ada <ada@x.test>",
    )
    page = _members(db_session, detail_user, first.id)
    assert [item.object_id for item in page.members] == [first.id]
    assert second.id not in {item.object_id for item in page.members}


def test_detail_read_does_not_advance_marker_or_create_receipt(interactive_session, detail_user):
    session = interactive_session
    t0 = datetime(2026, 9, 16, 15, tzinfo=UTC)
    older = _telegram(session, detail_user, "older", t0, "bt-marker")
    rows = [
        _telegram(session, detail_user, f"new {i}", t0 + timedelta(minutes=10 + i), "bt-marker")
        for i in range(3)
    ]
    InboxReviewMarkerService(session, detail_user).set_marker(older.id)
    session.flush()
    before = InboxReviewMarkerService(session, detail_user).get_marker()
    runner = BoundAssistantToolRunner(PerTurnToolBudget(), detail_user)
    result = runner("list_conversation_members", {"object_id": str(rows[1].id)})
    assert result.success is True
    after = InboxReviewMarkerService(session, detail_user).get_marker()
    assert after is not None
    assert after.anchor_object_id == before.anchor_object_id
    assert after.anchor_feed_at == before.anchor_feed_at
    assert runner._budget.inbox_review.verified_receipt() is None
    leftover = _tools(session, detail_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="inspect")
    )
    assert leftover.total_count == 3


def test_voice_without_transcript_placeholder_continues(db_session, detail_user):
    t0 = datetime(2026, 9, 16, 16, tzinfo=UTC)
    first = _telegram(db_session, detail_user, "text one", t0, "bt-voice")
    voice = _telegram(
        db_session,
        detail_user,
        "BrainTor: voice",
        t0 + timedelta(minutes=1),
        "bt-voice",
        body="",
        extra={"message_type": "voice"},
    )
    third = _telegram(db_session, detail_user, "text three", t0 + timedelta(minutes=2), "bt-voice")
    page = _members(db_session, detail_user, voice.id)
    assert [item.object_id for item in page.members] == [first.id, voice.id, third.id]
    assert page.members[0].narration == "text one"
    assert page.members[1].narration == "голосовое сообщение без расшифровки"
    assert page.members[1].excerpt is None
    assert page.members[2].narration == "text three"


def test_voice_with_transcript_is_readable(db_session, detail_user):
    t0 = datetime(2026, 9, 16, 17, tzinfo=UTC)
    voice = _telegram(
        db_session,
        detail_user,
        "BrainTor: voice",
        t0,
        "bt-voice-tx",
        body="уже расшифрованный текст",
        extra={"message_type": "voice"},
    )
    page = _members(db_session, detail_user, voice.id)
    assert page.members[0].narration == "уже расшифрованный текст"
    assert page.members[0].media_type == "voice"


def test_ambiguous_natural_discovery_prompt_does_not_guess() -> None:
    text = SYSTEM_INSTRUCTIONS
    description = ASSISTANT_FUNCTION_SCHEMAS["list_conversation_members"]["description"]
    for phrase in (
        "прочитай подробно переписку с BrainTor",
        "прочитай все сообщения в переписке с BrainTor",
        "а теперь зачитай сообщения из этой переписки",
        "прочитай эту переписку по сообщениям",
        "что именно он там написал?",
        "Never guess among ambiguous conversations",
        "list_conversation_members",
    ):
        assert phrase in text
        assert phrase in description or phrase == "list_conversation_members"
    assert "does NOT move the Inbox review marker" in description
    assert "inbox_review_receipt" in description
    assert "list_conversation_members" in ASSISTANT_FUNCTION_SCHEMAS


def test_compact_summary_review_remains_unchanged(db_session, detail_user):
    t0 = datetime(2026, 9, 16, 18, tzinfo=UTC)
    anchor = _gmail(db_session, detail_user, "anchor", t0, "anchor-thread", sender="solo@x.test")
    rows = [
        _telegram(db_session, detail_user, f"stack {i}", t0 + timedelta(minutes=1 + i), "bt-compact")
        for i in range(4)
    ]
    InboxReviewMarkerService(db_session, detail_user).set_marker(anchor.id)
    db_session.flush()
    page = _tools(db_session, detail_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=50)
    )
    assert page.total_count == 4
    assert len(page.items) == 4
    assert page.conversation_count == 1
    assert [item.type for item in page.compact_items] == ["stack"]
    assert page.compact_items[0].stack.message_count == 4
    raw = page.model_dump(mode="json")
    model = serialize_tool_output_for_assistant("list_inbox_since_review_marker", raw)
    compact = model.model_visible_payload["compact_items"]
    assert len(compact) == 1
    assert compact[0]["type"] == "stack"
    assert set(compact[0]["stack"]["object_ids"]) == {str(row.id) for row in rows}


def test_members_page_oldest_to_newest_and_does_not_hide_remainder(db_session, detail_user):
    t0 = datetime(2026, 9, 16, 19, tzinfo=UTC)
    rows = [
        _telegram(db_session, detail_user, f"p{i}", t0 + timedelta(minutes=i), "bt-page")
        for i in range(5)
    ]
    first = _members(db_session, detail_user, rows[3].id, limit=2)
    assert [item.object_id for item in first.members] == [rows[0].id, rows[1].id]
    assert first.has_more is True
    assert first.remaining_count == 3
    assert first.next_cursor
    second = _members(db_session, detail_user, rows[3].id, limit=2, cursor=first.next_cursor)
    assert [item.object_id for item in second.members] == [rows[2].id, rows[3].id]
    third = _members(db_session, detail_user, rows[3].id, limit=2, cursor=second.next_cursor)
    assert [item.object_id for item in third.members] == [rows[4].id]
    assert third.has_more is False


def _serialize_members(page):
    return serialize_tool_output_for_assistant(
        "list_conversation_members", page.model_dump(mode="json")
    ).model_visible_payload


def _traverse_visible(session, user_id, object_id, *, limit: int):
    seen: list[UUID] = []
    cursor = None
    pages = 0
    while True:
        pages += 1
        assert pages <= 40
        raw = _members(session, user_id, object_id, limit=limit, cursor=cursor)
        payload = _serialize_members(raw)
        visible = payload["members"]
        assert visible
        ids = [UUID(item["object_id"]) for item in visible]
        seen.extend(ids)
        if not payload["has_more"]:
            assert payload["remaining_count"] == 0
            assert not payload.get("next_cursor")
            return seen, payload, raw
        assert payload["remaining_count"] > 0
        assert payload["next_cursor"]
        cursor = payload["next_cursor"]


def test_char_trim_of_complete_page_does_not_hide_members(db_session, detail_user, monkeypatch):
    t0 = datetime(2026, 9, 16, 20, tzinfo=UTC)
    body = ("длинный текст переписки " * 40).strip()
    rows = [
        _telegram(
            db_session,
            detail_user,
            f"long-{i}-" + ("T" * 200),
            t0 + timedelta(minutes=i),
            "bt-trim-20",
            body=body,
        )
        for i in range(20)
    ]
    raw = _members(db_session, detail_user, rows[7].id, limit=20)
    assert raw.total_member_count == 20
    assert raw.has_more is False
    monkeypatch.setattr("app.assistant.tool_output.MAX_ASSISTANT_TOOL_OUTPUT_CHARS", 3200)
    payload = _serialize_members(raw)
    visible_n = payload["returned_count"]
    assert 1 <= visible_n < 20
    assert visible_n == len(payload["members"])
    assert payload["has_more"] is True
    assert payload["remaining_count"] == 20 - visible_n
    assert payload["next_cursor"]
    second = _members(
        db_session, detail_user, rows[7].id, limit=20, cursor=payload["next_cursor"]
    )
    assert second.members[0].object_id == rows[visible_n].id
    seen, _, _ = _traverse_visible(db_session, detail_user, rows[7].id, limit=20)
    assert seen == [row.id for row in rows]


def test_char_trim_mid_service_page_does_not_skip_hidden_prefix(db_session, detail_user, monkeypatch):
    t0 = datetime(2026, 9, 16, 21, tzinfo=UTC)
    body = ("ещё более длинное сообщение " * 40).strip()
    rows = [
        _telegram(
            db_session,
            detail_user,
            f"big-{i}-" + ("Q" * 200),
            t0 + timedelta(minutes=i),
            "bt-trim-30",
            body=body,
        )
        for i in range(30)
    ]
    raw = _members(db_session, detail_user, rows[0].id, limit=20)
    assert raw.returned_count == 20
    assert raw.has_more is True
    assert raw.remaining_count == 10
    monkeypatch.setattr("app.assistant.tool_output.MAX_ASSISTANT_TOOL_OUTPUT_CHARS", 3600)
    payload = _serialize_members(raw)
    visible_n = payload["returned_count"]
    assert 1 <= visible_n < 20
    assert payload["has_more"] is True
    assert payload["remaining_count"] == 30 - visible_n
    assert payload["next_cursor"] != raw.next_cursor
    second_raw = _members(
        db_session, detail_user, rows[0].id, limit=20, cursor=payload["next_cursor"]
    )
    assert second_raw.members[0].object_id == rows[visible_n].id
    seen, _, _ = _traverse_visible(db_session, detail_user, rows[0].id, limit=20)
    assert seen == [row.id for row in rows]
    assert len(set(seen)) == 30


def test_hard_char_bound_keeps_at_least_one_member(db_session, detail_user, monkeypatch):
    t0 = datetime(2026, 9, 16, 22, tzinfo=UTC)
    body = ("x" * 400)
    rows = [
        _telegram(
            db_session,
            detail_user,
            "title-" + ("Y" * 300),
            t0 + timedelta(minutes=i),
            "bt-hard-bound",
            body=body,
        )
        for i in range(6)
    ]
    raw = _members(db_session, detail_user, rows[2].id, limit=20)
    monkeypatch.setattr("app.assistant.tool_output.MAX_ASSISTANT_TOOL_OUTPUT_CHARS", 900)
    payload = _serialize_members(raw)
    assert payload["returned_count"] >= 1
    assert payload["members"]
    assert payload["members"][0]["object_id"] == str(rows[0].id)
    assert payload["has_more"] is True
    assert payload["next_cursor"]
    second = _members(db_session, detail_user, rows[2].id, cursor=payload["next_cursor"])
    assert second.members[0].object_id == rows[payload["returned_count"]].id
    seen, _, _ = _traverse_visible(db_session, detail_user, rows[2].id, limit=20)
    assert seen == [row.id for row in rows]


def test_detail_read_trim_does_not_move_marker(interactive_session, detail_user, monkeypatch):
    session = interactive_session
    t0 = datetime(2026, 9, 16, 23, tzinfo=UTC)
    older = _telegram(session, detail_user, "older-trim", t0, "bt-trim-marker")
    rows = [
        _telegram(
            session,
            detail_user,
            f"new-trim {i}",
            t0 + timedelta(minutes=10 + i),
            "bt-trim-marker",
            body=("голос и текст " * 50).strip(),
        )
        for i in range(8)
    ]
    InboxReviewMarkerService(session, detail_user).set_marker(older.id)
    session.flush()
    before = InboxReviewMarkerService(session, detail_user).get_marker()
    monkeypatch.setattr("app.assistant.tool_output.MAX_ASSISTANT_TOOL_OUTPUT_CHARS", 2800)
    runner = BoundAssistantToolRunner(PerTurnToolBudget(), detail_user)
    result = runner("list_conversation_members", {"object_id": str(rows[3].id), "limit": 20})
    assert result.success is True
    payload = result.model_visible_payload
    assert payload["has_more"] is True
    after = InboxReviewMarkerService(session, detail_user).get_marker()
    assert after.anchor_object_id == before.anchor_object_id
    assert runner._budget.inbox_review.verified_receipt() is None
