#!/usr/bin/env python3
"""Remote half of the production deployment contract.

The local deploy.py streams this file over verified SSH. It prints only
non-secret deployment facts and booleans.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPOSITORY_PATH = Path("/opt/secretary")
ENV_FILE = REPOSITORY_PATH / ".env"
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(ENV_FILE),
    "-f",
    "infra/compose.yaml",
    "-f",
    "infra/compose.deploy.yaml",
]


class DeployError(RuntimeError):
    pass


def run(
    cmd: list[str],
    *,
    sensitive: bool = False,
    env: dict[str, str] | None = None,
) -> str:
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        if sensitive:
            raise DeployError("sensitive preflight command failed")
        message = (proc.stderr or proc.stdout or "command failed").strip().splitlines()
        tail = message[-1][:300] if message else "command failed"
        raise DeployError(tail)
    return proc.stdout.strip()


def git(*args: str) -> str:
    return run(["git", *args])


def compose(*args: str, sensitive: bool = False) -> str:
    return run([*COMPOSE, *args], sensitive=sensitive)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_json(container_id: str) -> dict:
    payload = run(["docker", "inspect", container_id])
    rows = json.loads(payload)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise DeployError("unexpected docker inspect result")
    return rows[0]


def volume_identity(container_id: str) -> tuple[str, str, str, str]:
    info = inspect_json(container_id)
    mounts = info.get("Mounts") or []
    for mount in mounts:
        if mount.get("Destination") == "/var/lib/postgresql/data":
            return (
                str(mount.get("Type") or ""),
                str(mount.get("Name") or ""),
                str(mount.get("Source") or ""),
                str(mount.get("Destination") or ""),
            )
    raise DeployError("production DB volume mount not found")


def require_running(container_id: str, service_name: str) -> None:
    state = inspect_json(container_id).get("State") or {}
    if state.get("Running") is not True:
        raise DeployError(f"production {service_name} container is not running")


def require_db_healthy(container_id: str) -> None:
    require_running(container_id, "db")
    state = inspect_json(container_id).get("State") or {}
    health = state.get("Health") or {}
    if health and health.get("Status") != "healthy":
        raise DeployError("production DB container is not healthy")


def service_id(name: str) -> str:
    value = compose("ps", "-q", name)
    if not value:
        raise DeployError(f"production service missing: {name}")
    return value.splitlines()[0].strip()


def normalized_environment(service: dict) -> dict[str, str]:
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return {str(k): "" if v is None else str(v) for k, v in env.items()}
    if isinstance(env, list):
        result: dict[str, str] = {}
        for item in env:
            text = str(item)
            key, sep, value = text.partition("=")
            result[key] = value if sep else ""
        return result
    raise DeployError("unexpected Compose environment format")


def resolved_app_environment() -> tuple[dict[str, str], dict[str, str]]:
    raw = compose("config", "--format", "json", sensitive=True)
    config = json.loads(raw)
    services = config.get("services") or {}
    api = services.get("api")
    worker = services.get("worker")
    if not isinstance(api, dict) or not isinstance(worker, dict):
        raise DeployError("api/worker missing from Compose resolution")
    return normalized_environment(api), normalized_environment(worker)


def require_environment(api: dict[str, str], worker: dict[str, str]) -> None:
    required_nonempty = ("POSTGRES_PASSWORD", "SECRETARY_CREDENTIAL_KEY")
    for service_name, env in (("api", api), ("worker", worker)):
        for key in required_nonempty:
            if not env.get(key):
                raise DeployError(f"{service_name} required environment is empty: {key}")
    for key in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "SECRETARY_CREDENTIAL_KEY",
    ):
        if api.get(key) != worker.get(key):
            raise DeployError(f"api/worker environment mismatch: {key}")


def require_db_tcp_auth(db_id: str, api_env: dict[str, str]) -> None:
    password = api_env["POSTGRES_PASSWORD"]
    user = api_env.get("POSTGRES_USER") or "secretary"
    database = api_env.get("POSTGRES_DB") or "secretary"
    child_env = dict(os.environ)
    child_env["PGPASSWORD"] = password
    output = run(
        [
            "docker",
            "exec",
            "-e",
            "PGPASSWORD",
            db_id,
            "psql",
            "-h",
            "127.0.0.1",
            "-U",
            user,
            "-d",
            database,
            "-tAc",
            "SELECT 1",
        ],
        sensitive=True,
        env=child_env,
    )
    if output.strip() != "1":
        raise DeployError("production DB TCP authentication probe failed")


def require_health(url: str, *, attempts: int = 1) -> None:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            run(["curl", "--fail", "--silent", url])
            return
        except DeployError as exc:
            last_error = exc
            time.sleep(2)
    raise DeployError("production health check failed") from last_error


def require_alembic(expected: str) -> None:
    current = compose("exec", "-T", "api", "alembic", "current")
    if f"{expected} (head)" not in current:
        raise DeployError("unexpected production Alembic revision")


def rollback(
    rollback_sha: str,
    expected_alembic: str,
    health_url: str,
    db_id: str,
    db_volume: tuple[str, str, str, str],
    env_hash: str,
) -> bool:
    try:
        git("switch", "--detach", rollback_sha)
        compose("build", "api", "worker")
        compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")
        if service_id("db") != db_id:
            raise DeployError("DB container changed during rollback")
        if volume_identity(db_id) != db_volume:
            raise DeployError("DB volume changed during rollback")
        if file_sha256(ENV_FILE) != env_hash:
            raise DeployError("environment file changed during rollback")
        require_health(health_url, attempts=30)
        require_alembic(expected_alembic)
        return True
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--rollback-sha", required=True)
    parser.add_argument("--expected-alembic", required=True)
    parser.add_argument("--origin-url", required=True)
    parser.add_argument("--health-url", required=True)
    args = parser.parse_args()

    if Path.cwd().resolve() != REPOSITORY_PATH:
        raise DeployError("wrong production working directory")
    if git("remote", "get-url", "origin") != args.origin_url:
        raise DeployError("wrong production Git origin")
    if git("status", "--porcelain"):
        raise DeployError("production checkout is not clean")
    if not ENV_FILE.is_file():
        raise DeployError("production environment file missing")

    git("fetch", "--prune", "origin")
    if git("rev-parse", "origin/production") != args.release_sha:
        raise DeployError("origin/production does not equal authorized release")
    current_head = git("rev-parse", "HEAD")
    if current_head not in {args.rollback_sha, args.release_sha}:
        raise DeployError("unexpected current production checkout SHA")

    db_id = service_id("db")
    api_id = service_id("api")
    worker_id = service_id("worker")
    require_db_healthy(db_id)
    require_running(api_id, "api")
    require_running(worker_id, "worker")
    require_health(args.health_url)
    db_volume = volume_identity(db_id)
    env_hash = file_sha256(ENV_FILE)

    api_env, worker_env = resolved_app_environment()
    require_environment(api_env, worker_env)
    require_db_tcp_auth(db_id, api_env)

    recreated = False
    original_head = current_head
    try:
        git("switch", "--detach", args.release_sha)
        if git("rev-parse", "HEAD") != args.release_sha or git("status", "--porcelain"):
            raise DeployError("failed to select clean authorized release")

        compose("build", "api", "worker")
        recreated = True
        compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")

        if service_id("db") != db_id:
            raise DeployError("DB container changed during application rollout")
        if volume_identity(db_id) != db_volume:
            raise DeployError("DB volume changed during application rollout")
        if file_sha256(ENV_FILE) != env_hash:
            raise DeployError("production environment file changed during rollout")
        new_api_id = service_id("api")
        new_worker_id = service_id("worker")
        if new_api_id == api_id or new_worker_id == worker_id:
            raise DeployError("api/worker were not both recreated")
        require_health(args.health_url, attempts=30)
        require_alembic(args.expected_alembic)

        print(f"RELEASE_HEAD={args.release_sha}")
        print("HEALTH=PASS")
        print(f"ALEMBIC={args.expected_alembic}")
        print("DB_CONTAINER_UNCHANGED=true")
        print("DB_VOLUME_UNCHANGED=true")
        print("ENV_FILE_UNCHANGED=true")
        print("API_RECREATED=true")
        print("WORKER_RECREATED=true")
        print("DEPLOYMENT=PASS")
        return 0
    except Exception as exc:
        print(f"DEPLOYMENT=FAILED:{type(exc).__name__}", file=sys.stderr)
        if recreated:
            ok = rollback(
                args.rollback_sha,
                args.expected_alembic,
                args.health_url,
                db_id,
                db_volume,
                env_hash,
            )
            print(f"ROLLBACK={'PASS' if ok else 'FAILED'}", file=sys.stderr)
        else:
            try:
                git("switch", "--detach", original_head)
            except Exception:
                print("CHECKOUT_RESTORE=FAILED", file=sys.stderr)
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DeployError as exc:
        print(f"DEPLOYMENT_BLOCKED={exc}", file=sys.stderr)
        raise SystemExit(2)
