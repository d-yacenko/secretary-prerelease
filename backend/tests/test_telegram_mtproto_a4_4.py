"""Telegram Depth A4.4 — recurring scope reconciliation and history sync."""

from datetime import timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_errors import (
    TelegramMtprotoAuthorizationInvalidError,
    TelegramMtprotoGroupUnavailableError,
    TelegramMtprotoProviderUnavailableError,
    TelegramMtprotoScopeUnavailableError,
    classify_telegram_sync_failure,
)
from app.core.config import settings
from app.db.models import Job, TelegramMtprotoAccount, TelegramMtprotoChatSelection, User
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
    RECURRING_SOURCE_JOB_TYPES,
    WORKER_SOURCE_SYNC_LANE_TYPES,
)
from app.jobs.handlers import HANDLERS
from app.jobs.recurring_job_finalization import (
    finalize_recurring_job_failure,
    finalize_recurring_job_success,
)
from app.services.job_queue_service import JobQueueService, sanitize_job_error, utcnow
from app.services.source_sync_preference_service import (
    SUPPORTED_SOURCE_KEYS_ORDERED,
    deployment_default_interval_seconds_for_job_type,
)
from app.services.source_sync_scheduler import SourceSyncScheduler
from app.services.telegram_mtproto_recurring_sync_service import (
    TELEGRAM_MTPROTO_RECURRING_MAX_PEERS_PER_RUN,
    TelegramMtprotoRecurringSyncService,
)

KEY = Fernet.generate_key().decode()


def _account(session, user_id):
    account = TelegramMtprotoAccount(
        user_id=user_id,
        telegram_user_id=abs(hash((str(user_id), "telegram"))) % 2_000_000_000,
        session_encrypted="encrypted-session-placeholder",
    )
    session.add(account)
    session.flush()
    return account


def _selection(session, account_id, peer_id, *, active=True, manual=True):
    row = TelegramMtprotoChatSelection(
        account_id=account_id,
        peer_id=peer_id,
        peer_kind="private" if peer_id > 0 else "group",
        provider_peer_reference_encrypted=f"encrypted-reference-{peer_id}",
        title=f"Peer {peer_id}",
        manual_selected=manual,
        scope_active=active,
    )
    session.add(row)
    session.flush()
    return row


class _FakeScope:
    def __init__(self, events, action=None):
        self.events = events
        self.action = action

    async def reconcile_scope(self, user_id):
        self.events.append("reconcile")
        if self.action is not None:
            self.action()


class _FakeHistory:
    def __init__(self, events, failures=None):
        self.events = events
        self.failures = failures or {}
        self.calls = []

    async def sync_scope_peer(self, user_id, peer_id):
        self.events.append(f"history:{peer_id}")
        self.calls.append(peer_id)
        error = self.failures.get(peer_id)
        if error is not None:
            raise error


def _service(session, events, *, scope_action=None, failures=None):
    history = _FakeHistory(events, failures)
    service = TelegramMtprotoRecurringSyncService(
        session,
        scope_service=_FakeScope(events, scope_action),
        history_service=history,
    )
    return service, history


def test_recurring_job_identity_lane_and_safe_payload(db_session, monkeypatch):
    monkeypatch.setattr(settings, "secretary_credential_key", KEY)
    monkeypatch.setattr(settings, "telegram_api_id", 123)
    monkeypatch.setattr(settings, "telegram_api_hash", "telegram-api-hash")
    user = User(id=uuid4(), display_name="A4.4 scheduler user")
    db_session.add(user)
    db_session.flush()
    account = _account(db_session, user.id)

    scheduler = SourceSyncScheduler(db_session)
    scheduler._maintain_telegram_accounts()
    scheduler._maintain_telegram_accounts()
    jobs = list(
        db_session.scalars(
            select(Job).where(Job.type == JOB_TYPE_SYNC_TELEGRAM_MTPROTO)
        )
    )

    assert JOB_TYPE_SYNC_TELEGRAM_MTPROTO in RECURRING_SOURCE_JOB_TYPES
    assert JOB_TYPE_SYNC_TELEGRAM_MTPROTO in WORKER_SOURCE_SYNC_LANE_TYPES
    assert HANDLERS[JOB_TYPE_SYNC_TELEGRAM_MTPROTO] is not None
    assert len(jobs) == 1
    assert jobs[0].payload == {"account_id": str(account.id)}


