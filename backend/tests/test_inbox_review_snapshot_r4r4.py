"""Voice Assistant A R4-R4 — frozen Inbox review snapshots and verified completion."""

from __future__ import annotations

import base64
import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.assistant.session as assistant_session_module
from app.api.deps import get_db
from app.assistant.inbox_review_progress import InboxReviewTurnProgress
from app.assistant.reference_ids import (
    collect_object_ids_from_bounded_tool,
    collect_seen_object_ids_from_bounded_tool,
)
from app.assistant.tool_output import serialize_tool_output_for_assistant
from app.assistant.tool_runner import BoundAssistantToolRunner, PerTurnToolBudget
from app.db.models import ExternalActionAttempt, InboxReviewMarker, Job, Object, User
from app.llm.assistant_models import AssistantHistoryMessage, AssistantProviderResult
from app.main import app
from app.services.assistant_service import AssistantService
from app.services.domain_tool_service import DomainToolService
from app.services.inbox_review_marker import InboxReviewMarkerService, feed_tuple_is_newer
from app.services.inbox_review_snapshot_cursor import (
    decode_inbox_review_snapshot_cursor,
    encode_inbox_review_snapshot_cursor,
)
from app.services.recent_source_service import RecentSourceService, inbox_feed_at
from app.tools.schemas import ListInboxSinceReviewMarkerInput, ToolError
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient


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
    db_session.add(User(id=user_id, display_name="review-snapshot-r4r4"))
    db_session.flush()
    return user_id


@pytest.fixture
def wf_client(db_session, auth_headers):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as raw:
        yield AuthTestClient(raw, auth_headers)
    app.dependency_overrides.clear()


def _stamp(obj: Object, created_at: datetime, occurred_at: datetime | None = None) -> Object:
    obj.created_at = created_at
    obj.updated_at = created_at
    obj.occurred_at = occurred_at
    return obj


def _email(
    db_session: Session,
    title: str,
    *,
    created_at: datetime,
    object_id: UUID | None = None,
    user_id: UUID | None = None,
    body: str | None = None,
    provider: str = "gmail",
) -> Object:
    owner = user_id or BOOTSTRAP_USER_ID
    obj = Object(
        id=object_id or uuid.uuid4(),
        user_id=owner,
        kind="email",
        title=title,
        body=body,
        origin="source",
        state="observed",
        provider=provider,
        external_id=f"ext-{uuid.uuid4()}",
        metadata_={},
    )
    db_session.add(obj)
    db_session.flush()
    return _stamp(obj, created_at, created_at)


def _tools(session: Session, user_id: UUID) -> DomainToolService:
    return DomainToolService(session, user_id, None)


def _marker(session: Session, user_id: UUID) -> InboxReviewMarkerService:
    return InboxReviewMarkerService(session, user_id)


def _runner(
    user_id: UUID, seen: list[UUID] | None = None, max_calls: int | None = None
) -> tuple[BoundAssistantToolRunner, PerTurnToolBudget]:
    kwargs = {"initial_seen_object_ids": seen or []}
    if max_calls is not None:
        kwargs["max_calls"] = max_calls
    budget = PerTurnToolBudget(**kwargs)
    return BoundAssistantToolRunner(budget, user_id), budget


class _PagingReviewProvider:
    def __init__(self, purpose: str = "review", follow: bool = True, inject_cursor: str | None = None):
        self.purpose = purpose
        self.follow = follow
        self.inject_cursor = inject_cursor
        self.calls: list[tuple[str, dict]] = []
        self.validated_arguments: list[dict] = []

    def run(
        self,
        message: str,
        history: list[AssistantHistoryMessage],
        ui_context: str,
        reference_datetime,
        timezone: str,
        tool_runner,
        identity_facts=None,
    ) -> AssistantProviderResult:
        cursor = self.inject_cursor
        while True:
            args: dict = {"purpose": self.purpose, "limit": 20}
            if cursor:
                args["cursor"] = cursor
            result = tool_runner("list_inbox_since_review_marker", args)
            self.calls.append(("list_inbox_since_review_marker", args))
            if result.validated_arguments is not None:
                self.validated_arguments.append(dict(result.validated_arguments))
            if not self.follow:
                break
            payload = result.model_visible_payload or {}
            if payload.get("has_more") and payload.get("next_cursor"):
                cursor = payload["next_cursor"]
                continue
            break
        return AssistantProviderResult(answer="Inbox review.", candidate_object_ids=[], affected_object_ids=[])

    def run_text_only(self, message: str, context: str) -> AssistantProviderResult:
        return AssistantProviderResult(answer="done", candidate_object_ids=[], affected_object_ids=[])


