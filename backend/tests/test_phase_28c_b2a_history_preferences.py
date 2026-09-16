"""PHASE 28C-B2-A — per-user history depth preference foundation."""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import (
    MAX_SOURCE_SYNC_HISTORY_DAYS,
    MIN_SOURCE_SYNC_HISTORY_DAYS,
    settings,
)
from app.db.engine import engine
from app.db.models import User, UserSourcePreference
from app.services.source_sync_preference_service import deployment_default_history_days
from app.services.source_sync_scheduler import SourceSyncScheduler
from app.source_sync.constants import (
    SOURCE_GMAIL,
    SOURCE_GOOGLE_CALENDAR,
    SOURCE_MATTERMOST,
    SOURCE_YANDEX_CALENDAR,
    SOURCE_YANDEX_MAIL,
    SUPPORTED_SOURCE_KEYS,
)
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.conftest import AuthTestClient


@pytest.fixture(autouse=True)
def cleanup_user_source_preferences() -> None:
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    session.execute(delete(UserSourcePreference))
    trans.commit()
    conn.close()
    yield


def test_defaults_no_row_match_deployment_history_days(
    auth_client: AuthTestClient,
) -> None:
    response = auth_client.get("/me/source-preferences")
    assert response.status_code == 200
    preferences = response.json()["preferences"]
    expected = {
        SOURCE_GMAIL: settings.gmail_sync_days,
        SOURCE_GOOGLE_CALENDAR: settings.calendar_sync_days_back,
        SOURCE_YANDEX_MAIL: settings.yandex_mail_sync_days,
        SOURCE_YANDEX_CALENDAR: settings.calendar_sync_days_back,
        SOURCE_MATTERMOST: settings.mattermost_sync_days,
    }
    for source, days in expected.items():
        item = next(pref for pref in preferences if pref["source"] == source)
        assert item["history_days"] == days
        assert item["default_history_days"] == days


def test_get_all_sources_include_history_bounds(
    auth_client: AuthTestClient,
) -> None:
    response = auth_client.get("/me/source-preferences")
    assert response.status_code == 200
    for item in response.json()["preferences"]:
        assert item["min_history_days"] == settings.source_sync_user_min_history_days
        assert item["max_history_days"] == settings.source_sync_user_max_history_days
        assert "history_days" in item
        assert "default_history_days" in item


def test_patch_history_days_stores_and_returns(auth_client: AuthTestClient) -> None:
    response = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"history_days": 45},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["history_days"] == 45


def test_patch_clear_history_days_returns_deployment_default(
    auth_client: AuthTestClient,
    db_session,
) -> None:
    set_resp = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"history_days": 45},
    )
    assert set_resp.status_code == 200

    clear_resp = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"history_days": None},
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["history_days"] == settings.gmail_sync_days
    pref_count = db_session.scalar(
        select(func.count()).select_from(UserSourcePreference)
    )
    assert pref_count == 0


def test_empty_patch_returns_422(auth_client: AuthTestClient) -> None:
    response = auth_client.patch("/me/source-preferences/gmail", json={})
    assert response.status_code == 422


def test_history_bounds_min_max_accepted(
    auth_client: AuthTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.source_sync_user_min_history_days", 1
    )
    monkeypatch.setattr(
        "app.core.config.settings.source_sync_user_max_history_days", 90
    )
    min_resp = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"history_days": 1},
    )
    max_resp = auth_client.patch(
        "/me/source-preferences/mattermost",
        json={"history_days": 90},
    )
    assert min_resp.status_code == 200
    assert max_resp.status_code == 200


def test_history_bounds_below_min_rejected(
    auth_client: AuthTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.source_sync_user_min_history_days", 1
    )
    response = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"history_days": 0},
    )
    assert response.status_code == 422


def test_history_bounds_above_max_rejected(
    auth_client: AuthTestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.source_sync_user_max_history_days", 90
    )
    response = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"history_days": 91},
    )
    assert response.status_code == 422


def test_deployment_narrowing_clamps_effective_without_corrupting_stored_row(
    auth_client: AuthTestClient,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.source_sync_user_max_history_days", 90
    )
    set_resp = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"history_days": 90},
    )
    assert set_resp.status_code == 200

    monkeypatch.setattr(
        "app.core.config.settings.source_sync_user_max_history_days", 30
    )
    get_resp = auth_client.get("/me/source-preferences")
    gmail = next(
        item for item in get_resp.json()["preferences"] if item["source"] == SOURCE_GMAIL
    )
    assert gmail["history_days"] == 30
    assert gmail["max_history_days"] == 30

    row = db_session.get(UserSourcePreference, (BOOTSTRAP_USER_ID, SOURCE_GMAIL))
    assert row is not None
    assert row.history_days == 90


