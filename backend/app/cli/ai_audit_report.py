"""CLI for sanitized AI audit reports (PHASE 28D-A / 28D-A-R1)."""

import argparse
import json
import sys
from datetime import datetime, timedelta
from uuid import UUID

from app.ai_audit.constants import MAX_TRACE_LIST
from app.ai_audit.trace_service import AITraceService
from app.db.session import SessionLocal
from app.services.job_queue_service import utcnow
from app.users.bootstrap import BOOTSTRAP_USER_ID


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def _print_summary(user_id: UUID, hours: int) -> int:
    now = utcnow()
    started_after = now - timedelta(hours=hours)
    session = SessionLocal()
    try:
        summary = AITraceService(session).build_summary(user_id, started_after, now)
        print(json.dumps(summary, indent=2, default=str))
        return 0
    finally:
        session.close()


def _print_list(user_id: UUID, hours: int, workload: str | None, limit: int) -> int:
    now = utcnow()
    started_after = now - timedelta(hours=hours)
    session = SessionLocal()
    try:
        rows = AITraceService(session).list_traces(
            user_id,
            started_after,
            now,
            workload=workload,
            limit=limit,
        )
        print(json.dumps(rows, indent=2, default=str))
        return 0
    finally:
        session.close()


def _print_trace(user_id: UUID, trace_id: UUID, include_payloads: bool) -> int:
    session = SessionLocal()
    try:
        service = AITraceService(session)
        trace = service.get_trace(trace_id, user_id)
        if trace is None:
            print("trace not found", file=sys.stderr)
            return 1
        events = service.list_trace_events(trace_id, user_id, include_payloads=include_payloads)
        payload = {
            "trace_id": str(trace.id),
            "workload": trace.workload,
            "started_at": trace.started_at.isoformat(),
            "finished_at": trace.finished_at.isoformat() if trace.finished_at else None,
            "success": trace.success,
            "events": [
                {
                    "sequence": event["sequence"],
                    "event_type": event["event_type"],
                    "created_at": event["created_at"].isoformat(),
                    "metadata": event["metadata"],
                }
                for event in events
            ],
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Personal Secretary AI audit report")
    sub = parser.add_subparsers(dest="command", required=True)

    summary_parser = sub.add_parser("summary", help="Aggregate audit summary")
    summary_parser.add_argument("--user-id", default=str(BOOTSTRAP_USER_ID))
    summary_parser.add_argument("--hours", type=int, default=24)

    list_parser = sub.add_parser("list", help="Bounded trace listing")
    list_parser.add_argument("--user-id", default=str(BOOTSTRAP_USER_ID))
    list_parser.add_argument("--hours", type=int, default=24)
    list_parser.add_argument("--workload", default=None)
    list_parser.add_argument("--limit", type=int, default=MAX_TRACE_LIST)

    trace_parser = sub.add_parser("trace", help="Single trace waterfall")
    trace_parser.add_argument("trace_id")
    trace_parser.add_argument("--user-id", default=str(BOOTSTRAP_USER_ID))
    trace_parser.add_argument(
        "--include-payloads",
        action="store_true",
        help="Include retained payloads when within payload retention window",
    )

    cleanup_parser = sub.add_parser("cleanup", help="Expire payloads and old traces")
    cleanup_parser.add_argument("--user-id", default=str(BOOTSTRAP_USER_ID))

    args = parser.parse_args(argv)
    user_id = UUID(str(args.user_id))

    if args.command == "summary":
        return _print_summary(user_id, args.hours)

    if args.command == "list":
        return _print_list(user_id, args.hours, args.workload, args.limit)

    if args.command == "trace":
        return _print_trace(user_id, UUID(str(args.trace_id)), args.include_payloads)

    if args.command == "cleanup":
        session = SessionLocal()
        try:
            result = AITraceService(session).cleanup_expired()
            session.commit()
            print(json.dumps(result, indent=2))
            return 0
        finally:
            session.close()

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
