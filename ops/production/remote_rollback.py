#!/usr/bin/env python3
"""Explicit production application rollback; never changes database state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path("/opt/secretary")
ENV_FILE = ROOT / ".env"
COMPOSE = ["docker", "compose", "--env-file", str(ENV_FILE), "-f", "infra/compose.yaml", "-f", "infra/compose.deploy.yaml"]


class RollbackError(RuntimeError):
    pass


def run(command: list[str], *, sensitive: bool = False) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RollbackError("production rollback command failed")
    return result.stdout.strip()


def compose(*args: str) -> str:
    return run([*COMPOSE, *args])


def require(value: bool, message: str) -> None:
    if not value:
        raise RollbackError(message)


def service_id(service: str) -> str:
    value = compose("ps", "-q", service)
    require(bool(value), "required production container is missing")
    return value.splitlines()[0].strip()


def inspect(container: str, template: str) -> str:
    return run(["docker", "inspect", "--format", template, container])


def environment() -> dict[str, str]:
    data = json.loads(compose("config", "--format", "json"))
    values = data.get("services", {}).get("api", {}).get("environment", {})
    if isinstance(values, list):
        values = dict(item.split("=", 1) for item in values if "=" in item)
    require(isinstance(values, dict), "application environment unavailable")
    result = {str(k): str(v) for k, v in values.items()}
    require(result.get("POSTGRES_PASSWORD", "") != "", "database password unavailable")
    require(result.get("SECRETARY_CREDENTIAL_KEY", "") != "", "credential key unavailable")
    return result


def db_auth(db: str, env: dict[str, str]) -> None:
    child_environment = os.environ.copy()
    child_environment["PGPASSWORD"] = env["POSTGRES_PASSWORD"]
    command = ["docker", "exec", "-e", "PGPASSWORD", db, "psql", "-U",
               env.get("POSTGRES_USER", "secretary"), "-d", env.get("POSTGRES_DB", "secretary"),
               "-h", "127.0.0.1", "-tAc", "SELECT 1"]
    result = subprocess.run(command, text=True, capture_output=True, check=False, env=child_environment)
    require(result.returncode == 0 and result.stdout.strip() == "1", "database authentication failed")


def health(url: str) -> None:
    result = json.loads(run(["curl", "--fail", "--silent", url]))
    require(isinstance(result, dict) and result.get("status") == "ok", "API health failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--rollback-sha", required=True)
    parser.add_argument("--expected-alembic", required=True)
    parser.add_argument("--origin-url", required=True)
    parser.add_argument("--health-url", required=True)
    args = parser.parse_args()
    try:
        require(Path.cwd().resolve() == ROOT, "rollback must run in /opt/secretary")
        require(args.origin_url == "https://github.com/d-yacenko/secretary-prerelease.git", "unexpected Git origin contract")
        require(run(["git", "remote", "get-url", "origin"]) == args.origin_url, "Git origin mismatch")
        require(run(["git", "status", "--porcelain"]) == "", "production checkout is not clean")
        run(["git", "fetch", "--prune", "origin"])
        require(run(["git", "rev-parse", "origin/production"]) == args.release_sha, "production ref mismatch")
        require(run(["git", "rev-parse", "HEAD"]) == args.release_sha, "runtime release mismatch")
        db, api, worker = (service_id(name) for name in ("db", "api", "worker"))
        require(inspect(db, "{{.State.Status}}") == "running", "database is not running")
        require(inspect(db, "{{.State.Health.Status}}") == "healthy", "database is not healthy")
        api_state = inspect(api, "{{.State.Status}}")
        worker_state = inspect(worker, "{{.State.Status}}")
        require(api_state == "running", "api is not running")
        require(worker_state == "running", "worker is not running")
        volume = inspect(db, "{{range .Mounts}}{{.Name}}={{.Destination}};{{end}}")
        env_hash = hashlib.sha256(ENV_FILE.read_bytes()).hexdigest()
        env = environment(); db_auth(db, env); health(args.health_url)
        before = (db, volume, env_hash)
        run(["git", "switch", "--detach", args.rollback_sha])
        compose("build", "api", "worker")
        compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")
        require(run(["git", "rev-parse", "HEAD"]) == args.rollback_sha, "rollback checkout mismatch")
        require(service_id("db") == before[0], "database container changed")
        require(inspect(before[0], "{{range .Mounts}}{{.Name}}={{.Destination}};{{end}}") == before[1], "database volume changed")
        require(hashlib.sha256(ENV_FILE.read_bytes()).hexdigest() == before[2], "environment file changed")
        require(inspect(service_id("api"), "{{.State.Status}}") == "running", "api is not running after rollback")
        require(inspect(service_id("worker"), "{{.State.Status}}") == "running", "worker is not running after rollback")
        health(args.health_url)
        current = compose("exec", "-T", "api", "alembic", "current")
        require(any(line.strip() == f"{args.expected_alembic} (head)" for line in current.splitlines()), "Alembic revision mismatch")
        print("ROLLBACK=PASS")
        return 0
    except (RollbackError, OSError, ValueError, json.JSONDecodeError):
        print("ROLLBACK=FAILED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