def test_history_patch_isolation_between_users(
    auth_client: AuthTestClient,
    db_session,
    issue_bearer,
) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()
    user_b_client = AuthTestClient(
        auth_client._client,
        {"Authorization": f"Bearer {issue_bearer(user_b_id)}"},
    )

    patch_a = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"history_days": 45},
    )
    assert patch_a.status_code == 200

    get_b = user_b_client.get("/me/source-preferences")
    gmail_b = next(
        item for item in get_b.json()["preferences"] if item["source"] == SOURCE_GMAIL
    )
    assert gmail_b["history_days"] == settings.gmail_sync_days


def test_history_only_patch_preserves_enabled_and_cadence(
    auth_client: AuthTestClient,
) -> None:
    setup = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"enabled": False, "sync_interval_seconds": 900},
    )
    assert setup.status_code == 200

    history_patch = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"history_days": 45},
    )
    assert history_patch.status_code == 200
    body = history_patch.json()
    assert body["enabled"] is False
    assert body["sync_interval_seconds"] == 900
    assert body["history_days"] == 45


def test_enabled_only_patch_preserves_history_override(
    auth_client: AuthTestClient,
) -> None:
    setup = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"history_days": 45},
    )
    assert setup.status_code == 200

    enabled_patch = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"enabled": False},
    )
    assert enabled_patch.status_code == 200
    body = enabled_patch.json()
    assert body["enabled"] is False
    assert body["history_days"] == 45


def test_row_deleted_when_all_overrides_cleared(
    auth_client: AuthTestClient,
    db_session,
) -> None:
    auth_client.patch(
        "/me/source-preferences/gmail",
        json={"history_days": 45},
    )
    clear_resp = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"history_days": None},
    )
    assert clear_resp.status_code == 200
    pref_count = db_session.scalar(
        select(func.count()).select_from(UserSourcePreference)
    )
    assert pref_count == 0


def test_row_retained_when_history_remains_after_clearing_enabled(
    auth_client: AuthTestClient,
    db_session,
) -> None:
    auth_client.patch(
        "/me/source-preferences/gmail",
        json={"enabled": False, "history_days": 45},
    )
    clear_enabled = auth_client.patch(
        "/me/source-preferences/gmail",
        json={"enabled": None},
    )
    assert clear_enabled.status_code == 200
    assert clear_enabled.json()["history_days"] == 45

    row = db_session.get(UserSourcePreference, (BOOTSTRAP_USER_ID, SOURCE_GMAIL))
    assert row is not None
    assert row.history_days == 45
    assert row.enabled is None


def test_history_patch_does_not_invoke_scheduler_reconcile(
    auth_client: AuthTestClient,
) -> None:
    with patch.object(
        SourceSyncScheduler,
        "reconcile_user_source",
    ) as reconcile_mock:
        response = auth_client.patch(
            "/me/source-preferences/gmail",
            json={"history_days": 45},
        )
    assert response.status_code == 200
    reconcile_mock.assert_not_called()


def test_no_explicit_intake_history_keys(auth_client: AuthTestClient) -> None:
    for source in ("google_drive", "yandex_disk", "local"):
        response = auth_client.patch(
            f"/me/source-preferences/{source}",
            json={"history_days": 30},
        )
        assert response.status_code == 404

    get_resp = auth_client.get("/me/source-preferences")
    sources = {item["source"] for item in get_resp.json()["preferences"]}
    assert sources == set(SUPPORTED_SOURCE_KEYS)


def test_deployment_default_history_days_mapping() -> None:
    assert deployment_default_history_days(SOURCE_GMAIL) == settings.gmail_sync_days
    assert (
        deployment_default_history_days(SOURCE_GOOGLE_CALENDAR)
        == settings.calendar_sync_days_back
    )
    assert (
        deployment_default_history_days(SOURCE_YANDEX_MAIL)
        == settings.yandex_mail_sync_days
    )
    assert (
        deployment_default_history_days(SOURCE_YANDEX_CALENDAR)
        == settings.calendar_sync_days_back
    )
    assert (
        deployment_default_history_days(SOURCE_MATTERMOST)
        == settings.mattermost_sync_days
    )


def test_config_min_history_at_least_application_minimum() -> None:
    assert settings.source_sync_user_min_history_days >= MIN_SOURCE_SYNC_HISTORY_DAYS


def test_config_max_history_at_least_min_history() -> None:
    assert (
        settings.source_sync_user_max_history_days
        >= settings.source_sync_user_min_history_days
    )


def test_config_max_history_never_exceeds_application_max() -> None:
    assert (
        settings.source_sync_user_max_history_days <= MAX_SOURCE_SYNC_HISTORY_DAYS
    )


def test_config_rejects_max_history_above_application_cap() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(source_sync_user_max_history_days=91)