def test_paginate_more_than_twenty_no_skip_or_dup(db_session: Session, marker_user: UUID) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "A", created_at=t0, user_id=marker_user)
    newer = [
        _email(db_session, f"N{i:02d}", created_at=t0 + timedelta(minutes=i + 1), user_id=marker_user)
        for i in range(37)
    ]
    _marker(db_session, marker_user).set_marker(anchor.id)
    db_session.flush()

    first = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=20)
    )
    assert first.total_count == 37
    assert first.returned_count == 20
    assert first.remaining_count == 17
    assert first.has_more is True
    assert first.next_cursor
    assert first.snapshot_top_object_id == newer[-1].id
    assert first.snapshot_top_object_id != first.items[0].object_id
    first_ids = [item.object_id for item in first.items]
    assert first_ids == [item.id for item in newer[:20]]

    second = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=20, cursor=first.next_cursor)
    )
    assert second.total_count == 37
    assert second.snapshot_top_object_id == newer[-1].id
    assert second.returned_count == 17
    assert second.remaining_count == 0
    assert second.has_more is False
    assert second.next_cursor is None
    second_ids = [item.object_id for item in second.items]
    combined = first_ids + second_ids
    expected = [item.id for item in newer]
    assert combined == expected
    assert len(combined) == len(set(combined)) == 37
    assert combined[-1] == first.snapshot_top_object_id


def test_review_five_items_oldest_to_newest(db_session: Session, marker_user: UUID) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "A", created_at=t0, user_id=marker_user)
    items = [
        _email(db_session, f"N{i}", created_at=t0 + timedelta(hours=i + 1), user_id=marker_user)
        for i in range(5)
    ]
    _marker(db_session, marker_user).set_marker(anchor.id)
    db_session.flush()
    page = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=20)
    )
    assert [item.object_id for item in page.items] == [item.id for item in items]
    assert [item.title for item in page.items] == ["N0", "N1", "N2", "N3", "N4"]
    assert page.snapshot_top_object_id == items[-1].id
    assert page.items[-1].object_id == page.snapshot_top_object_id
    inspect_page = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="inspect", limit=20)
    )
    assert [item.object_id for item in inspect_page.items] == [item.id for item in reversed(items)]
    feed = RecentSourceService(db_session, marker_user).list_page(limit=10)
    assert [obj.id for obj in feed.items[:6]] == [
        items[-1].id,
        items[-2].id,
        items[-3].id,
        items[-4].id,
        items[-5].id,
        anchor.id,
    ]


def test_equal_feed_at_uuid_order_across_pages(db_session: Session, marker_user: UUID) -> None:
    t = datetime(2026, 9, 14, 12, tzinfo=UTC)
    low = UUID("00000000-0000-4000-8000-000000000001")
    mid = UUID("00000000-0000-4000-8000-000000000002")
    high = UUID("00000000-0000-4000-8000-000000000003")
    _email(db_session, "low", created_at=t, object_id=low, user_id=marker_user)
    _email(db_session, "mid", created_at=t, object_id=mid, user_id=marker_user)
    _email(db_session, "high", created_at=t, object_id=high, user_id=marker_user)
    db_session.flush()
    assert feed_tuple_is_newer(t, high, t, mid)
    _marker(db_session, marker_user).set_marker(low)
    first = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(limit=1, purpose="review")
    )
    assert [item.object_id for item in first.items] == [mid]
    assert first.total_count == 2
    assert first.snapshot_top_object_id == high
    second = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(limit=1, purpose="review", cursor=first.next_cursor)
    )
    assert [item.object_id for item in second.items] == [high]
    assert second.has_more is False
    assert second.items[-1].object_id == first.snapshot_top_object_id