def test_scheduler_lifecycle_trigger_retire_and_running_stale_job(db_session, monkeypatch):
    monkeypatch.setattr(settings, "secretary_credential_key", KEY)
    monkeypatch.setattr(settings, "telegram_api_id", 123)
    monkeypatch.setattr(settings, "telegram_api_hash", "telegram-api-hash")
    user = User(id=uuid4(), display_name="A4.4 lifecycle user")
    db_session.add(user)
    db_session.flush()
    account = _account(db_session, user.id)
    scheduler = SourceSyncScheduler(db_session)
    scheduler._maintain_telegram_accounts()
    job = db_session.scalar(select(Job).where(Job.type == JOB_TYPE_SYNC_TELEGRAM_MTPROTO))
    assert job is not None
    assert scheduler.trigger_all_for_user(user.id) == [f"telegram_mtproto:{account.id}"]

    monkeypatch.setattr(settings, "telegram_api_hash", "")
    scheduler._maintain_telegram_accounts()
    assert job.status == JOB_STATUS_DONE

    job.status = JOB_STATUS_PENDING
    job.locked_at = None
    scheduler._maintain_telegram_accounts()
    assert job.status == JOB_STATUS_DONE
    job.status = JOB_STATUS_RUNNING
    scheduler._maintain_telegram_accounts()
    assert job.status == JOB_STATUS_RUNNING


def test_deleted_account_job_is_retired_but_running_job_is_preserved(db_session, monkeypatch):
    monkeypatch.setattr(settings, "secretary_credential_key", KEY)
    monkeypatch.setattr(settings, "telegram_api_id", 123)
    monkeypatch.setattr(settings, "telegram_api_hash", "telegram-api-hash")
    user = User(id=uuid4(), display_name="A4.4 deleted account user")
    db_session.add(user)
    db_session.flush()
    account = _account(db_session, user.id)
    job = Job(
        user_id=user.id,
        type=JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
        payload={"account_id": str(account.id)},
        status=JOB_STATUS_PENDING,
    )
    db_session.add(job)
    db_session.flush()
    db_session.delete(account)
    db_session.flush()

    scheduler = SourceSyncScheduler(db_session)
    scheduler._retire_stale_recurring_jobs(CredentialEncryption(KEY))
    assert job.status == JOB_STATUS_DONE

    job.status = JOB_STATUS_RUNNING
    scheduler._retire_stale_recurring_jobs(CredentialEncryption(KEY))
    assert job.status == JOB_STATUS_RUNNING


def test_telegram_interval_is_separate_from_generic_preferences():
    assert JOB_TYPE_SYNC_TELEGRAM_MTPROTO not in SUPPORTED_SOURCE_KEYS_ORDERED
    assert deployment_default_interval_seconds_for_job_type(
        JOB_TYPE_SYNC_TELEGRAM_MTPROTO
    ) == 300


def test_telegram_failure_classification_and_sanitization():
    provider_error = TelegramMtprotoProviderUnavailableError("provider-body", 37)
    assert classify_telegram_sync_failure(provider_error) == ("transient", True, 37)
    assert classify_telegram_sync_failure(
        TelegramMtprotoAuthorizationInvalidError("auth details")
    ) == ("authentication", False, None)
    assert sanitize_job_error(provider_error) == "TelegramMtprotoProviderUnavailableError"


@pytest.mark.asyncio
async def test_reconcile_precedes_history_and_only_active_account_peers_sync(db_session):
    user = User(id=uuid4(), display_name="A4.4 orchestration user")
    other_user = User(id=uuid4(), display_name="A4.4 other user")
    db_session.add_all([user, other_user])
    db_session.flush()
    account = _account(db_session, user.id)
    other_account = _account(db_session, other_user.id)
    _selection(db_session, account.id, 1, active=True, manual=False)
    _selection(db_session, account.id, 2, active=False)
    _selection(db_session, other_account.id, 3, active=True)
    events = []
    service, history = _service(db_session, events)

    await service.run(user.id, account.id, {})

    assert events == ["reconcile", "history:1"]
    assert history.calls == [1]


@pytest.mark.asyncio
async def test_reconcile_scope_churn_is_applied_before_peer_selection(db_session):
    user = User(id=uuid4(), display_name="A4.4 churn user")
    db_session.add(user)
    db_session.flush()
    account = _account(db_session, user.id)
    removed = _selection(db_session, account.id, 10, active=True)
    added = _selection(db_session, account.id, 11, active=False)

    def reconcile():
        removed.scope_active = False
        added.scope_active = True
        db_session.flush()

    events = []
    service, history = _service(db_session, events, scope_action=reconcile)
    await service.run(user.id, account.id, {})

    assert history.calls == [11]


