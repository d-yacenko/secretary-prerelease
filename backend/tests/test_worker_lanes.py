"""Reserved scheduled worker lane isolation from a blocked general job."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.schemas import ObjectCreate
from app.db.engine import engine
from app.db.models import Job, Notification, Object, User
from app.domain.scheduled_activity import (
    SCHEDULED_ACTIVITY_STATUS_COMPLETED,
    SCHEDULED_ACTIVITY_STATUS_SCHEDULED,
)
from app.jobs.constants import (
    JOB_STATUS_DONE,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_EMBED_OBJECT,
    JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
    JOB_TYPE_SYNC_GOOGLE_GMAIL,
    JOB_TYPE_SYNC_YANDEX_MAIL,
    WORKER_GENERAL_EXCLUDE_TYPES,
)
from app.jobs.handlers import get_handler
from app.jobs.worker import process_one_job
from app.llm.embedding_service import FakeEmbeddingService
from app.services.graph_service import GraphService
from app.services.job_queue_service import JobQueueService
from app.services.scheduled_activity_service import ScheduledActivityService


def _clear_jobs() -> None:
    with Session(engine) as session:
        session.execute(delete(Job))
        session.commit()


def _persist_user() -> uuid.UUID:
    user_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=user_id, display_name=f"lanes-{user_id}"))
        session.commit()
    return user_id


def _cleanup_user(user_id: uuid.UUID) -> None:
    with Session(engine) as session:
        session.execute(delete(Notification).where(Notification.user_id == user_id))
        session.execute(delete(Job).where(Job.user_id == user_id))
        session.execute(delete(Object).where(Object.user_id == user_id))
        session.execute(delete(User).where(User.id == user_id))
        session.commit()


def _load(model, entity_id):
    with Session(engine) as session:
        row = session.get(model, entity_id)
        if row is not None:
            session.expunge(row)
        return row


def _persist_due_once(user_id: uuid.UUID, title: str) -> tuple[uuid.UUID, uuid.UUID]:
    due_at = datetime.now(UTC) - timedelta(seconds=1)
    with Session(engine) as session:
        graph = GraphService(session, user_id)
        obj = ScheduledActivityService(session, user_id, graph).create_once(
            title=title,
            body="Lane isolation",
            run_at=datetime.now(UTC) + timedelta(hours=2),
            priority="normal",
            origin_state="confirmed",
            confidence=None,
            enqueue_embedding=False,
        )
        job = session.scalar(
            select(Job).where(
                Job.user_id == user_id,
                Job.type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
            )
        )
        assert job is not None
        obj.due_at = due_at
        job.run_after = due_at
        activity_id, job_id = obj.id, job.id
        session.commit()
    return activity_id, job_id


def _persist_embed_job(user_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    with Session(engine) as session:
        obj = GraphService(session, user_id).create_object(
            ObjectCreate(
                kind="task",
                title=f"Lane general {uuid.uuid4()}",
                origin="user",
            )
        )
        job = JobQueueService(session).enqueue(
            JOB_TYPE_EMBED_OBJECT,
            {"object_id": str(obj.id)},
            user_id,
            run_after=datetime.now(UTC) - timedelta(minutes=1),
        )
        object_id, job_id = obj.id, job.id
        session.commit()
    return object_id, job_id


def test_scheduled_lane_fires_while_general_handler_blocked(monkeypatch) -> None:
    _clear_jobs()
    user_id = _persist_user()
    started = threading.Event()
    release = threading.Event()

    def blocking_embed(session, embedding_service, payload, user_id_arg):
        started.set()
        if not release.wait(timeout=15):
            raise TimeoutError("general handler was not released")

    original = get_handler

    def patched(job_type: str):
        if job_type == JOB_TYPE_EMBED_OBJECT:
            return blocking_embed
        return original(job_type)

    monkeypatch.setattr("app.jobs.worker.get_handler", patched)
    try:
        _persist_embed_job(user_id)
        activity_id, scheduled_job_id = _persist_due_once(user_id, "Lane reminder")

        general_thread = threading.Thread(
            target=lambda: process_one_job(
                FakeEmbeddingService(),
                exclude_types=WORKER_GENERAL_EXCLUDE_TYPES,
            ),
            daemon=True,
        )
        general_thread.start()
        assert started.wait(timeout=5)

        processed = process_one_job(include_types={JOB_TYPE_RUN_SCHEDULED_ACTIVITY})
        assert processed

        activity = _load(Object, activity_id)
        scheduled_job = _load(Job, scheduled_job_id)
        assert activity is not None
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_COMPLETED
        assert activity.occurred_at is not None
        assert scheduled_job is not None
        assert scheduled_job.status == JOB_STATUS_DONE
        with Session(engine) as session:
            note_count = session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user_id)
            )
        assert note_count == 1

        running_general = None
        with Session(engine) as session:
            running_general = session.scalar(
                select(Job).where(
                    Job.user_id == user_id,
                    Job.type == JOB_TYPE_EMBED_OBJECT,
                )
            )
            session.expunge(running_general)
        assert running_general is not None
        assert running_general.status == JOB_STATUS_RUNNING

        release.set()
        general_thread.join(timeout=5)
        assert not general_thread.is_alive()
        finished_general = _load(Job, running_general.id)
        assert finished_general is not None
        assert finished_general.status == JOB_STATUS_DONE
    finally:
        release.set()
        _cleanup_user(user_id)


def test_scheduled_lane_failure_does_not_block_general_lane(monkeypatch) -> None:
    _clear_jobs()
    user_id = _persist_user()

    def failing_scheduled(session, embedding_service, payload, user_id_arg):
        raise RuntimeError("scheduled handler boom")

    original = get_handler

    def patched(job_type: str):
        if job_type == JOB_TYPE_RUN_SCHEDULED_ACTIVITY:
            return failing_scheduled
        return original(job_type)

    monkeypatch.setattr("app.jobs.worker.get_handler", patched)
    try:
        _, embed_job_id = _persist_embed_job(user_id)
        activity_id, scheduled_job_id = _persist_due_once(user_id, "Failing reminder")
        assert process_one_job(include_types={JOB_TYPE_RUN_SCHEDULED_ACTIVITY})
        scheduled_job = _load(Job, scheduled_job_id)
        assert scheduled_job is not None
        assert scheduled_job.status == JOB_STATUS_PENDING
        activity = _load(Object, activity_id)
        assert activity is not None
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_SCHEDULED

        assert process_one_job(
            FakeEmbeddingService(),
            exclude_types=WORKER_GENERAL_EXCLUDE_TYPES,
        )
        embed_job = _load(Job, embed_job_id)
        assert embed_job is not None
        assert embed_job.status == JOB_STATUS_DONE
    finally:
        _cleanup_user(user_id)


def test_general_lane_failure_does_not_block_scheduled_lane(monkeypatch) -> None:
    _clear_jobs()
    user_id = _persist_user()

    def failing_embed(session, embedding_service, payload, user_id_arg):
        raise RuntimeError("general handler boom")

    original = get_handler

    def patched(job_type: str):
        if job_type == JOB_TYPE_EMBED_OBJECT:
            return failing_embed
        return original(job_type)

    monkeypatch.setattr("app.jobs.worker.get_handler", patched)
    try:
        _, embed_job_id = _persist_embed_job(user_id)
        activity_id, scheduled_job_id = _persist_due_once(user_id, "Surviving reminder")
        assert process_one_job(
            FakeEmbeddingService(),
            exclude_types=WORKER_GENERAL_EXCLUDE_TYPES,
        )
        embed_job = _load(Job, embed_job_id)
        assert embed_job is not None
        assert embed_job.status == JOB_STATUS_PENDING

        assert process_one_job(include_types={JOB_TYPE_RUN_SCHEDULED_ACTIVITY})
        scheduled_job = _load(Job, scheduled_job_id)
        activity = _load(Object, activity_id)
        assert scheduled_job is not None
        assert scheduled_job.status == JOB_STATUS_DONE
        assert activity is not None
        assert activity.status == SCHEDULED_ACTIVITY_STATUS_COMPLETED
        assert activity.occurred_at is not None
    finally:
        _cleanup_user(user_id)


def _persist_source_sync_job(user_id: uuid.UUID, job_type: str) -> uuid.UUID:
    account_id = uuid.uuid4()
    with Session(engine) as session:
        job = JobQueueService(session).ensure_recurring_source_job(
            job_type,
            account_id,
            user_id,
            run_after=datetime.now(UTC) - timedelta(minutes=1),
        )
        job_id = job.id
        session.commit()
    return job_id


def test_gmail_source_lane_runs_while_yandex_mail_handler_blocked(monkeypatch) -> None:
    _clear_jobs()
    user_id = _persist_user()
    started = threading.Event()
    release = threading.Event()

    def blocking_yandex(session, embedding_service, payload, user_id_arg):
        started.set()
        if not release.wait(timeout=15):
            raise TimeoutError("yandex mail handler was not released")

    def ok_gmail(session, embedding_service, payload, user_id_arg):
        return None

    original = get_handler

    def patched(job_type: str):
        if job_type == JOB_TYPE_SYNC_YANDEX_MAIL:
            return blocking_yandex
        if job_type == JOB_TYPE_SYNC_GOOGLE_GMAIL:
            return ok_gmail
        return original(job_type)

    monkeypatch.setattr("app.jobs.worker.get_handler", patched)
    try:
        yandex_job_id = _persist_source_sync_job(user_id, JOB_TYPE_SYNC_YANDEX_MAIL)
        gmail_job_id = _persist_source_sync_job(user_id, JOB_TYPE_SYNC_GOOGLE_GMAIL)

        yandex_thread = threading.Thread(
            target=lambda: process_one_job(include_types={JOB_TYPE_SYNC_YANDEX_MAIL}),
            daemon=True,
        )
        yandex_thread.start()
        assert started.wait(timeout=5)

        processed = process_one_job(include_types={JOB_TYPE_SYNC_GOOGLE_GMAIL})
        assert processed
        gmail_job = _load(Job, gmail_job_id)
        assert gmail_job is not None
        assert gmail_job.status == JOB_STATUS_PENDING
        assert gmail_job.payload.get("last_success_at")

        yandex_running = _load(Job, yandex_job_id)
        assert yandex_running is not None
        assert yandex_running.status == JOB_STATUS_RUNNING

        release.set()
        yandex_thread.join(timeout=5)
        assert not yandex_thread.is_alive()
    finally:
        release.set()
        _cleanup_user(user_id)