def test_exact_count_without_full_enumeration(db_session: Session, marker_user: UUID) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "A", created_at=t0, user_id=marker_user)
    for i in range(25):
        _email(db_session, f"N{i:02d}", created_at=t0 + timedelta(minutes=i + 1), user_id=marker_user)
    _marker(db_session, marker_user).set_marker(anchor.id)
    db_session.flush()
    page = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="inspect", limit=1)
    )
    assert page.total_count == 25
    assert page.returned_count == 1
    assert page.remaining_count == 24
    assert page.purpose == "inspect"


def test_continuation_excludes_arrival_above_snapshot_top(
    db_session: Session, marker_user: UUID
) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "A", created_at=t0, user_id=marker_user)
    n1 = _email(db_session, "N1", created_at=t0 + timedelta(hours=1), user_id=marker_user)
    n2 = _email(db_session, "N2", created_at=t0 + timedelta(hours=2), user_id=marker_user)
    n3 = _email(db_session, "N3", created_at=t0 + timedelta(hours=3), user_id=marker_user)
    _marker(db_session, marker_user).set_marker(anchor.id)
    db_session.flush()
    first = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=2)
    )
    assert [item.object_id for item in first.items] == [n1.id, n2.id]
    assert first.snapshot_top_object_id == n3.id
    assert first.remaining_count == 1
    n4 = _email(db_session, "N4", created_at=t0 + timedelta(hours=4), user_id=marker_user)
    db_session.flush()
    second = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=2, cursor=first.next_cursor)
    )
    ids = [item.object_id for item in second.items]
    assert ids == [n3.id]
    assert n4.id not in ids
    assert first.snapshot_top_object_id == n3.id


def test_malformed_and_foreign_cursor_fail_closed(db_session: Session, marker_user: UUID) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "A", created_at=t0, user_id=marker_user)
    top = _email(db_session, "N1", created_at=t0 + timedelta(hours=1), user_id=marker_user)
    _marker(db_session, marker_user).set_marker(anchor.id)
    db_session.flush()
    with pytest.raises(ToolError, match="invalid inbox review cursor"):
        _tools(db_session, marker_user).list_inbox_since_review_marker(
            ListInboxSinceReviewMarkerInput(cursor="%%%")
        )
    other_top_time = t0 + timedelta(hours=2)
    bad = encode_inbox_review_snapshot_cursor(
        anchor_object_id=anchor.id,
        anchor_feed_at=inbox_feed_at(anchor),
        snapshot_top_object_id=top.id,
        snapshot_top_feed_at=inbox_feed_at(top),
        last_object_id=uuid.uuid4(),
        last_feed_at=other_top_time,
        direction="asc",
    )
    with pytest.raises(ToolError, match="invalid inbox review cursor"):
        _tools(db_session, marker_user).list_inbox_since_review_marker(
            ListInboxSinceReviewMarkerInput(cursor=bad, purpose="review")
        )
    extra = _email(db_session, "N2", created_at=t0 + timedelta(hours=2), user_id=marker_user)
    db_session.flush()
    inspect_page = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="inspect", limit=1)
    )
    assert inspect_page.next_cursor
    assert inspect_page.items[0].object_id == extra.id
    with pytest.raises(ToolError, match="invalid inbox review cursor"):
        _tools(db_session, marker_user).list_inbox_since_review_marker(
            ListInboxSinceReviewMarkerInput(purpose="review", cursor=inspect_page.next_cursor)
        )
    review_page = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=1)
    )
    assert review_page.next_cursor
    assert review_page.items[0].object_id == top.id
    with pytest.raises(ToolError, match="invalid inbox review cursor"):
        _tools(db_session, marker_user).list_inbox_since_review_marker(
            ListInboxSinceReviewMarkerInput(
                purpose="inspect", cursor=review_page.next_cursor
            )
        )
    v1 = {
        "v": 1,
        "a_id": str(anchor.id),
        "a_at": inbox_feed_at(anchor).isoformat().replace("+00:00", "Z"),
        "t_id": str(top.id),
        "t_at": inbox_feed_at(top).isoformat().replace("+00:00", "Z"),
        "l_id": str(top.id),
        "l_at": inbox_feed_at(top).isoformat().replace("+00:00", "Z"),
    }
    raw = json.dumps(v1, separators=(",", ":"), sort_keys=True).encode("utf-8")
    v1_cursor = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    with pytest.raises(ToolError, match="invalid inbox review cursor"):
        _tools(db_session, marker_user).list_inbox_since_review_marker(
            ListInboxSinceReviewMarkerInput(purpose="review", cursor=v1_cursor)
        )


