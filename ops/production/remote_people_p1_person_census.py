#!/usr/bin/env python3
"""Read-only production Person census. Streamed only by people_p1_person_census.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path("/opt/secretary")
CANONICAL_ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"
PRODUCTION_SHA = "296b4735f9473ea60ef22f1827ed94260603128e"
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(REPO / ".env"),
    "-f",
    "infra/compose.yaml",
    "-f",
    "infra/compose.deploy.yaml",
]
FACTS = (
    "PERSON_TOTAL",
    "PERSON_VISIBLE",
    "PERSON_WITH_EDGES",
    "PERSON_INCIDENT_EDGES",
    "PERSON_TASK_EDGES",
    "PERSON_FLOW_EDGES",
)
CENSUS_SQL = """
BEGIN TRANSACTION READ ONLY;
WITH visible AS (
    SELECT id
    FROM objects
    WHERE kind = 'person'
      AND deleted_at IS NULL
      AND (status IS NULL OR status <> 'deleted')
),
incident AS (
    SELECT DISTINCT e.id AS edge_id,
           CASE
               WHEN vs.id IS NOT NULL THEN e.target_id
               ELSE e.source_id
           END AS other_id
    FROM edges e
    LEFT JOIN visible vs ON vs.id = e.source_id
    LEFT JOIN visible vt ON vt.id = e.target_id
    WHERE vs.id IS NOT NULL OR vt.id IS NOT NULL
)
SELECT current_setting('transaction_read_only')
    || '|' || (SELECT count(*)::text FROM objects WHERE kind = 'person')
    || '|' || (SELECT count(*)::text FROM visible)
    || '|' || (
        SELECT count(*)::text FROM visible v
        WHERE EXISTS (
            SELECT 1 FROM edges e
            WHERE e.source_id = v.id OR e.target_id = v.id
        )
    )
    || '|' || (SELECT count(DISTINCT edge_id)::text FROM incident)
    || '|' || (
        SELECT count(*)::text
        FROM incident i
        JOIN objects o ON o.id = i.other_id
        WHERE o.kind = 'task'
    )
    || '|' || (
        SELECT count(*)::text
        FROM incident i
        JOIN objects o ON o.id = i.other_id
        WHERE o.kind <> 'person' AND o.kind <> 'task'
    );
COMMIT;
"""


class CensusError(RuntimeError):
    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__(stage)


def run(command: list[str], *, stdin: str | None = None) -> str:
    result = subprocess.run(
        command,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise CensusError("command")
    return result.stdout.strip()


def git(*args: str) -> str:
    return run(["git", *args])


def compose(*args: str, stdin: str | None = None) -> str:
    return run([*COMPOSE, *args], stdin=stdin)


def require_repository(expected_sha: str) -> None:
    if Path.cwd().resolve() != REPO:
        raise CensusError("cwd")
    if git("remote", "get-url", "origin") != CANONICAL_ORIGIN:
        raise CensusError("origin")
    if git("status", "--porcelain"):
        raise CensusError("worktree")
    if git("rev-parse", "HEAD") != expected_sha:
        raise CensusError("head")
    if git("rev-parse", "origin/production") != expected_sha:
        raise CensusError("production_ref")


def require_alembic_output(text: str) -> None:
    if not any(line.strip() == "0047 (head)" for line in text.splitlines()):
        raise CensusError("alembic")


def require_runtime(health_url: str) -> None:
    for service in ("db", "api", "worker"):
        container = compose("ps", "-q", service).strip()
        if not container:
            raise CensusError(f"{service}_running")
        state = run(["docker", "inspect", "-f", "{{.State.Running}}", container])
        if state != "true":
            raise CensusError(f"{service}_running")
    db = compose("ps", "-q", "db").strip()
    if run(["docker", "inspect", "-f", "{{.State.Health.Status}}", db]) != "healthy":
        raise CensusError("db_health")
    body = run(["curl", "-fsS", health_url]).replace(" ", "")
    if '"status":"ok"' not in body:
        raise CensusError("api_health")
    require_alembic_output(compose("exec", "-T", "api", "alembic", "current"))
    compose(
        "exec",
        "-T",
        "db",
        "sh",
        "-lc",
        'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "${POSTGRES_USER:-secretary}" '
        '-d "${POSTGRES_DB:-secretary}" -v ON_ERROR_STOP=1 -At -c "SELECT 1"',
    )


def parse_census_row(line: str) -> list[int]:
    parts = line.strip().split("|")
    if len(parts) != 7 or parts[0] != "on":
        raise CensusError("read_only")
    values: list[int] = []
    for part in parts[1:]:
        if not part.isdecimal():
            raise CensusError("census_output")
        values.append(int(part))
    return values


def run_census() -> list[int]:
    output = compose(
        "exec",
        "-T",
        "db",
        "sh",
        "-lc",
        'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 '
        '-U "${POSTGRES_USER:-secretary}" -d "${POSTGRES_DB:-secretary}" '
        "-v ON_ERROR_STOP=1 -At",
        stdin=CENSUS_SQL,
    )
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise CensusError("census_output")
    return parse_census_row(lines[0])


def emit_facts(values: list[int]) -> None:
    if len(values) != len(FACTS):
        raise CensusError("census_output")
    print("CENSUS_PREFLIGHT=pass", flush=True)
    print("CENSUS_READ_ONLY=on", flush=True)
    for key, value in zip(FACTS, values, strict=True):
        print(f"{key}={value}", flush=True)


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != PRODUCTION_SHA:
        print("CENSUS_BLOCKED=arguments", flush=True)
        return 1
    try:
        require_repository(sys.argv[1])
        require_runtime(sys.argv[2])
    except CensusError as exc:
        print(f"CENSUS_BLOCKED={exc.stage}", flush=True)
        return 1
    print("CENSUS_MARKER=started", flush=True)
    try:
        emit_facts(run_census())
    except CensusError as exc:
        print(f"CENSUS_BLOCKED={exc.stage}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
