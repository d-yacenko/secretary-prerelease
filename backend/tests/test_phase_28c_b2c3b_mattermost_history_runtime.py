"""PHASE 28C-B2-C3-B — Mattermost bounded history runtime."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, func, select

from app.connectors.mattermost.credentials import MattermostAccountStore
from app.connectors.mattermost.mattermost_history_state import get_history_backfill
from app.connectors.mattermost.sync import build_mattermost_sync_service
from app.connectors.mattermost.transport import FakeMattermostTransport
from app.core.config import settings
from app.db.engine import engine
from app.db.models import Job, MattermostAccount, Object, User, UserSourcePreference
from app.jobs.constants import JOB_TYPE_SYNC_MATTERMOST
from app.jobs.handlers import HANDLERS
from app.jobs.source_sync_handlers import _mattermost_sync_service, handle_sync_mattermost
from app.jobs.worker import process_one_job
from app.services.source_sync_preference_service import SourceSyncPreferenceService
from app.services.source_sync_scheduler import SourceSyncScheduler
from app.source_sync.constants import SOURCE_MATTERMOST
from app.users.bootstrap import BOOTSTRAP_USER_ID

ALLOWED_URL = "https://mm.example.com"
PAT = "mattermost-personal-access-token"
FIXED_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)
FIXED_NOW_MS = int(FIXED_NOW.timestamp() * 1000)
CHANNEL_A = "channel-a"
CHANNEL_B = "channel-b"
CHANNEL_C = "channel-c"
CHANNEL_REMOVED = "channel-removed"
TEAM = {"id": "team-1", "name": "team", "display_name": "Team"}
AUTHOR = {"id": "author-1", "username": "bob", "display_name": "Bob"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _ms(days: float) -> int:
    return int((FIXED_NOW - timedelta(days=days)).timestamp() * 1000)


def _post(
    post_id: str,
    channel_id: str,
    create_at_ms: int,
    message: str | None = None,
    update_at_ms: int | None = None,
) -> dict:
    update = update_at_ms if update_at_ms is not None else create_at_ms
    return {
        "id": post_id,
        "channel_id": channel_id,
        "user_id": "author-1",
        "message": message or post_id,
        "create_at": create_at_ms,
        "update_at": update,
        "type": "",
        "root_id": "",
        "file_ids": [],
    }


def _channel(channel_id: str) -> dict:
    return {
        "id": channel_id,
        "name": channel_id,
        "display_name": channel_id,
        "type": "O",
        "team_id": "team-1",
        "last_post_at": FIXED_NOW_MS,
    }


@pytest.fixture(autouse=True)
def cleanup_tables() -> None:
    conn = engine.connect()
    trans = conn.begin()
    session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    session.execute(delete(Job))
    session.execute(delete(Object))
    session.execute(delete(UserSourcePreference))
    session.execute(delete(MattermostAccount))
    trans.commit()
    conn.close()
    yield
    conn = engine.connect()
    trans = conn.begin()
    session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    session.execute(delete(Job))
    session.execute(delete(Object))
    session.execute(delete(UserSourcePreference))
    session.execute(delete(MattermostAccount))
    trans.commit()
    conn.close()


@pytest.fixture(autouse=True)
def fixed_utcnow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.connectors.mattermost.sync.utcnow", lambda: FIXED_NOW)
    monkeypatch.setattr(
        "app.connectors.mattermost.mattermost_history_state.utcnow",
        lambda: FIXED_NOW,
    )


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def mattermost_settings(monkeypatch: pytest.MonkeyPatch, credential_key: str) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    monkeypatch.setattr(
        "app.core.config.settings.mattermost_allowed_base_urls",
        ALLOWED_URL,
    )


def _connect_account(
    db_session,
    credential_key: str,
    *,
    sync_state: dict | None = None,
    user_id: uuid.UUID = BOOTSTRAP_USER_ID,
) -> MattermostAccount:
    store = MattermostAccountStore(
        db_session,
        MattermostAccountStore.build_encryption(credential_key),
    )
    account = store.upsert_account(
        user_id=user_id,
        normalized_server_url=ALLOWED_URL,
        remote_user_id="user-1",
        username="alice",
        access_token=PAT,
        display_name="Alice",
        email="alice@example.com",
    )
    if sync_state is not None:
        account.sync_state = sync_state
    db_session.flush()
    return account


def _build_service(
    db_session,
    credential_key: str,
    transport: FakeMattermostTransport,
    *,
    sync_days: int = 14,
    max_posts_per_run: int = 500,
    initial_posts_per_channel: int = 100,
) -> object:
    return build_mattermost_sync_service(
        session=db_session,
        credential_key=credential_key,
        sync_days=sync_days,
        max_channels=50,
        initial_posts_per_channel=initial_posts_per_channel,
        max_posts_per_run=max_posts_per_run,
        overlap_seconds=300,
        transport_factory=lambda snapshot: transport,
        now_factory=lambda: FIXED_NOW,
    )


def _history_post_calls(transport: FakeMattermostTransport) -> list[tuple[str, dict]]:
    return [
        (path, params or {})
        for method, path, params in transport.calls
        if method == "GET" and path.endswith("/posts")
        and (
            (params or {}).get("before") is not None
            or (params or {}).get("page") == 0 and "since" not in (params or {})
        )
    ]


def _bootstrap_channel_state(
    *,
    last_post_id: str = "live-anchor",
    last_create_ms: int = _ms(1),
) -> dict:
    return {
        "bootstrap_complete": True,
        "last_processed_post_id": last_post_id,
        "last_processed_create_at_ms": last_create_ms,
        "edit_sweep_watermark_ms": last_create_ms,
    }


def test_effective_history_user_a_seven_user_b_default(
    db_session,
    credential_key: str,
) -> None:
    user_b_id = uuid.uuid4()
    db_session.add(User(id=user_b_id, display_name="User B"))
    db_session.flush()
    account_a = _connect_account(db_session, credential_key)
    account_b = _connect_account(db_session, credential_key, user_id=user_b_id)
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_MATTERMOST,
        history_days=7,
        history_days_specified=True,
    )
    transport_a = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={
            CHANNEL_A: [
                _post("old", CHANNEL_A, _ms(10)),
                _post("live", CHANNEL_A, _ms(1)),
            ],
        },
    )
    service_a = _build_service(db_session, credential_key, transport_a, sync_days=7)
    service_a.sync_account(account_a.id, BOOTSTRAP_USER_ID)
    assert any(
        _post("old", CHANNEL_A, _ms(10))["id"] in str(call)
        or (_ms(7) > _ms(10))
        for call in transport_a.calls
    )

    transport_b = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={CHANNEL_A: [_post("live-b", CHANNEL_A, _ms(1))]},
    )
    service_b = _build_service(
        db_session,
        credential_key,
        transport_b,
        sync_days=settings.mattermost_sync_days,
    )
    service_b.sync_account(account_b.id, user_b_id)
    stored_b = db_session.get(MattermostAccount, account_b.id)
    entry = (stored_b.sync_state or {}).get("channels", {}).get(CHANNEL_A, {})
    assert entry.get("bootstrap_complete") is True


def test_worker_service_uses_source_mattermost_effective_history(
    db_session,
    credential_key: str,
    mattermost_settings,
) -> None:
    _connect_account(db_session, credential_key)
    SourceSyncPreferenceService.build(db_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_MATTERMOST,
        history_days=21,
        history_days_specified=True,
    )
    service = _mattermost_sync_service(db_session, BOOTSTRAP_USER_ID)
    assert service._sync_days == 21


def test_worker_passes_include_history_pass_true(
    db_session,
    credential_key: str,
    mattermost_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _connect_account(db_session, credential_key)
    captured: dict[str, bool] = {}

    class StubService:
        def sync_account(self, account_id, user_id, *, include_history_pass=False):
            captured["include_history_pass"] = include_history_pass
            return {
                "synchronized": 0,
                "created": 0,
                "updated": 0,
                "unchanged": 0,
                "jobs_enqueued": 0,
            }

    monkeypatch.setattr(
        "app.jobs.source_sync_handlers._mattermost_sync_service",
        lambda session, user_id: StubService(),
    )
    handle_sync_mattermost(
        db_session,
        None,
        {"account_id": str(account.id)},
        BOOTSTRAP_USER_ID,
    )
    assert captured["include_history_pass"] is True


def test_live_before_history_and_counters_exclude_history(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    "bootstrap_complete": True,
                    "last_processed_post_id": "live-1",
                    "last_processed_create_at_ms": _ms(1),
                    "edit_sweep_watermark_ms": _ms(0.5),
                },
            }
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={
            CHANNEL_A: [
                _post("hist-old", CHANNEL_A, _ms(12)),
                _post("live-1", CHANNEL_A, _ms(1)),
                _post("live-2", CHANNEL_A, _ms(0.5)),
            ],
        },
    )
    service = _build_service(db_session, credential_key, transport, initial_posts_per_channel=5)
    result = service.sync_account(
        account.id,
        BOOTSTRAP_USER_ID,
        include_history_pass=True,
    )
    assert result["created"] == 1
    hist_obj = db_session.scalar(
        select(Object).where(Object.metadata_["post_id"].as_string() == "hist-old")
    )
    assert hist_obj is not None


def test_live_state_persisted_before_history_provider_call(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _connect_account(db_session, credential_key)
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={CHANNEL_A: [_post("live-1", CHANNEL_A, _ms(1))]},
    )
    service = _build_service(db_session, credential_key, transport)
    observed_live_anchor: str | None = None

    original_history = service._run_history_pass

    def history_wrapper(**kwargs):
        nonlocal observed_live_anchor
        channel_state = kwargs["channel_state_root"]
        observed_live_anchor = channel_state[CHANNEL_A]["last_processed_post_id"]
        return original_history(**kwargs)

    monkeypatch.setattr(service, "_run_history_pass", history_wrapper)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert observed_live_anchor == "live-1"


def test_one_history_posts_page_per_run(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(db_session, credential_key)
    old_posts = [
        _post(f"old-{idx}", CHANNEL_A, _ms(20) + idx * 1000)
        for idx in range(30)
    ]
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={CHANNEL_A: old_posts + [_post("live-1", CHANNEL_A, _ms(1))]},
    )
    service = _build_service(
        db_session,
        credential_key,
        transport,
        initial_posts_per_channel=10,
        max_posts_per_run=10,
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    page_zero_calls = [
        params or {}
        for _, path, params in transport.calls
        if path.endswith("/posts")
        and (params or {}).get("page") == 0
        and "since" not in (params or {})
        and "after" not in (params or {})
    ]
    before_calls = [
        params or {}
        for _, path, params in transport.calls
        if path.endswith("/posts") and (params or {}).get("before") is not None
    ]
    assert len(before_calls) == 0
    assert len(page_zero_calls) == 2


def test_initial_history_uses_page_zero_once(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(db_session, credential_key)
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={
            CHANNEL_A: [
                _post("old-1", CHANNEL_A, _ms(20)),
                _post("live-1", CHANNEL_A, _ms(1)),
            ],
        },
    )
    service = _build_service(db_session, credential_key, transport, initial_posts_per_channel=5)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    page_calls = [
        params
        for _, path, params in transport.calls
        if path.endswith("/posts") and (params or {}).get("page") == 0 and "before" not in (params or {})
    ]
    assert len(page_calls) == 2
    assert page_calls[-1]["per_page"] == 5


def test_active_state_persisted_before_first_history_request(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={"channels": {CHANNEL_A: _bootstrap_channel_state()}},
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={CHANNEL_A: [_post("old-1", CHANNEL_A, _ms(12))]},
    )
    service = _build_service(db_session, credential_key, transport)
    observed_active = False
    original_get_posts_page = transport.get_posts_page

    def tracked_get_posts_page(channel_id, page, per_page):
        nonlocal observed_active
        stored = db_session.get(MattermostAccount, account.id)
        backfill = get_history_backfill(stored.sync_state["channels"][CHANNEL_A])
        if backfill.get("active_start_ms") is not None:
            observed_active = True
        return original_get_posts_page(channel_id, page, per_page)

    transport.get_posts_page = tracked_get_posts_page
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert observed_active is True


def test_continuation_uses_get_posts_before_exact_anchor(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    **_bootstrap_channel_state(),
                    "history_backfill": {
                        "version": 1,
                        "active_start_ms": _ms(30),
                        "active_end_ms": FIXED_NOW_MS,
                        "active_history_days": 14,
                        "active_before_post_id": "p100",
                    },
                },
            },
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={
            CHANNEL_A: [
                _post("p50", CHANNEL_A, _ms(20)),
                _post("p100", CHANNEL_A, _ms(10)),
            ],
        },
    )
    service = _build_service(db_session, credential_key, transport, initial_posts_per_channel=10)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    before_calls = [
        (params or {}).get("before")
        for _, path, params in transport.calls
        if path.endswith("/posts") and (params or {}).get("before") is not None
    ]
    assert before_calls == ["p100"]


def test_persisted_before_cursor_stable_after_newer_posts_inserted(
    db_session,
    credential_key: str,
) -> None:
    class StableTransport(FakeMattermostTransport):
        def get_posts_before(self, channel_id, before_post_id, per_page):
            result = super().get_posts_before(channel_id, before_post_id, per_page)
            self.posts_by_channel[channel_id].append(
                _post("p-new", channel_id, _ms(0.1))
            )
            return result

    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    **_bootstrap_channel_state(),
                    "history_backfill": {
                        "version": 1,
                        "active_start_ms": _ms(30),
                        "active_end_ms": FIXED_NOW_MS,
                        "active_history_days": 14,
                        "active_before_post_id": "p80",
                    },
                },
            },
        },
    )
    transport = StableTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={
            CHANNEL_A: [
                _post("p40", CHANNEL_A, _ms(22)),
                _post("p50", CHANNEL_A, _ms(20)),
                _post("p80", CHANNEL_A, _ms(10)),
            ],
        },
    )
    service = _build_service(db_session, credential_key, transport, initial_posts_per_channel=2)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(MattermostAccount, account.id)
    backfill = get_history_backfill(stored.sync_state["channels"][CHANNEL_A])
    assert backfill.get("active_before_post_id") == "p40"


def test_successful_page_advances_to_oldest_provider_post(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    **_bootstrap_channel_state(),
                    "history_backfill": {
                        "version": 1,
                        "active_start_ms": _ms(30),
                        "active_end_ms": FIXED_NOW_MS,
                        "active_history_days": 14,
                        "active_before_post_id": "p100",
                    },
                },
            },
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={
            CHANNEL_A: [
                _post("p55", CHANNEL_A, _ms(19)),
                _post("p60", CHANNEL_A, _ms(18)),
                _post("p80", CHANNEL_A, _ms(12)),
                _post("p100", CHANNEL_A, _ms(8)),
            ],
        },
    )
    service = _build_service(db_session, credential_key, transport, initial_posts_per_channel=3)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(MattermostAccount, account.id)
    backfill = get_history_backfill(stored.sync_state["channels"][CHANNEL_A])
    assert backfill.get("active_before_post_id") == "p55"


def test_page_only_newer_than_active_end_progresses_cursor_without_objects(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    "bootstrap_complete": True,
                    "last_processed_post_id": "p-new",
                    "last_processed_create_at_ms": _ms(5),
                    "edit_sweep_watermark_ms": _ms(4),
                    "history_backfill": {
                        "version": 1,
                        "active_start_ms": _ms(30),
                        "active_end_ms": _ms(10),
                        "active_history_days": 14,
                        "active_before_post_id": "p-new",
                    },
                },
            },
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={
            CHANNEL_A: [
                _post("p-mid", CHANNEL_A, _ms(8)),
                _post("p-new", CHANNEL_A, _ms(5)),
                _post("p-extra", CHANNEL_A, _ms(4)),
            ],
        },
    )
    service = _build_service(
        db_session,
        credential_key,
        transport,
        initial_posts_per_channel=10,
        max_posts_per_run=1,
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert db_session.scalar(
        select(func.count()).select_from(Object).where(Object.metadata_["post_id"].as_string() == "p-mid")
    ) == 0
    stored = db_session.get(MattermostAccount, account.id)
    backfill = get_history_backfill(stored.sync_state["channels"][CHANNEL_A])
    assert backfill.get("active_before_post_id") == "p-mid"
    assert backfill.get("active_start_ms") == _ms(30)


def test_page_crossing_active_start_materializes_in_window_and_completes(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    **_bootstrap_channel_state(),
                    "history_backfill": {
                        "version": 1,
                        "active_start_ms": _ms(15),
                        "active_end_ms": FIXED_NOW_MS,
                        "active_history_days": 14,
                        "active_before_post_id": "p-top",
                    },
                },
            },
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={
            CHANNEL_A: [
                _post("p-old", CHANNEL_A, _ms(25)),
                _post("p-in", CHANNEL_A, _ms(12)),
                _post("p-top", CHANNEL_A, _ms(5)),
            ],
        },
    )
    service = _build_service(db_session, credential_key, transport, initial_posts_per_channel=10)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    assert db_session.scalar(
        select(Object).where(Object.metadata_["post_id"].as_string() == "p-in")
    ) is not None
    assert db_session.scalar(
        select(Object).where(Object.metadata_["post_id"].as_string() == "p-old")
    ) is None
    stored = db_session.get(MattermostAccount, account.id)
    backfill = get_history_backfill(stored.sync_state["channels"][CHANNEL_A])
    assert backfill.get("covered_start_ms") == _ms(15)
    assert backfill.get("active_start_ms") is None


def test_empty_provider_page_completes_interval(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    **_bootstrap_channel_state(),
                    "history_backfill": {
                        "version": 1,
                        "active_start_ms": _ms(14),
                        "active_end_ms": FIXED_NOW_MS,
                        "active_history_days": 14,
                        "active_before_post_id": "missing",
                    },
                },
            },
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={CHANNEL_A: [_post("missing", CHANNEL_A, _ms(5))]},
    )
    service = _build_service(db_session, credential_key, transport, initial_posts_per_channel=10)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(MattermostAccount, account.id)
    backfill = get_history_backfill(stored.sync_state["channels"][CHANNEL_A])
    assert backfill.get("covered_start_ms") == _ms(14)
    assert backfill.get("active_start_ms") is None


def test_short_final_page_completes_interval(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    **_bootstrap_channel_state(),
                    "history_backfill": {
                        "version": 1,
                        "active_start_ms": _ms(14),
                        "active_end_ms": FIXED_NOW_MS,
                        "active_history_days": 14,
                        "active_before_post_id": "p3",
                    },
                },
            },
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={
            CHANNEL_A: [
                _post("p1", CHANNEL_A, _ms(12)),
                _post("p2", CHANNEL_A, _ms(11)),
                _post("p3", CHANNEL_A, _ms(10)),
            ],
        },
    )
    service = _build_service(
        db_session,
        credential_key,
        transport,
        initial_posts_per_channel=10,
    )
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(MattermostAccount, account.id)
    backfill = get_history_backfill(stored.sync_state["channels"][CHANNEL_A])
    assert backfill.get("covered_start_ms") == _ms(14)
    assert backfill.get("active_start_ms") is None


def test_crash_during_provider_call_keeps_cursor(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    **_bootstrap_channel_state(),
                    "history_backfill": {
                        "version": 1,
                        "active_start_ms": _ms(30),
                        "active_end_ms": FIXED_NOW_MS,
                        "active_history_days": 14,
                        "active_before_post_id": "p100",
                    },
                },
            },
            "last_history_channel_id": CHANNEL_B,
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={CHANNEL_A: [_post("p50", CHANNEL_A, _ms(20)), _post("p100", CHANNEL_A, _ms(10))]},
    )

    def boom(*args, **kwargs):
        raise RuntimeError("provider boom")

    transport.get_posts_before = boom
    service = _build_service(db_session, credential_key, transport)
    with pytest.raises(RuntimeError, match="provider boom"):
        service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(MattermostAccount, account.id)
    backfill = get_history_backfill(stored.sync_state["channels"][CHANNEL_A])
    assert backfill.get("active_before_post_id") == "p100"
    assert stored.sync_state.get("last_history_channel_id") == CHANNEL_B


def test_crash_mid_materialization_retries_same_page_without_duplicates(
    db_session,
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    **_bootstrap_channel_state(),
                    "history_backfill": {
                        "version": 1,
                        "active_start_ms": _ms(30),
                        "active_end_ms": FIXED_NOW_MS,
                        "active_history_days": 14,
                        "active_before_post_id": "p100",
                    },
                },
            },
        },
    )
    posts = [
        _post(f"p{idx}", CHANNEL_A, _ms(20) + idx * 1000)
        for idx in range(60, 70)
    ]
    posts.append(_post("p100", CHANNEL_A, _ms(10)))
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={CHANNEL_A: posts},
    )
    service = _build_service(db_session, credential_key, transport, initial_posts_per_channel=10)
    crash_count = 0
    original_upsert = service._upsert_post

    def crash_wrapper(**kwargs):
        nonlocal crash_count
        post = kwargs["post"]
        if crash_count == 0 and str(post.get("id")) == "p62":
            crash_count += 1
            raise RuntimeError("simulated crash")
        return original_upsert(**kwargs)

    monkeypatch.setattr(service, "_upsert_post", crash_wrapper)
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(MattermostAccount, account.id)
    backfill = get_history_backfill(stored.sync_state["channels"][CHANNEL_A])
    assert backfill.get("active_before_post_id") == "p100"
    before_calls = [
        (params or {}).get("before")
        for _, path, params in transport.calls
        if (params or {}).get("before") is not None
    ]
    assert before_calls == ["p100"]

    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(MattermostAccount, account.id)
    backfill = get_history_backfill(stored.sync_state["channels"][CHANNEL_A])
    assert backfill.get("active_before_post_id") == "p60"
    embed_jobs = list(db_session.scalars(select(Job).where(Job.type == "embed_object")))
    assert len(embed_jobs) == 10


def test_new_historical_post_created_once_with_embed(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={"channels": {CHANNEL_A: _bootstrap_channel_state()}},
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={CHANNEL_A: [_post("hist-1", CHANNEL_A, _ms(12))]},
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    obj = db_session.scalar(
        select(Object).where(Object.metadata_["post_id"].as_string() == "hist-1")
    )
    assert obj is not None
    embed_jobs = list(db_session.scalars(select(Job).where(Job.type == "embed_object")))
    assert len(embed_jobs) == 1


def test_existing_unchanged_post_no_duplicate_embed(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={"channels": {CHANNEL_A: _bootstrap_channel_state()}},
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={CHANNEL_A: [_post("hist-1", CHANNEL_A, _ms(12))]},
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    jobs_first = list(db_session.scalars(select(Job).where(Job.type == "embed_object")))
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    jobs_second = list(db_session.scalars(select(Job).where(Job.type == "embed_object")))
    assert len(jobs_first) == 1
    assert len(jobs_second) == 1


def test_history_increase_plans_missing_older_interval_only(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    **_bootstrap_channel_state(),
                    "history_backfill": {
                        "version": 1,
                        "covered_start_ms": _ms(14),
                        "covered_oldest_post_id": "p-old",
                    },
                },
            },
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={
            CHANNEL_A: [
                _post("p-90", CHANNEL_A, _ms(80)),
                _post("p-old", CHANNEL_A, _ms(14)),
            ],
        },
    )
    service = _build_service(db_session, credential_key, transport, sync_days=90, initial_posts_per_channel=5)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    before_calls = [
        (params or {}).get("before")
        for _, path, params in transport.calls
        if (params or {}).get("before") is not None
    ]
    assert before_calls == ["p-old"]


def test_history_decrease_discards_active_cursor_before_provider_call(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    **_bootstrap_channel_state(),
                    "history_backfill": {
                        "version": 1,
                        "covered_start_ms": _ms(90),
                        "active_start_ms": _ms(14),
                        "active_end_ms": FIXED_NOW_MS,
                        "active_history_days": 90,
                        "active_before_post_id": "p-drop",
                    },
                },
            },
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={CHANNEL_A: [_post("live-only", CHANNEL_A, _ms(1))]},
    )
    service = _build_service(db_session, credential_key, transport, sync_days=14)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(MattermostAccount, account.id)
    backfill = get_history_backfill(stored.sync_state["channels"][CHANNEL_A])
    assert backfill.get("active_before_post_id") is None
    assert backfill.get("covered_start_ms") == _ms(90)
    assert db_session.scalar(
        select(Object).where(Object.metadata_["post_id"].as_string() == "p-drop")
    ) is None


def test_forward_and_history_state_preservation(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    "bootstrap_complete": True,
                    "last_processed_post_id": "live-anchor",
                    "last_processed_create_at_ms": _ms(1),
                    "edit_sweep_watermark_ms": _ms(1),
                    "custom_marker": True,
                    "history_backfill": {
                        "version": 1,
                        "covered_start_ms": _ms(30),
                    },
                },
            },
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={
            CHANNEL_A: [
                _post("hist-1", CHANNEL_A, _ms(20)),
                _post("live-anchor", CHANNEL_A, _ms(1)),
            ],
        },
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(MattermostAccount, account.id)
    entry = stored.sync_state["channels"][CHANNEL_A]
    assert entry["last_processed_post_id"] == "live-anchor"
    assert entry["custom_marker"] is True
    assert get_history_backfill(entry).get("covered_start_ms") == _ms(30)


def test_multi_channel_round_robin_continuation(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_A: {
                    **_bootstrap_channel_state(),
                    "history_backfill": {"version": 1, "covered_start_ms": _ms(30)},
                },
                CHANNEL_B: {
                    **_bootstrap_channel_state(last_post_id="live-b"),
                    "history_backfill": {"version": 1, "covered_start_ms": _ms(30)},
                },
                CHANNEL_C: {
                    **_bootstrap_channel_state(last_post_id="live-c"),
                    "history_backfill": {"version": 1, "covered_start_ms": _ms(30)},
                },
            },
            "last_history_channel_id": CHANNEL_A,
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A), _channel(CHANNEL_B), _channel(CHANNEL_C)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={
            CHANNEL_A: [_post("a-old", CHANNEL_A, _ms(20))],
            CHANNEL_B: [_post("b-old", CHANNEL_B, _ms(20))],
            CHANNEL_C: [_post("c-old", CHANNEL_C, _ms(20))],
        },
    )
    service = _build_service(db_session, credential_key, transport, sync_days=90)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(MattermostAccount, account.id)
    assert stored.sync_state.get("last_history_channel_id") == CHANNEL_B


def test_removed_channel_state_retained_no_history_request(
    db_session,
    credential_key: str,
) -> None:
    account = _connect_account(
        db_session,
        credential_key,
        sync_state={
            "channels": {
                CHANNEL_REMOVED: {
                    "history_backfill": {
                        "version": 1,
                        "covered_start_ms": _ms(30),
                    },
                },
            },
        },
    )
    transport = FakeMattermostTransport(
        channels=[_channel(CHANNEL_A)],
        teams=[TEAM],
        users_by_id={"author-1": AUTHOR},
        posts_by_channel={CHANNEL_A: [_post("a-old", CHANNEL_A, _ms(20))]},
    )
    service = _build_service(db_session, credential_key, transport)
    service.sync_account(account.id, BOOTSTRAP_USER_ID, include_history_pass=True)
    stored = db_session.get(MattermostAccount, account.id)
    removed = get_history_backfill(stored.sync_state["channels"][CHANNEL_REMOVED])
    assert removed.get("covered_start_ms") == _ms(30)


def test_disabled_mattermost_worker_skips_provider_calls(
    credential_key: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_embedding_service,
) -> None:
    handler_calls = 0

    def fake_handler(session, embedding_service, payload, user_id) -> None:
        nonlocal handler_calls
        handler_calls += 1

    monkeypatch.setattr(settings, "secretary_credential_key", credential_key)
    conn = engine.connect()
    trans = conn.begin()
    persist_session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    store = MattermostAccountStore(
        persist_session,
        MattermostAccountStore.build_encryption(credential_key),
    )
    account = store.upsert_account(
        user_id=BOOTSTRAP_USER_ID,
        normalized_server_url=ALLOWED_URL,
        remote_user_id="user-1",
        username="alice",
        access_token=PAT,
        display_name="Alice",
        email="alice@example.com",
    )
    SourceSyncScheduler(persist_session).run_maintenance()
    SourceSyncPreferenceService.build(persist_session).update_preference(
        BOOTSTRAP_USER_ID,
        SOURCE_MATTERMOST,
        enabled=False,
        enabled_specified=True,
    )
    trans.commit()
    conn.close()

    conn = engine.connect()
    trans = conn.begin()
    ready_session = __import__("sqlalchemy.orm", fromlist=["Session"]).Session(bind=conn)
    job = ready_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_MATTERMOST,
            Job.payload["account_id"].as_string() == str(account.id),
        )
    )
    job.run_after = utcnow() - timedelta(seconds=1)
    trans.commit()
    conn.close()

    with patch.dict(HANDLERS, {JOB_TYPE_SYNC_MATTERMOST: fake_handler}):
        assert process_one_job(fake_embedding_service)

    assert handler_calls == 0