@pytest.mark.asyncio
async def test_fail_closed_reconcile_makes_zero_history_calls(db_session):
    user = User(id=uuid4(), display_name="A4.4 fail closed user")
    db_session.add(user)
    db_session.flush()
    account = _account(db_session, user.id)
    _selection(db_session, account.id, 20)
    events = []

    class FailingScope:
        async def reconcile_scope(self, user_id):
            raise TelegramMtprotoScopeUnavailableError("provider details hidden")

    history = _FakeHistory(events)
    service = TelegramMtprotoRecurringSyncService(
        db_session, scope_service=FailingScope(), history_service=history
    )
    with pytest.raises(TelegramMtprotoScopeUnavailableError):
        await service.run(user.id, account.id, {})
    assert history.calls == []


@pytest.mark.asyncio
async def test_batch_bound_round_robin_wrap_and_peer_local_failure(db_session):
    user = User(id=uuid4(), display_name="A4.4 fair user")
    db_session.add(user)
    db_session.flush()
    account = _account(db_session, user.id)
    for peer_id in range(1, 13):
        _selection(db_session, account.id, peer_id)
    events = []
    service, history = _service(
        db_session,
        events,
        failures={1: TelegramMtprotoGroupUnavailableError("unavailable")},
    )
    payload = {"telegram_peer_cursor": 0}

    await service.run(user.id, account.id, payload)
    assert len(history.calls) == TELEGRAM_MTPROTO_RECURRING_MAX_PEERS_PER_RUN
    assert history.calls[0] == 1
    assert history.calls[-1] == 10
    assert payload["telegram_peer_cursor"] == 10

    await service.run(user.id, account.id, payload)
    assert history.calls[10:12] == [11, 12]
    assert len(history.calls[10:]) == TELEGRAM_MTPROTO_RECURRING_MAX_PEERS_PER_RUN
    assert payload["telegram_peer_cursor"] == 8


@pytest.mark.asyncio
async def test_provider_failure_stops_batch_and_never_leaks_job_values(db_session):
    user = User(id=uuid4(), display_name="A4.4 provider user")
    db_session.add(user)
    db_session.flush()
    account = _account(db_session, user.id)
    _selection(db_session, account.id, 31)
    _selection(db_session, account.id, 32)
    events = []
    service, history = _service(
        db_session,
        events,
        failures={31: TelegramMtprotoProviderUnavailableError("session-secret", 47)},
    )

    with pytest.raises(TelegramMtprotoProviderUnavailableError):
        await service.run(user.id, account.id, {})
    assert history.calls == [31]

    queue = JobQueueService(db_session)
    job = queue.enqueue(
        JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
        {"account_id": str(account.id)},
        user.id,
    )
    job.status = JOB_STATUS_RUNNING
    job.attempts = 1
    finalize_recurring_job_failure(
        db_session,
        job.id,
        user.id,
        JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
        "TelegramMtprotoProviderUnavailableError",
        failure_kind="transient",
        retryable=True,
        retry_after_seconds=47,
    )
    assert job.status == JOB_STATUS_PENDING
    assert 46 <= (job.run_after - utcnow()).total_seconds() <= 47
    assert job.last_error == "TelegramMtprotoProviderUnavailableError"
    assert "session-secret" not in job.last_error


@pytest.mark.asyncio
async def test_empty_reconciled_scope_does_not_fetch_history(db_session):
    user = User(id=uuid4(), display_name="A4.4 empty user")
    db_session.add(user)
    db_session.flush()
    account = _account(db_session, user.id)
    row = _selection(db_session, account.id, 41)

    def reconcile():
        row.scope_active = False
        db_session.flush()

    events = []
    service, history = _service(db_session, events, scope_action=reconcile)
    payload = {"telegram_peer_cursor": 4}
    await service.run(user.id, account.id, payload)

    assert history.calls == []
    assert payload["telegram_peer_cursor"] == 0


def test_success_clears_failure_metadata_and_uses_300_seconds(db_session):
    user = User(id=uuid4(), display_name="A4.4 success user")
    db_session.add(user)
    db_session.flush()
    queue = JobQueueService(db_session)
    job = queue.enqueue(
        JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
        {
            "account_id": str(uuid4()),
            "telegram_peer_cursor": 7,
            "last_error_kind": "transient",
            "last_error_retryable": True,
        },
        user.id,
    )
    job.status = JOB_STATUS_RUNNING
    finalize_recurring_job_success(
        db_session,
        job.id,
        user.id,
        JOB_TYPE_SYNC_TELEGRAM_MTPROTO,
    )
    assert job.status == JOB_STATUS_PENDING
    assert job.payload["telegram_peer_cursor"] == 7
    assert "last_error_kind" not in job.payload
    assert job.run_after >= utcnow() + timedelta(seconds=299)
