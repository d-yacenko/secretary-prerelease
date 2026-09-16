"""PHASE 28C-R1-R1-R1 — idle source status must not block sync banner clearance."""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.db.models import Job
from app.jobs.constants import JOB_TYPE_SYNC_GOOGLE_GMAIL
from app.services.job_queue_service import JobQueueService
from app.services.source_status_service import SourceStatusService
from app.services.source_sync_scheduler import SourceSyncScheduler
from app.source_sync.constants import SOURCE_GMAIL
from app.users.bootstrap import BOOTSTRAP_USER_ID
from tests.test_phase_28c_source_preferences import _gmail_account_id


@pytest.fixture
def credential_key() -> str:
    return Fernet.generate_key().decode()


def test_enabled_source_without_active_job_reports_scheduled_idle(
    db_session, credential_key, monkeypatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.secretary_credential_key", credential_key)
    account_id = _gmail_account_id(db_session, credential_key, monkeypatch)
    SourceSyncScheduler(db_session).run_maintenance()
    job = db_session.scalar(
        select(Job).where(
            Job.type == JOB_TYPE_SYNC_GOOGLE_GMAIL,
            Job.payload["account_id"].as_string() == str(account_id),
        )
    )
    assert job is not None
    JobQueueService(db_session).retire_recurring_source_job(job)
    rows = SourceStatusService(db_session, BOOTSTRAP_USER_ID).list_status()
    gmail_rows = [row for row in rows if row.source == SOURCE_GMAIL]
    assert len(gmail_rows) == 1
    row = gmail_rows[0]
    assert row.enabled is True
    assert row.status == "scheduled"
    assert row.next_sync_at is None
    assert row.last_error is None
