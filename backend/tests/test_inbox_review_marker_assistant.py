"""Voice Assistant A R2 — Inbox review-marker tools for typed/voice Assistant."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.assistant.session as assistant_session_module
from app.api.schemas import ObjectCreate
from app.assistant.constants import MAX_ASSISTANT_LIST_RESULTS
from app.assistant.reference_ids import (
    collect_object_ids_from_bounded_tool,
    collect_seen_object_ids_from_bounded_tool,
)
from app.assistant.tool_output import serialize_tool_output_for_assistant
from app.assistant.tool_runner import BoundAssistantToolRunner, PerTurnToolBudget
from app.db.models import (
    ExternalActionAttempt,
    InboxReviewMarker,
    Job,
    Object,
    PendingActionPlan,
    User,
)
from app.llm.openai_assistant_provider import SYSTEM_INSTRUCTIONS
from app.mcp.gateway_runner import execute_mcp_tool
from app.proactive.constants import PROACTIVE_READ_TOOL_NAMES
from app.services.domain_tool_service import DomainToolService
from app.services.graph_service import GraphService
from app.services.inbox_review_marker import (
    InboxReviewMarkerService,
    feed_tuple_is_newer,
)
from app.services.recent_source_service import RecentSourceService, inbox_feed_at
from app.tools.assistant_contracts import ASSISTANT_FUNCTION_SCHEMAS
from app.tools.policy import ToolPermission
from app.tools.registry import TOOL_REGISTRY
from app.tools.results import ToolExecutionStatus
from app.tools.schemas import (
    ListInboxSinceReviewMarkerInput,
    SetInboxReviewMarkerInput,
    ToolError,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID


class _SessionProxy:
    """Route SessionLocal() to the test transaction without committing it."""

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
def marker_user(db_session) -> UUID:
    user_id = uuid.uuid4()
    db_session.add(User(id=user_id, display_name="review-marker-assistant"))
    db_session.flush()
    return user_id


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
    occurred_at: datetime | None = None,
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
    return _stamp(obj, created_at, occurred_at or created_at)


def _tools(session: Session, user_id: UUID = BOOTSTRAP_USER_ID) -> DomainToolService:
    return DomainToolService(session, user_id, None)


def _marker(session: Session, user_id: UUID = BOOTSTRAP_USER_ID) -> InboxReviewMarkerService:
    return InboxReviewMarkerService(session, user_id)


def _runner(
    user_id: UUID, seen: list[UUID] | None = None
) -> tuple[BoundAssistantToolRunner, PerTurnToolBudget]:
    budget = PerTurnToolBudget(initial_seen_object_ids=seen or [])
    return BoundAssistantToolRunner(budget, user_id), budget


def _pap_count(session: Session, user_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(PendingActionPlan)
            .where(PendingActionPlan.user_id == user_id)
        )
        or 0
    )


def _visible_list_payload(page) -> dict:
    raw = page.model_dump(mode="json")
    return serialize_tool_output_for_assistant(
        "list_inbox_since_review_marker", raw
    ).model_visible_payload


def test_anchor_is_excluded_from_new(db_session: Session, marker_user: UUID) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    older = _email(db_session, "older", created_at=t0 - timedelta(hours=2), user_id=marker_user)
    anchor = _email(db_session, "anchor", created_at=t0, user_id=marker_user)
    _marker(db_session, marker_user).set_marker(anchor.id)
    db_session.flush()

    page = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput()
    )
    assert page.marker_present is True
    assert page.marker_not_set is False
    assert page.anchor_object_id == anchor.id
    assert page.anchor_feed_at == inbox_feed_at(anchor)
    assert [item.object_id for item in page.items] == []
    assert older.id not in {item.object_id for item in page.items}
    assert page.has_more is False


def test_strictly_newer_items_canonical_order(db_session: Session, marker_user: UUID) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "A", created_at=t0, user_id=marker_user)
    n1 = _email(db_session, "N1", created_at=t0 + timedelta(hours=1), user_id=marker_user)
    n2 = _email(db_session, "N2", created_at=t0 + timedelta(hours=2), user_id=marker_user)
    _marker(db_session, marker_user).set_marker(anchor.id)
    db_session.flush()

    page = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput()
    )
    assert [item.object_id for item in page.items] == [n2.id, n1.id]
    assert [item.title for item in page.items] == ["N2", "N1"]
    assert anchor.id not in {item.object_id for item in page.items}
    feed = RecentSourceService(db_session, marker_user).list_page(limit=10)
    assert [obj.id for obj in feed.items[:3]] == [n2.id, n1.id, anchor.id]


def test_same_feed_timestamp_uuid_tie_break_matches_inbox(
    db_session: Session, marker_user: UUID
) -> None:
    t = datetime(2026, 9, 14, 12, tzinfo=UTC)
    low = UUID("00000000-0000-4000-8000-000000000001")
    mid = UUID("00000000-0000-4000-8000-000000000002")
    high = UUID("00000000-0000-4000-8000-000000000003")
    _email(db_session, "low", created_at=t, object_id=low, user_id=marker_user)
    _email(db_session, "mid", created_at=t, object_id=mid, user_id=marker_user)
    _email(db_session, "high", created_at=t, object_id=high, user_id=marker_user)
    db_session.flush()

    assert feed_tuple_is_newer(t, high, t, mid)
    assert feed_tuple_is_newer(t, mid, t, low)
    feed_ids = [
        obj.id
        for obj in RecentSourceService(db_session, marker_user).list_page(limit=10).items
        if obj.id in {low, mid, high}
    ]
    assert feed_ids == [high, mid, low]

    _marker(db_session, marker_user).set_marker(mid)
    page = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput()
    )
    assert [item.object_id for item in page.items] == [high]

    _marker(db_session, marker_user).set_marker(high)
    page_at_newest = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput()
    )
    assert [item.object_id for item in page_at_newest.items] == []


def test_marker_absent_is_explicit_and_does_not_dump_history(
    db_session: Session, marker_user: UUID
) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    historical = [
        _email(db_session, f"old-{i}", created_at=t0 - timedelta(days=i), user_id=marker_user)
        for i in range(5)
    ]
    db_session.flush()
    assert _marker(db_session, marker_user).get_marker() is None

    page = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput()
    )
    assert page.marker_present is False
    assert page.marker_not_set is True
    assert page.anchor_object_id is None
    assert page.anchor_feed_at is None
    assert page.items == []
    assert page.has_more is False
    assert page.message == "Inbox review marker is not set"
    assert page.items == []
    historical_ids = {item.id for item in historical}
    assert historical_ids  # historical Inbox exists but is not classified as new


def test_user_isolation_marker_and_objects(db_session: Session, marker_user: UUID) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    other_id = uuid.uuid4()
    db_session.add(User(id=other_id, display_name="foreign-review-marker"))
    db_session.flush()

    mine_anchor = _email(db_session, "mine-anchor", created_at=t0, user_id=marker_user)
    mine_new = _email(
        db_session, "mine-new", created_at=t0 + timedelta(hours=1), user_id=marker_user
    )
    foreign_new = _email(
        db_session,
        "secret-new",
        created_at=t0 + timedelta(hours=2),
        user_id=other_id,
    )
    _marker(db_session, marker_user).set_marker(mine_anchor.id)
    _marker(db_session, other_id).set_marker(foreign_new.id)
    db_session.flush()

    mine_page = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput()
    )
    assert [item.object_id for item in mine_page.items] == [mine_new.id]
    assert foreign_new.id not in {item.object_id for item in mine_page.items}
    assert mine_page.anchor_object_id == mine_anchor.id

    other_page = _tools(db_session, other_id).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput()
    )
    assert other_page.items == []
    assert other_page.anchor_object_id == foreign_new.id
    assert mine_new.id not in {item.object_id for item in other_page.items}

    with pytest.raises(ToolError, match="object not found"):
        _tools(db_session, marker_user).set_inbox_review_marker(
            SetInboxReviewMarkerInput(after_object_id=foreign_new.id)
        )
    assert _marker(db_session, marker_user).get_marker().anchor_object_id == mine_anchor.id


def test_set_marker_executes_immediately_without_pending_plan(
    interactive_session, marker_user: UUID
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    obj = _email(session, "set-now", created_at=t0, user_id=marker_user)
    before_pap = _pap_count(session, marker_user)
    runner, budget = _runner(marker_user, seen=[obj.id])

    result = runner("set_inbox_review_marker", {"after_object_id": str(obj.id)})
    assert result.success is True
    assert result.status == ToolExecutionStatus.SUCCESS
    assert result.staged_action is None
    assert budget.staged_actions == []
    assert _pap_count(session, marker_user) == before_pap
    marker = _marker(session, marker_user).get_marker()
    assert marker is not None
    assert marker.anchor_object_id == obj.id


def test_clear_marker_executes_immediately_without_pending_plan(
    interactive_session, marker_user: UUID
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    obj = _email(session, "clear-now", created_at=t0, user_id=marker_user)
    _marker(session, marker_user).set_marker(obj.id)
    session.flush()
    before_pap = _pap_count(session, marker_user)
    runner, budget = _runner(marker_user)

    result = runner("clear_inbox_review_marker", {})
    assert result.success is True
    assert result.status == ToolExecutionStatus.SUCCESS
    assert result.staged_action is None
    assert budget.staged_actions == []
    assert _pap_count(session, marker_user) == before_pap
    assert _marker(session, marker_user).get_marker() is None
    assert session.get(InboxReviewMarker, marker_user) is None


def test_set_marker_fails_closed_when_target_not_exposed(
    interactive_session, marker_user: UUID
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    n1 = _email(session, "N1", created_at=t0 + timedelta(hours=1), user_id=marker_user)
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()
    runner, _budget = _runner(marker_user)

    guessed = runner("set_inbox_review_marker", {"after_object_id": str(n1.id)})
    assert guessed.success is False
    assert guessed.status == ToolExecutionStatus.TOOL_ERROR
    assert "target object was not exposed in this Assistant turn" in guessed.error
    assert guessed.staged_action is None
    assert _marker(session, marker_user).get_marker().anchor_object_id == anchor.id

    listed = runner("list_inbox_since_review_marker", {"limit": 20})
    assert listed.success is True
    assert listed.model_visible_payload["items"][0]["object_id"] == str(n1.id)
    still_pending = runner("set_inbox_review_marker", {"after_object_id": str(n1.id)})
    assert still_pending.success is False
    assert "target object was not exposed in this Assistant turn" in still_pending.error
    assert _marker(session, marker_user).get_marker().anchor_object_id == anchor.id


def test_set_marker_succeeds_after_list_inbox_exposes_object(
    interactive_session, marker_user: UUID
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    n1 = _email(
        session, "N1", created_at=t0 + timedelta(hours=1), body="short body", user_id=marker_user
    )
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()
    runner, budget = _runner(marker_user)

    listed = runner("list_inbox_since_review_marker", {"limit": 20})
    assert listed.success is True
    assert listed.model_visible_payload["items"][0]["object_id"] == str(n1.id)
    runner.commit_model_visible_outputs()
    seen = collect_seen_object_ids_from_bounded_tool(
        "list_inbox_since_review_marker", listed.model_visible_payload
    )
    assert n1.id in seen
    assert anchor.id in seen

    result = runner("set_inbox_review_marker", {"after_object_id": str(n1.id)})
    assert result.success is True
    assert result.staged_action is None
    assert budget.staged_actions == []
    assert _marker(session, marker_user).get_marker().anchor_object_id == n1.id


def test_review_marker_references_are_new_items_not_anchor(
    db_session: Session, marker_user: UUID
) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "A", created_at=t0, user_id=marker_user)
    n1 = _email(db_session, "N1", created_at=t0 + timedelta(hours=1), user_id=marker_user)
    n2 = _email(db_session, "N2", created_at=t0 + timedelta(hours=2), user_id=marker_user)
    _marker(db_session, marker_user).set_marker(anchor.id)
    db_session.flush()

    payload = _visible_list_payload(
        _tools(db_session, marker_user).list_inbox_since_review_marker(
            ListInboxSinceReviewMarkerInput()
        )
    )
    assert payload["anchor_object_id"] == str(anchor.id)
    assert [row["object_id"] for row in payload["items"]] == [str(n2.id), str(n1.id)]

    candidates: list[UUID] = []
    collect_object_ids_from_bounded_tool(
        "list_inbox_since_review_marker", payload, candidates, []
    )
    assert candidates == [n2.id, n1.id]
    assert anchor.id not in candidates

    seen = collect_seen_object_ids_from_bounded_tool(
        "list_inbox_since_review_marker", payload
    )
    assert seen == [anchor.id, n2.id, n1.id]


def test_review_marker_zero_new_items_have_no_reference_ids(
    db_session: Session, marker_user: UUID
) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    older = _email(db_session, "older", created_at=t0 - timedelta(hours=1), user_id=marker_user)
    anchor = _email(db_session, "A", created_at=t0, user_id=marker_user)
    _marker(db_session, marker_user).set_marker(anchor.id)
    db_session.flush()

    payload = _visible_list_payload(
        _tools(db_session, marker_user).list_inbox_since_review_marker(
            ListInboxSinceReviewMarkerInput()
        )
    )
    assert payload["items"] == []
    assert payload["anchor_object_id"] == str(anchor.id)

    candidates: list[UUID] = []
    collect_object_ids_from_bounded_tool(
        "list_inbox_since_review_marker", payload, candidates, []
    )
    assert candidates == []
    assert older.id not in candidates
    assert anchor.id not in candidates

    seen = collect_seen_object_ids_from_bounded_tool(
        "list_inbox_since_review_marker", payload
    )
    assert seen == [anchor.id]


def test_set_marker_still_accepts_exposed_anchor(
    interactive_session, marker_user: UUID
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(session, "A", created_at=t0, user_id=marker_user)
    _email(session, "N1", created_at=t0 + timedelta(hours=1), user_id=marker_user)
    _marker(session, marker_user).set_marker(anchor.id)
    session.flush()
    runner, budget = _runner(marker_user)

    listed = runner("list_inbox_since_review_marker", {"limit": 20})
    assert listed.success is True
    runner.commit_model_visible_outputs()
    result = runner("set_inbox_review_marker", {"after_object_id": str(anchor.id)})
    assert result.success is True
    assert result.staged_action is None
    assert budget.staged_actions == []
    assert _marker(session, marker_user).get_marker().anchor_object_id == anchor.id


def test_non_inbox_eligible_target_rejected(interactive_session, marker_user: UUID) -> None:
    session = interactive_session
    task = GraphService(session, marker_user).create_object(
        ObjectCreate(kind="task", title="Not in inbox", origin="user")
    )
    session.flush()
    runner, _budget = _runner(marker_user, seen=[task.id])

    result = runner("set_inbox_review_marker", {"after_object_id": str(task.id)})
    assert result.success is False
    assert result.status == ToolExecutionStatus.TOOL_ERROR
    assert "object is not eligible for the inbox feed" in result.error
    assert _marker(session, marker_user).get_marker() is None


def test_marker_tools_do_not_write_provider_or_external_state(
    interactive_session, marker_user: UUID
) -> None:
    session = interactive_session
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    email = _email(session, "gmail-keep", created_at=t0, provider="gmail", user_id=marker_user)
    snapshot = (
        email.provider,
        email.external_id,
        dict(email.metadata_),
        email.canonical_uri,
        email.status,
        email.state,
    )
    before_attempts = session.scalar(select(func.count()).select_from(ExternalActionAttempt))
    before_jobs = session.scalar(select(func.count()).select_from(Job))
    runner, _budget = _runner(marker_user, seen=[email.id])

    set_result = runner("set_inbox_review_marker", {"after_object_id": str(email.id)})
    clear_result = runner("clear_inbox_review_marker", {})
    assert set_result.success and clear_result.success
    session.refresh(email)
    assert (
        email.provider,
        email.external_id,
        dict(email.metadata_),
        email.canonical_uri,
        email.status,
        email.state,
    ) == snapshot
    assert session.scalar(select(func.count()).select_from(ExternalActionAttempt)) == before_attempts
    assert session.scalar(select(func.count()).select_from(Job)) == before_jobs

    set_src = inspect.getsource(DomainToolService.set_inbox_review_marker)
    clear_src = inspect.getsource(DomainToolService.clear_inbox_review_marker)
    list_src = inspect.getsource(DomainToolService.list_inbox_since_review_marker)
    for src in (set_src, clear_src, list_src):
        assert "/inbox/review-marker" not in src
        assert "http" not in src.lower()


def test_bounded_tool_output_and_has_more(db_session: Session, marker_user: UUID) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    anchor = _email(db_session, "anchor", created_at=t0, user_id=marker_user)
    newer = [
        _email(
            db_session,
            f"N{i:02d}",
            created_at=t0 + timedelta(minutes=i + 1),
            body="word " * 80,
            user_id=marker_user,
        )
        for i in range(25)
    ]
    _marker(db_session, marker_user).set_marker(anchor.id)
    db_session.flush()

    domain_page = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(limit=2)
    )
    assert len(domain_page.items) == 2
    assert domain_page.has_more is True
    assert [item.object_id for item in domain_page.items] == [newer[-1].id, newer[-2].id]
    assert all(item.excerpt is not None and "word" in item.excerpt for item in domain_page.items)
    assert all(
        item.excerpt is None or len(item.excerpt) <= 161 for item in domain_page.items
    )
    raw = _tools(db_session, marker_user).list_inbox_since_review_marker(
        ListInboxSinceReviewMarkerInput(limit=50)
    ).model_dump(mode="json")
    assert "body" not in raw["items"][0]
    assert len(raw["items"]) == 25
    model_out = serialize_tool_output_for_assistant("list_inbox_since_review_marker", raw)
    payload = model_out.model_visible_payload
    assert len(payload["items"]) == MAX_ASSISTANT_LIST_RESULTS
    assert payload["has_more"] is True
    assert payload["total_count"] == 25
    assert payload["returned_count"] == MAX_ASSISTANT_LIST_RESULTS
    assert payload["remaining_count"] == 5
    assert payload["next_cursor"]
    assert payload["snapshot_top_object_id"] == str(newer[-1].id)
    visible_ids = [UUID(str(row["object_id"])) for row in payload["items"]]
    assert newer[-1].id in visible_ids
    assert newer[0].id not in visible_ids
    seen = collect_seen_object_ids_from_bounded_tool("list_inbox_since_review_marker", payload)
    assert UUID(str(payload["anchor_object_id"])) in seen
    assert set(visible_ids).issubset(set(seen))
    candidates: list[UUID] = []
    collect_object_ids_from_bounded_tool(
        "list_inbox_since_review_marker", payload, candidates, []
    )
    assert newer[-1].id in candidates
    assert UUID(str(payload["anchor_object_id"])) not in candidates
    assert candidates == visible_ids


def test_mcp_review_marker_annotate_fail_closed(db_session, patched_mcp_tool_session) -> None:
    t0 = datetime(2026, 9, 14, 12, tzinfo=UTC)
    obj = _email(db_session, "mcp-anchor", created_at=t0)
    _marker(db_session).clear_marker()
    listed = execute_mcp_tool("list_inbox_since_review_marker", {"limit": 20})
    assert listed.marker_not_set is True
    assert listed.items == []

    with pytest.raises(ToolError, match="requires approval"):
        execute_mcp_tool("set_inbox_review_marker", {"after_object_id": str(obj.id)})
    assert _marker(db_session).get_marker() is None

    _marker(db_session).set_marker(obj.id)
    db_session.flush()
    with pytest.raises(ToolError, match="requires approval"):
        execute_mcp_tool("clear_inbox_review_marker", {})
    assert _marker(db_session).get_marker() is not None


def test_review_marker_tools_not_on_proactive_allowlist() -> None:
    for name in (
        "list_inbox_since_review_marker",
        "list_conversation_members",
        "set_inbox_review_marker",
        "clear_inbox_review_marker",
    ):
        assert name not in PROACTIVE_READ_TOOL_NAMES
    assert TOOL_REGISTRY["list_inbox_since_review_marker"].permission == ToolPermission.READ
    assert TOOL_REGISTRY["set_inbox_review_marker"].permission == ToolPermission.ANNOTATE
    assert TOOL_REGISTRY["clear_inbox_review_marker"].permission == ToolPermission.ANNOTATE
    assert TOOL_REGISTRY["set_inbox_review_marker"].prepare_method is None
    assert TOOL_REGISTRY["clear_inbox_review_marker"].prepare_method is None
    assert TOOL_REGISTRY["clear_inbox_review_marker"].input_model is None


def test_prompt_routes_whats_new_to_read_not_auto_mutate() -> None:
    text = SYSTEM_INSTRUCTIONS
    for phrase in (
        "что нового?",
        "что нового во входящих?",
        "что пришло с прошлого раза?",
        "какие новые письма?",
        "перечисли то, что выше маркера просмотра",
        "перечисли все новые сообщения",
        "назови все новые сообщения",
        "прочти все новые сообщения",
        "что нового — перечисли всё",
        "сколько новых сообщений?",
        "отметь это просмотренным",
        "перенеси просмотрено досюда до этого письма",
        "считай всё текущее просмотренным",
        "убери маркер просмотра",
    ):
        assert phrase in text
    assert "list_inbox_since_review_marker" in text
    assert "set_inbox_review_marker" in text
    assert "clear_inbox_review_marker" in text
    assert "Do not guess a time window" in text
    assert "Do not call set_inbox_review_marker or clear_inbox_review_marker merely because" in text
    assert "fetched objects, summarized them, generated text, or requested speech" in text
    assert "purpose=review" in text
    assert "total_count" in text
    assert "next_cursor" in text
    assert "without a Pending Action Plan" in text
    assert "not Gmail/Yandex/Mattermost/Telegram/Teams provider read/unread" in text

    read_desc = ASSISTANT_FUNCTION_SCHEMAS["list_inbox_since_review_marker"]["description"]
    set_desc = ASSISTANT_FUNCTION_SCHEMAS["set_inbox_review_marker"]["description"]
    clear_desc = ASSISTANT_FUNCTION_SCHEMAS["clear_inbox_review_marker"]["description"]
    assert "что нового во входящих" in read_desc
    assert "Inspect/count/listing/summarizing does not move the marker" in read_desc
    assert "purpose=review" in read_desc
    assert "next_cursor" in read_desc
    assert "oldest-to-newest" in read_desc
    assert "oldest-to-newest" in text
    assert "GLOBAL Secretary Inbox review frontier" in set_desc
    assert "without a Pending Action Plan" in set_desc
    assert "provider mail read-state" in set_desc
    assert "without a Pending Action Plan" in clear_desc
    assert "убери маркер просмотра" in clear_desc
