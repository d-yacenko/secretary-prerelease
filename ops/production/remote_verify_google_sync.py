#!/usr/bin/env python3
"""Read-only production Google runtime verification helper."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPOSITORY_PATH = Path("/opt/secretary")
ENV_FILE = REPOSITORY_PATH / ".env"
COMPOSE = ["docker", "compose", "--env-file", str(ENV_FILE), "-f", "infra/compose.yaml", "-f", "infra/compose.deploy.yaml"]
JOB_TYPES = ("sync_google_gmail", "sync_google_calendar")


class VerificationError(RuntimeError):
    pass


def run(command: list[str], *, sensitive: bool = False) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise VerificationError("production verification command failed")
    return result.stdout.strip()


def compose(*args: str) -> str:
    return run([*COMPOSE, *args])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def service_id(service: str) -> str:
    value = compose("ps", "-q", service)
    require(bool(value), f"{service} container is missing")
    return value.splitlines()[0].strip()


def inspect(container: str, template: str) -> str:
    return run(["docker", "inspect", "--format", template, container])


def require_running(container: str) -> None:
    require(inspect(container, "{{.State.Status}}") == "running", "required container is not running")


def resolved_environment() -> dict[str, dict[str, str]]:
    raw = compose("config", "--format", "json")
    data = json.loads(raw)
    services = data.get("services", {})
    result: dict[str, dict[str, str]] = {}
    for service in ("api", "worker"):
        environment = services.get(service, {}).get("environment", {})
        if isinstance(environment, list):
            environment = dict(item.split("=", 1) for item in environment if "=" in item)
        require(isinstance(environment, dict), "application environment is unavailable")
        result[service] = {str(k): str(v) for k, v in environment.items()}
        require(result[service].get("POSTGRES_PASSWORD", "") != "", "database password is unavailable")
        require(result[service].get("SECRETARY_CREDENTIAL_KEY", "") != "", "credential key is unavailable")
    return result


def require_db_auth(db: str, environment: dict[str, str]) -> None:
    command = ["docker", "exec", "-e", f"PGPASSWORD={environment['POSTGRES_PASSWORD']}", db,
               "psql", "-U", environment.get("POSTGRES_USER", "secretary"), "-d",
               environment.get("POSTGRES_DB", "secretary"), "-tAc", "SELECT 1"]
    require(run(command, sensitive=True) == "1", "database authentication failed")


def query(db: str, environment: dict[str, str], sql: str) -> list[str]:
    command = ["docker", "exec", "-e", f"PGPASSWORD={environment['POSTGRES_PASSWORD']}", db,
               "psql", "-U", environment.get("POSTGRES_USER", "secretary"), "-d",
               environment.get("POSTGRES_DB", "secretary"), "-At", "-c", sql]
    return [line.strip() for line in run(command, sensitive=True).splitlines() if line.strip()]


def assert_runtime(worker: str) -> None:
    code = """