def test_anchor_seen_not_reference_candidate(db_session: Session, marker_user: UUID) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "A", created_at=t0, user_id=marker_user)
    n1 = _email(db_session, "N1", created_at=t0 + timedelta(hours=1), user_id=marker_user)
    _marker(db_session, marker_user).set_marker(anchor.id)
    db_session.flush()
    raw = (
        _tools(db_session, marker_user)
        .list_inbox_since_review_marker(ListInboxSinceReviewMarkerInput())
        .model_dump(mode="json")
    )
    payload = serialize_tool_output_for_assistant(
        "list_inbox_since_review_marker", raw
    ).model_visible_payload
    seen = collect_seen_object_ids_from_bounded_tool("list_inbox_since_review_marker", payload)
    candidates: list[UUID] = []
    collect_object_ids_from_bounded_tool("list_inbox_since_review_marker", payload, candidates, [])
    assert anchor.id in seen
    assert n1.id in seen
    assert n1.id in candidates
    assert anchor.id not in candidates


def test_inspect_never_yields_receipt(interactive_session, marker_user: UUID) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    for i in range(3):
        _email(session, f"N{i}", created_at=t0 + timedelta(hours=i + 1), user_id=marker_user)
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()
    provider = _PagingReviewProvider(purpose="inspect", follow=True)
    result = AssistantService(marker_user, provider).send_message("сколько нового?", [])
    assert result.inbox_review_receipt is None
    assert _marker(session, marker_user).get_marker().anchor_object_id == anchor.id


