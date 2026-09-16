import logging
import signal
import threading
import time
from collections.abc import Callable, Collection

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.jobs.constants import (
    JOB_TYPE_RUN_SCHEDULED_ACTIVITY,
    WORKER_GENERAL_EXCLUDE_TYPES,
    WORKER_IDLE_SLEEP_SECONDS,
    source_sync_lane_job_types,
    teams_notification_lane_job_types,
)
from app.jobs.worker import process_one_job
from app.services.proactive_scheduler import ProactiveScheduler
from app.services.source_sync_scheduler import SourceSyncScheduler

logger = logging.getLogger(__name__)


def _run_isolated_maintenance(label: str, runner: Callable[[Session], None]) -> None:
    session = SessionLocal()
    try:
        runner(session)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("%s maintenance failed", label)
    finally:
        session.close()


def run_scheduler_maintenance() -> None:
    _run_isolated_maintenance(
        "source sync scheduler",
        lambda session: SourceSyncScheduler(session).run_maintenance(),
    )
    _run_isolated_maintenance(
        "proactive scheduler",
        lambda session: ProactiveScheduler(session).run_maintenance(),
    )

    def _cleanup_traces(session: Session) -> None:
        from app.ai_audit.trace_service import AITraceService

        AITraceService(session).cleanup_expired()

    _run_isolated_maintenance("ai trace cleanup", _cleanup_traces)


def _run_scheduler_maintenance() -> None:
    run_scheduler_maintenance()


def _run_job_lane(
    stop: threading.Event,
    *,
    include_types: Collection[str] | None = None,
    exclude_types: Collection[str] | None = None,
    run_scheduler: bool = False,
) -> None:
    last_scheduler_at = 0.0
    while not stop.is_set():
        try:
            if run_scheduler:
                now = time.monotonic()
                if now - last_scheduler_at >= settings.source_sync_scheduler_interval_seconds:
                    run_scheduler_maintenance()
                    last_scheduler_at = now
            processed = process_one_job(
                include_types=include_types,
                exclude_types=exclude_types,
            )
            if not processed:
                stop.wait(WORKER_IDLE_SLEEP_SECONDS)
        except Exception:
            logger.exception("worker loop error")
            stop.wait(WORKER_IDLE_SLEEP_SECONDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("worker started")
    stop = threading.Event()

    def _request_stop(signum: int, _frame: object) -> None:
        logger.info("worker received signal %s", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    scheduled = threading.Thread(
        target=_run_job_lane,
        name="worker-scheduled",
        kwargs={"stop": stop, "include_types": {JOB_TYPE_RUN_SCHEDULED_ACTIVITY}},
        daemon=True,
    )
    source_sync_threads = [
        threading.Thread(
            target=_run_job_lane,
            name=f"worker-source-{job_type}",
            kwargs={"stop": stop, "include_types": {job_type}},
            daemon=True,
        )
        for job_type in source_sync_lane_job_types()
    ]
    notification_threads = [
        threading.Thread(
            target=_run_job_lane,
            name=f"worker-teams-notification-{job_type}",
            kwargs={"stop": stop, "include_types": {job_type}},
            daemon=True,
        )
        for job_type in teams_notification_lane_job_types()
    ]
    general = threading.Thread(
        target=_run_job_lane,
        name="worker-general",
        kwargs={
            "stop": stop,
            "exclude_types": WORKER_GENERAL_EXCLUDE_TYPES,
            "run_scheduler": True,
        },
        daemon=True,
    )
    scheduled.start()
    for thread in source_sync_threads:
        thread.start()
    for thread in notification_threads:
        thread.start()
    general.start()
    stop.wait()


if __name__ == "__main__":
    main()