from datetime import UTC, datetime, timedelta
from app.connectors.google.api_errors import parse_google_retry_after
from app.connectors.google.errors import GoogleApiError, GoogleOAuthError, classify_google_sync_failure
from app.services.job_queue_service import GOOGLE_TRANSIENT_RETRY_DELAYS_SECONDS, YANDEX_TRANSIENT_RETRY_DELAYS_SECONDS
assert GOOGLE_TRANSIENT_RETRY_DELAYS_SECONDS == (10, 30, 60)
assert YANDEX_TRANSIENT_RETRY_DELAYS_SECONDS == (10, 30, 60)
oauth = GoogleOAuthError('temporary', retryable=True, retry_after_seconds=91)
assert classify_google_sync_failure(oauth) == ('transient', True, 91)
assert classify_google_sync_failure(GoogleOAuthError('credentials')) == ('authentication', False, None)
assert classify_google_sync_failure(GoogleApiError('rate', status_code=403, reason='userRateLimitExceeded', retryable=True))[:2] == ('transient', True)
assert classify_google_sync_failure(GoogleApiError('denied', api_status='PERMISSION_DENIED')) == ('permission', False, None)
assert parse_google_retry_after('91') == 91
assert parse_google_retry_after((datetime.now(UTC) + timedelta(seconds=30)).strftime('%a, %d %b %Y %H:%M:%S GMT')) is not None
"""
    run([*COMPOSE, "exec", "-T", "worker", "python3", "-c", code], sensitive=True)
    print("GOOGLE_RUNTIME_RETRY_POLICY_OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--expected-alembic", required=True)
    parser.add_argument("--observation-seconds", type=int, default=0)
    parser.add_argument("--origin-url", required=True)
    parser.add_argument("--health-url", required=True)
    args = parser.parse_args()
    try:
        require(Path.cwd().resolve() == REPOSITORY_PATH, "production verification must run in /opt/secretary")
        require(args.origin_url == "https://github.com/d-yacenko/secretary-prerelease.git", "unexpected Git origin contract")
        require(0 <= args.observation_seconds <= 360, "observation duration is out of bounds")
        require(run(["git", "remote", "get-url", "origin"]) == args.origin_url, "Git origin mismatch")
        require(run(["git", "status", "--porcelain"]) == "", "production checkout is not clean")
        run(["git", "fetch", "--prune", "origin"])
        require(run(["git", "rev-parse", "HEAD"]) == args.release_sha, "runtime release mismatch")
        require(run(["git", "rev-parse", "origin/production"]) == args.release_sha, "production ref mismatch")
        db, api, worker = (service_id(name) for name in ("db", "api", "worker"))
        require_running(db); require_running(api); require_running(worker)
        require(inspect(db, "{{.State.Health.Status}}") == "healthy", "database is not healthy")
        health_result = json.loads(run(["curl", "--fail", "--silent", args.health_url]))
        require(isinstance(health_result, dict) and health_result.get("status") == "ok", "API health failed")
        environment = resolved_environment()
        require_db_auth(db, environment["api"])
        current = run([*COMPOSE, "exec", "-T", "api", "alembic", "current"], sensitive=True)
        require(any(line.strip() == f"{args.expected_alembic} (head)" for line in current.splitlines()), "Alembic revision mismatch")
        assert_runtime(worker)
        type_list = "('sync_google_gmail','sync_google_calendar')"
        rows = query(db, environment["api"], f"SELECT type || '|' || status || '|' || count(*) FROM jobs WHERE type IN {type_list} GROUP BY type,status ORDER BY type,status")
        statuses: set[str] = set()
        for row in rows:
            parts = row.split("|")
            require(len(parts) == 3 and parts[0] in JOB_TYPES and parts[1] in {"pending", "running", "failed", "done"} and parts[2].isdigit(), "unexpected job aggregate")
            statuses.add(parts[1])
            print(f"GOOGLE_JOB_COUNT={parts[0]}:{parts[1]}:{parts[2]}")
        for status in ("pending", "running", "failed"):
            print(f"GOOGLE_JOBS_{status.upper()}={'true' if status in statuses else 'false'}")
        due = query(db, environment["api"], f"SELECT count(*) FROM jobs WHERE type IN {type_list} AND status='pending' AND run_after <= now() + interval '6 minutes'")[0]
        require(due.isdigit(), "unexpected due-job aggregate")
        print(f"GOOGLE_JOBS_DUE_WITHIN_6M={due}")
        observation_due = query(db, environment["api"], f"SELECT count(*) FROM jobs WHERE type IN {type_list} AND status='pending' AND run_after <= now() + interval '{args.observation_seconds} seconds'")[0]
        require(observation_due.isdigit(), "unexpected observation aggregate")
        if observation_due == "0":
            print("NATURAL_GOOGLE_OBSERVATION=NOT_AVAILABLE")
        else:
            deadline = time.monotonic() + args.observation_seconds
            while time.monotonic() < deadline:
                time.sleep(min(2, deadline - time.monotonic()))
            print("NATURAL_GOOGLE_OBSERVATION=DUE_AGGREGATE_ONLY")
        return 0
    except (VerificationError, OSError, ValueError, json.JSONDecodeError):
        print("GOOGLE_RUNTIME_VERIFICATION=FAILED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