def test_explicit_complete_enumeration_forces_review_purpose(
    interactive_session, marker_user: UUID
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    newer = [
        _email(session, f"N{i}", created_at=t0 + timedelta(hours=i + 1), user_id=marker_user)
        for i in range(3)
    ]
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()

    provider = _PagingReviewProvider(purpose="inspect")
    result = AssistantService(marker_user, provider).send_message(
        "Перечисли все новые сообщения.", []
    )

    assert provider.validated_arguments == [{"purpose": "review", "limit": 20}]
    assert result.inbox_review_receipt is not None
    assert result.inbox_review_receipt.snapshot_top_object_id == newer[-1].id


def test_natural_complete_enumeration_with_pronoun_forces_review_purpose(
    interactive_session, marker_user: UUID
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    newer = [
        _email(session, f"N{i}", created_at=t0 + timedelta(hours=i + 1), user_id=marker_user)
        for i in range(3)
    ]
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()

    provider = _PagingReviewProvider(purpose="inspect")
    result = AssistantService(marker_user, provider).send_message(
        "Перечисли мне все новые сообщения.", []
    )

    assert provider.validated_arguments == [{"purpose": "review", "limit": 20}]
    assert result.inbox_review_receipt is not None
    assert result.inbox_review_receipt.snapshot_top_object_id == newer[-1].id


def test_explicit_count_remains_inspect_purpose(
    interactive_session, marker_user: UUID
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    _email(session, "N1", created_at=t0 + timedelta(hours=1), user_id=marker_user)
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()

    provider = _PagingReviewProvider(purpose="review")
    result = AssistantService(marker_user, provider).send_message(
        "Сколько новых сообщений?", []
    )

    assert provider.validated_arguments == [{"purpose": "inspect", "limit": 20}]
    assert result.inbox_review_receipt is None


def test_natural_count_with_possessive_remains_inspect_purpose(
    interactive_session, marker_user: UUID
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    _email(session, "N1", created_at=t0 + timedelta(hours=1), user_id=marker_user)
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()

    provider = _PagingReviewProvider(purpose="review")
    result = AssistantService(marker_user, provider).send_message(
        "Сколько у меня новых сообщений?", []
    )

    assert provider.validated_arguments == [{"purpose": "inspect", "limit": 20}]
    assert result.inbox_review_receipt is None


def test_review_final_page_yields_verified_receipt(interactive_session, marker_user: UUID) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    newer = [
        _email(session, f"N{i:02d}", created_at=t0 + timedelta(minutes=i + 1), user_id=marker_user)
        for i in range(25)
    ]
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()
    provider = _PagingReviewProvider(purpose="review", follow=True)
    result = AssistantService(marker_user, provider).send_message("что нового?", [])
    receipt = result.inbox_review_receipt
    assert receipt is not None
    assert receipt.anchor_before_object_id == anchor.id
    assert receipt.snapshot_top_object_id == newer[-1].id
    assert receipt.total_count == 25
    assert _marker(session, marker_user).get_marker().anchor_object_id == anchor.id
    assert len(provider.calls) >= 2


def test_review_missing_next_page_yields_no_receipt(interactive_session, marker_user: UUID) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    for i in range(25):
        _email(session, f"N{i:02d}", created_at=t0 + timedelta(minutes=i + 1), user_id=marker_user)
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()
    provider = _PagingReviewProvider(purpose="review", follow=False)
    result = AssistantService(marker_user, provider).send_message("что нового?", [])
    assert result.inbox_review_receipt is None


def test_tool_limit_yields_no_receipt(interactive_session, marker_user: UUID, monkeypatch) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    for i in range(25):
        _email(session, f"N{i:02d}", created_at=t0 + timedelta(minutes=i + 1), user_id=marker_user)
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()
    monkeypatch.setattr("app.services.assistant_service.MAX_ASSISTANT_TOOL_CALLS_PER_TURN", 1)
    provider = _PagingReviewProvider(purpose="review", follow=True)
    result = AssistantService(marker_user, provider).send_message("что нового?", [])
    assert result.inbox_review_receipt is None


def test_mixed_snapshot_cursor_yields_no_receipt(interactive_session, marker_user: UUID) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    newer = [
        _email(session, f"N{i:02d}", created_at=t0 + timedelta(minutes=i + 1), user_id=marker_user)
        for i in range(25)
    ]
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()
    first = _tools(session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=20)
    )
    foreign = encode_inbox_review_snapshot_cursor(
        anchor_object_id=anchor.id,
        anchor_feed_at=inbox_feed_at(anchor),
        snapshot_top_object_id=newer[-2].id,
        snapshot_top_feed_at=inbox_feed_at(newer[-2]),
        last_object_id=newer[-2].id,
        last_feed_at=inbox_feed_at(newer[-2]),
        direction="asc",
    )
    decode_inbox_review_snapshot_cursor(foreign)

    class _MixedProvider(_PagingReviewProvider):
        def run(self, message, history, ui_context, reference_datetime, timezone, tool_runner, identity_facts=None):
            first_result = tool_runner(
                "list_inbox_since_review_marker",
                {"purpose": "review", "limit": 20},
            )
            self.calls.append(("list_inbox_since_review_marker", {"purpose": "review"}))
            tool_runner(
                "list_inbox_since_review_marker",
                {"purpose": "review", "limit": 20, "cursor": foreign},
            )
            assert first_result.success
            return AssistantProviderResult(
                answer="mixed",
                candidate_object_ids=[],
                affected_object_ids=[],
            )

    result = AssistantService(marker_user, _MixedProvider()).send_message("что нового?", [])
    assert result.inbox_review_receipt is None
    assert first.next_cursor


def test_no_provider_read_mutations_on_review_list(
    interactive_session, marker_user: UUID
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    email = _email(session, "A", created_at=t0, user_id=marker_user, provider="gmail")
    _marker(session, marker_user).set_marker(email.id)
    newer = _email(session, "N1", created_at=t0 + timedelta(hours=1), user_id=marker_user)
    session.flush()
    snapshot = (
        email.provider,
        email.external_id,
        dict(email.metadata_),
        email.canonical_uri,
        email.status,
        email.state,
        newer.provider,
        newer.external_id,
        dict(newer.metadata_),
    )
    before_attempts = int(session.scalar(select(func.count()).select_from(ExternalActionAttempt)) or 0)
    before_jobs = int(session.scalar(select(func.count()).select_from(Job)) or 0)
    runner, budget = _runner(marker_user)
    listed = runner("list_inbox_since_review_marker", {"purpose": "review", "limit": 20})
    assert listed.success
    session.refresh(email)
    session.refresh(newer)
    assert (
        email.provider,
        email.external_id,
        dict(email.metadata_),
        email.canonical_uri,
        email.status,
        email.state,
        newer.provider,
        newer.external_id,
        dict(newer.metadata_),
    ) == snapshot
    assert budget.inbox_review.verified_receipt() is not None
    assert int(session.scalar(select(func.count()).select_from(ExternalActionAttempt)) or 0) == before_attempts
    assert int(session.scalar(select(func.count()).select_from(Job)) or 0) == before_jobs


def test_complete_review_cas_and_new_arrival(
    db_session: Session, marker_user: UUID
) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "A", created_at=t0, user_id=marker_user)
    n1 = _email(db_session, "N1", created_at=t0 + timedelta(hours=1), user_id=marker_user)
    n2 = _email(db_session, "N2", created_at=t0 + timedelta(hours=2), user_id=marker_user)
    n3 = _email(db_session, "N3", created_at=t0 + timedelta(hours=3), user_id=marker_user)
    svc = _marker(db_session, marker_user)
    svc.set_marker(anchor.id)
    db_session.flush()
    n4 = _email(db_session, "N4", created_at=t0 + timedelta(hours=4), user_id=marker_user)
    db_session.flush()
    result = svc.complete_review(
        expected_anchor_object_id=anchor.id,
        expected_anchor_feed_at=inbox_feed_at(anchor),
        snapshot_top_object_id=n3.id,
        snapshot_top_feed_at=inbox_feed_at(n3),
    )
    assert result.status == "advanced"
    assert result.marker.anchor_object_id == n3.id
    leftover = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="inspect")
    )
    assert [item.object_id for item in leftover.items] == [n4.id]
    already = svc.complete_review(
        expected_anchor_object_id=anchor.id,
        expected_anchor_feed_at=inbox_feed_at(anchor),
        snapshot_top_object_id=n3.id,
        snapshot_top_feed_at=inbox_feed_at(n3),
    )
    assert already.status == "already_current"
    assert already.marker.anchor_object_id == n3.id
    svc.set_marker(n1.id)
    db_session.flush()
    conflict = svc.complete_review(
        expected_anchor_object_id=anchor.id,
        expected_anchor_feed_at=inbox_feed_at(anchor),
        snapshot_top_object_id=n3.id,
        snapshot_top_feed_at=inbox_feed_at(n3),
    )
    assert conflict.status == "conflict"
    assert conflict.marker.anchor_object_id == n1.id
    assert n2.id


def test_complete_endpoint_cas(wf_client, db_session: Session) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "A", created_at=t0)
    top = _email(db_session, "N3", created_at=t0 + timedelta(hours=3))
    db_session.flush()
    wf_client.put("/inbox/review-marker", json={"after_object_id": str(anchor.id)})
    response = wf_client.post(
        "/inbox/review-marker/complete",
        json={
            "anchor_before_object_id": str(anchor.id),
            "anchor_before_feed_at": inbox_feed_at(anchor).isoformat().replace("+00:00", "Z"),
            "snapshot_top_object_id": str(top.id),
            "snapshot_top_feed_at": inbox_feed_at(top).isoformat().replace("+00:00", "Z"),
            "total_count": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "advanced"
    assert body["review_marker"]["anchor_object_id"] == str(top.id)
    current = db_session.get(InboxReviewMarker, BOOTSTRAP_USER_ID)
    assert current is not None
    assert current.anchor_object_id == top.id


def test_full_review_completion_moves_marker_to_newest_top(
    db_session: Session, marker_user: UUID
) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "A", created_at=t0, user_id=marker_user)
    items = [
        _email(db_session, f"N{i}", created_at=t0 + timedelta(hours=i + 1), user_id=marker_user)
        for i in range(5)
    ]
    svc = _marker(db_session, marker_user)
    svc.set_marker(anchor.id)
    db_session.flush()
    page = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review", limit=20)
    )
    assert page.items[-1].object_id == page.snapshot_top_object_id == items[-1].id
    result = svc.complete_review(
        expected_anchor_object_id=anchor.id,
        expected_anchor_feed_at=inbox_feed_at(anchor),
        snapshot_top_object_id=page.snapshot_top_object_id,
        snapshot_top_feed_at=inbox_feed_at(items[-1]),
    )
    assert result.status == "advanced"
    assert result.marker.anchor_object_id == items[-1].id
    leftover = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(purpose="review")
    )
    assert leftover.items == []
    assert leftover.total_count == 0


