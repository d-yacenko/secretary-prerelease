#!/usr/bin/env python3
"""Remote migration-bearing rollout; streamed only by migrate_deploy.py."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path("/opt/secretary")
ENV = REPO / ".env"
COMPOSE = ["docker", "compose", "--env-file", str(ENV), "-f", "infra/compose.yaml", "-f", "infra/compose.deploy.yaml"]
MTPROTO_TABLES = (
    "telegram_mtproto_accounts",
    "telegram_mtproto_auth_challenges",
    "telegram_mtproto_chat_selections",
    "telegram_mtproto_sync_folders",
)


class DeployError(RuntimeError):
    pass


RECOVERABLE_ERRORS = (DeployError, OSError, ValueError, subprocess.SubprocessError)


def run(cmd: list[str], *, env: dict[str, str] | None = None, sensitive: bool = False) -> str:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False, env=env)
    if proc.returncode:
        if sensitive:
            raise DeployError("sensitive preflight failed")
        raise DeployError("remote command failed")
    return proc.stdout.strip()


def git(*args: str) -> str:
    return run(["git", *args])


def compose(*args: str, sensitive: bool = False) -> str:
    return run([*COMPOSE, *args], sensitive=sensitive)


def inspect_json(container: str) -> dict:
    data = json.loads(run(["docker", "inspect", container]))
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise DeployError("unexpected container inspection")
    return data[0]


def service_id(name: str) -> str:
    result = compose("ps", "-q", name)
    if not result:
        raise DeployError(f"missing service: {name}")
    return result.splitlines()[0]


def running(container: str) -> bool:
    return (inspect_json(container).get("State") or {}).get("Running") is True


def require_stopped(api: str, worker: str) -> None:
    if running(api) or running(worker):
        raise DeployError("api/worker did not stop before migration")


def stop_applications(api: str, worker: str) -> None:
    compose("stop", "api", "worker")
    require_stopped(api, worker)


def require_db(container: str) -> None:
    state = inspect_json(container).get("State") or {}
    if state.get("Running") is not True or (state.get("Health") or {}).get("Status") != "healthy":
        raise DeployError("database is not running and healthy")


def volume(container: str) -> tuple[str, str, str]:
    for mount in inspect_json(container).get("Mounts") or []:
        if mount.get("Destination") == "/var/lib/postgresql/data":
            return (str(mount.get("Type") or ""), str(mount.get("Name") or ""), str(mount.get("Source") or ""))
    raise DeployError("database volume is missing")


def env_hash() -> str:
    return hashlib.sha256(ENV.read_bytes()).hexdigest()


def resolved_environment() -> tuple[dict[str, str], dict[str, str]]:
    data = json.loads(compose("config", "--format", "json", sensitive=True))
    services = data.get("services") or {}
    result = []
    for name in ("api", "worker"):
        service = services.get(name)
        if not isinstance(service, dict):
            raise DeployError("api/worker missing from Compose")
        values = service.get("environment") or {}
        if isinstance(values, dict):
            result.append({str(k): "" if v is None else str(v) for k, v in values.items()})
        else:
            raise DeployError("unexpected Compose environment")
    return result[0], result[1]


def require_environment(api: dict[str, str], worker: dict[str, str], *, require_telegram: bool) -> None:
    for name, values in (("api", api), ("worker", worker)):
        if not values.get("POSTGRES_PASSWORD") or not values.get("SECRETARY_CREDENTIAL_KEY"):
            raise DeployError(f"{name} required environment is empty")
        if require_telegram and (
            not values.get("TELEGRAM_API_HASH")
            or not values.get("TELEGRAM_API_ID", "").isdigit()
            or int(values["TELEGRAM_API_ID"]) <= 0
        ):
            raise DeployError(f"{name} Telegram credentials are unavailable")
    for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "SECRETARY_CREDENTIAL_KEY"):
        if api.get(key) != worker.get(key):
            raise DeployError("api/worker environment mismatch")


def require_release_environment(
    rollback_api: dict[str, str],
    rollback_worker: dict[str, str],
    release_api: dict[str, str],
    release_worker: dict[str, str],
) -> None:
    require_environment(release_api, release_worker, require_telegram=True)
    for key in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "SECRETARY_CREDENTIAL_KEY",
    ):
        if release_api.get(key) != rollback_api.get(key) or release_worker.get(key) != rollback_worker.get(key):
            raise DeployError("release environment changes DB or credential settings")


def db_auth(db: str, values: dict[str, str]) -> None:
    child = dict(os.environ)
    child["PGPASSWORD"] = values["POSTGRES_PASSWORD"]
    output = run(["docker", "exec", "-e", "PGPASSWORD", db, "psql", "-h", "127.0.0.1", "-U", values.get("POSTGRES_USER", "secretary"), "-d", values.get("POSTGRES_DB", "secretary"), "-tAc", "SELECT 1"], env=child, sensitive=True)
    if output != "1":
        raise DeployError("database TCP authentication failed")


def require_db_revision(db: str, values: dict[str, str], expected: str) -> None:
    child = dict(os.environ)
    child["PGPASSWORD"] = values["POSTGRES_PASSWORD"]
    output = run(
        [
            "docker",
            "exec",
            "-e",
            "PGPASSWORD",
            db,
            "psql",
            "-h",
            "127.0.0.1",
            "-U",
            values.get("POSTGRES_USER", "secretary"),
            "-d",
            values.get("POSTGRES_DB", "secretary"),
            "-tAc",
            "SELECT version_num FROM alembic_version",
        ],
        env=child,
        sensitive=True,
    )
    revisions = [line.strip() for line in output.splitlines() if line.strip()]
    if len(revisions) != 1 or revisions[0] != expected:
        raise DeployError("unexpected database Alembic revision")


def health(url: str) -> None:
    run(["curl", "--fail", "--silent", url])


def mtproto_empty(db: str, values: dict[str, str]) -> bool:
    child = dict(os.environ)
    child["PGPASSWORD"] = values["POSTGRES_PASSWORD"]
    for table in MTPROTO_TABLES:
        try:
            result = run(["docker", "exec", "-e", "PGPASSWORD", db, "psql", "-h", "127.0.0.1", "-U", values.get("POSTGRES_USER", "secretary"), "-d", values.get("POSTGRES_DB", "secretary"), "-tAc", f"SELECT count(*) FROM {table}"], env=child, sensitive=True)
        except Exception as exc:
            raise DeployError("unable to prove MTProto tables are empty") from exc
        if result != "0":
            return False
    return True


def restore_old(
    rollback: str,
    expected: str,
    url: str,
    db: str,
    db_values: dict[str, str],
    db_volume: tuple[str, str, str],
    before_env: str,
    api: str,
    worker: str,
) -> bool:
    try:
        git("switch", "--detach", rollback)
        compose("build", "api", "worker")
        compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")
        if service_id("db") != db or volume(db) != db_volume or env_hash() != before_env:
            return False
        if service_id("api") == api or service_id("worker") == worker:
            return False
        require_db(db)
        health(url)
        require_db_revision(db, db_values, expected)
        return True
    except RECOVERABLE_ERRORS:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--rollback-sha", required=True)
    parser.add_argument("--from-alembic", required=True)
    parser.add_argument("--to-alembic", required=True)
    parser.add_argument("--origin-url", required=True)
    parser.add_argument("--health-url", required=True)
    args = parser.parse_args()
    if Path.cwd().resolve() != REPO or args.from_alembic != "0041" or args.to_alembic != "0046":
        raise DeployError("migration deployment preflight rejected")
    if git("remote", "get-url", "origin") != args.origin_url or git("status", "--porcelain"):
        raise DeployError("production Git identity or cleanliness check failed")
    if not ENV.is_file():
        raise DeployError("production environment file missing")
    git("fetch", "--prune", "origin")
    if git("rev-parse", "origin/production") != args.release_sha:
        raise DeployError("production ref is not the authorized release")
    current = git("rev-parse", "HEAD")
    if current != args.rollback_sha:
        raise DeployError("migration rollout requires the exact rollback runtime")
    db = service_id("db")
    api = service_id("api")
    worker = service_id("worker")
    require_db(db)
    if not running(api) or not running(worker):
        raise DeployError("api/worker are not running")
    health(args.health_url)
    before_volume = volume(db)
    before_env = env_hash()
    api_env, worker_env = resolved_environment()
    require_environment(api_env, worker_env, require_telegram=False)
    db_auth(db, api_env)
    require_db_revision(db, api_env, args.from_alembic)

    stopped = False
    migration_started = False
    live = False
    try:
        git("switch", "--detach", args.release_sha)
        release_api_env, release_worker_env = resolved_environment()
        require_release_environment(api_env, worker_env, release_api_env, release_worker_env)
        compose("build", "api", "worker")
        if service_id("db") != db or volume(db) != before_volume or env_hash() != before_env:
            raise DeployError("database or environment changed before downtime")
        stopped = True
        stop_applications(api, worker)
        require_db(db)
        if service_id("db") != db or volume(db) != before_volume or env_hash() != before_env:
            raise DeployError("database or environment changed during downtime")
        migration_started = True
        compose("run", "--rm", "--no-deps", "api", "alembic", "upgrade", args.to_alembic)
        require_db_revision(db, release_api_env, args.to_alembic)
        live = True
        compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker")
        if service_id("db") != db or volume(db) != before_volume or env_hash() != before_env:
            raise DeployError("database or environment changed after cutover")
        if service_id("api") == api or service_id("worker") == worker or not running(service_id("api")) or not running(service_id("worker")):
            raise DeployError("release application containers are not recreated and running")
        health(args.health_url)
        require_db_revision(db, release_api_env, args.to_alembic)
        print("MIGRATION_DEPLOYMENT=PASS")
        print("ALEMBIC=0046")
        print("DB_CONTAINER_UNCHANGED=true")
        print("DB_VOLUME_UNCHANGED=true")
        print("ENV_FILE_UNCHANGED=true")
        print("API_RECREATED=true")
        print("WORKER_RECREATED=true")
        return 0
    except RECOVERABLE_ERRORS as exc:
        if stopped:
            if live:
                try:
                    compose("stop", "api", "worker")
                    if not mtproto_empty(db, api_env):
                        print("MIGRATION_ROLLBACK_BLOCKED=post_cutover_mtproto_data", file=sys.stderr)
                        print("BREAK_GLASS_REQUIRED=true", file=sys.stderr)
                        return 2
                except RECOVERABLE_ERRORS:
                    print("MIGRATION_ROLLBACK_BLOCKED=post_cutover_mtproto_data", file=sys.stderr)
                    print("BREAK_GLASS_REQUIRED=true", file=sys.stderr)
                    return 2
            if migration_started:
                try:
                    compose("run", "--rm", "--no-deps", "api", "alembic", "downgrade", args.from_alembic)
                    require_db_revision(db, api_env, args.from_alembic)
                except RECOVERABLE_ERRORS:
                    print("MIGRATION_ROLLBACK=FAILED", file=sys.stderr)
                    return 2
            ok = restore_old(
                args.rollback_sha,
                args.from_alembic,
                args.health_url,
                db,
                api_env,
                before_volume,
                before_env,
                api,
                worker,
            )
            print(f"MIGRATION_ROLLBACK={'PASS' if ok else 'FAILED'}", file=sys.stderr)
            return 0 if ok else 2
        try:
            git("switch", "--detach", args.rollback_sha)
        except RECOVERABLE_ERRORS:
            print("CHECKOUT_RESTORE=FAILED", file=sys.stderr)
        print(f"MIGRATION_DEPLOYMENT=FAILED:{type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DeployError as exc:
        print(f"MIGRATION_DEPLOYMENT_BLOCKED={exc}", file=sys.stderr)
        raise SystemExit(2)
