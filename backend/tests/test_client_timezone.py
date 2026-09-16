from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.api.schemas import ObjectCreate
from app.core.client_timezone import (
    clear_request_timezone,
    resolve_client_timezone,
    set_request_timezone,
)
from app.services.domain_tool_service import DomainToolService
from app.services.errors import ValidationError
from app.services.graph_service import GraphService
from app.services.secretary_service import normalize_reference_datetime
from app.services.today_service import TodayService
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import FakeEmbeddingService


def test_invalid_timezone_returns_validation_error() -> None:
    with pytest.raises(ValidationError):
        resolve_client_timezone("Not/AZone")


def test_cross_midnight_due_at_europe_moscow() -> None:
    due_at = datetime(2026, 8, 30, 21, 59, 0, tzinfo=UTC)
    tz = "Europe/Moscow"
    reference = normalize_reference_datetime(
        datetime(2026, 8, 31, 10, 0, 0, tzinfo=ZoneInfo(tz)),
        tz,
    )
    local_due = due_at.astimezone(ZoneInfo(tz))
    assert local_due.strftime("%d.%m.%Y %H:%M") == "31.08.2026 00:59"
    assert local_due.date() == reference.date()


def test_cross_midnight_due_at_europe_amsterdam_previous_evening() -> None:
    due_at = datetime(2026, 8, 30, 21, 59, 0, tzinfo=UTC)
    tz = "Europe/Amsterdam"
    reference = normalize_reference_datetime(
        datetime(2026, 8, 31, 10, 0, 0, tzinfo=ZoneInfo(tz)),
        tz,
    )
    local_due = due_at.astimezone(ZoneInfo(tz))
    assert local_due.date() < reference.date()


def test_cross_midnight_due_at_america_new_york_previous_day() -> None:
    due_at = datetime(2026, 8, 30, 21, 59, 0, tzinfo=UTC)
    tz = "America/New_York"
    reference = normalize_reference_datetime(
        datetime(2026, 8, 31, 12, 0, 0, tzinfo=ZoneInfo(tz)),
        tz,
    )
    local_due = due_at.astimezone(ZoneInfo(tz))
    assert local_due.date() < reference.date()


def test_get_today_uses_request_timezone(db_session) -> None:
    set_request_timezone("Europe/Moscow")
    try:
        tools = DomainToolService(
            db_session,
            BOOTSTRAP_USER_ID,
            FakeEmbeddingService(),
            client_timezone="Europe/Moscow",
        )
        result = tools.get_today()
        assert result.timezone == "Europe/Moscow"
        assert result.datetime.tzinfo == ZoneInfo("Europe/Moscow")
    finally:
        clear_request_timezone()


def test_today_service_uses_client_timezone(db_session) -> None:
    graph = GraphService(db_session, BOOTSTRAP_USER_ID, None)
    due_at = datetime(2026, 8, 30, 21, 59, 0, tzinfo=UTC)
    graph.create_object(
        ObjectCreate(
            kind="task",
            title="TZ task",
            origin="user",
            state="confirmed",
            status="open",
            due_at=due_at,
        )
    )
    snapshot = TodayService(db_session, BOOTSTRAP_USER_ID).snapshot(
        reference_at=datetime(2026, 8, 31, 10, 0, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        timezone="Europe/Moscow",
    )
    assert snapshot["timezone"] == "Europe/Moscow"
    assert any(obj.title == "TZ task" for obj in snapshot["tasks"])