def test_char_bound_keeps_cursor_metadata(db_session: Session, marker_user: UUID, monkeypatch) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "A", created_at=t0, user_id=marker_user)
    for i in range(8):
        _email(
            db_session,
            f"N{i}",
            created_at=t0 + timedelta(minutes=i + 1),
            user_id=marker_user,
            body="word " * 400,
        )
    _marker(db_session, marker_user).set_marker(anchor.id)
    db_session.flush()
    raw = (
        _tools(db_session, marker_user)
        .list_inbox_since_review_marker(ListInboxSinceReviewMarkerInput(limit=8, purpose="review"))
        .model_dump(mode="json")
    )
    monkeypatch.setattr("app.assistant.tool_output.MAX_ASSISTANT_TOOL_OUTPUT_CHARS", 1800)
    payload = serialize_tool_output_for_assistant("list_inbox_since_review_marker", raw).model_visible_payload
    assert payload.get("total_count") == 8
    assert payload.get("snapshot_top_object_id")
    assert payload.get("has_more") is True
    assert payload.get("next_cursor")
    assert len(payload.get("items") or []) < 8


def test_char_bound_model_view_does_not_drop_verified_receipt(
    interactive_session, marker_user: UUID, monkeypatch
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    newer = [
        _email(
            session,
            f"N{i}",
            created_at=t0 + timedelta(minutes=i + 1),
            user_id=marker_user,
            body="word " * 400,
        )
        for i in range(8)
    ]
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()
    monkeypatch.setattr("app.assistant.tool_output.MAX_ASSISTANT_TOOL_OUTPUT_CHARS", 1800)
    provider = _PagingReviewProvider(purpose="inspect", follow=True)
    result = AssistantService(marker_user, provider).send_message(
        "Перечисли все новые сообщения.",
        [],
    )
    assert result.inbox_review_receipt is not None
    assert result.inbox_review_receipt.snapshot_top_object_id == newer[-1].id
    assert result.inbox_review_receipt.total_count == 8


def test_progress_inspect_never_completes() -> None:
    progress = InboxReviewTurnProgress()
    progress.observe(
        arguments={"purpose": "inspect"},
        payload={
            "marker_present": True,
            "marker_not_set": False,
            "purpose": "inspect",
            "anchor_object_id": str(uuid.uuid4()),
            "anchor_feed_at": "2026-09-14T12:00:00Z",
            "snapshot_top_object_id": str(uuid.uuid4()),
            "snapshot_top_feed_at": "2026-09-14T13:00:00Z",
            "total_count": 1,
            "has_more": False,
            "items": [],
        },
    )
    assert progress.verified_receipt() is None
