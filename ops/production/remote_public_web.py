#!/usr/bin/env python3
"""Remote half of the public branding-site rollout.

Streamed over verified SSH by public_web_rollout.py. It may recreate only the
public_web Compose service. It does not move Git refs or print secrets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

REPOSITORY_PATH = Path("/opt/secretary")
ENV_FILE = REPOSITORY_PATH / ".env"
CANONICAL_ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"
BRANDING_HOST = "web-itx.duckdns.org"
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
PUBLIC_WEB_UP = ("up", "-d", "--no-deps", "--force-recreate", "public_web")
IDENTITY_KEYS = (
    "db_container",
    "db_volume",
    "env_checksum",
    "api_container",
    "worker_container",
)
PUBLIC_URLS = {
    f"https://{BRANDING_HOST}/": 200,
    f"https://{BRANDING_HOST}/privacy": 200,
    f"https://{BRANDING_HOST}/terms": 200,
    f"https://{BRANDING_HOST}/not-a-branding-page": 404,
}


class PublicWebError(RuntimeError):
    pass


def require_remote_release(
    *,
    repository_path: str,
    origin_url: str,
    expected_origin: str,
    head: str,
    origin_production: str,
    release_sha: str,
) -> None:
    if repository_path != str(REPOSITORY_PATH):
        raise PublicWebError("unexpected production repository_path")
    if origin_url != CANONICAL_ORIGIN or expected_origin != CANONICAL_ORIGIN:
        raise PublicWebError("unexpected production origin")
    if head != release_sha or origin_production != release_sha:
        raise PublicWebError("production ref does not equal authorized release")


def occupied_public_ports(ss_output: str) -> set[int]:
    found: set[int] = set()
    for line in ss_output.splitlines():
        for token in line.split():
            if token.endswith((":80", "]:80")):
                found.add(80)
            if token.endswith((":443", "]:443")):
                found.add(443)
    return found


def require_ports_free_for_first_rollout(
    *, service_exists: bool, listeners: set[int]
) -> None:
    if service_exists:
        return
    occupied = listeners & {80, 443}
    if occupied:
        raise PublicWebError("public web ports already occupied")


def require_identities_unchanged(before: dict[str, str], after: dict[str, str]) -> None:
    for key in IDENTITY_KEYS:
        if not before.get(key) or before.get(key) != after.get(key):
            raise PublicWebError("db, api, worker, or env identity changed")


def require_public_statuses(statuses: dict[str, int]) -> None:
    for url, expected in PUBLIC_URLS.items():
        if statuses.get(url) != expected:
            raise PublicWebError("public page verification failed")


def must_remove_new_public_web(*, existed_before: bool, verified: bool) -> bool:
    return (not existed_before) and (not verified)


def run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "command failed").strip().splitlines()
        tail = message[-1][:300] if message else "command failed"
        raise PublicWebError(tail)
    return proc.stdout.strip()


def git(*args: str) -> str:
    return run(["git", *args])


def compose(*args: str) -> str:
    if args[:1] == ("up",) and args[-1:] != ("public_web",):
        raise PublicWebError("public web rollout may start only public_web")
    return run([*COMPOSE, *args])


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_json(container_id: str) -> dict:
    rows = json.loads(run(["docker", "inspect", container_id]))
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise PublicWebError("unexpected docker inspect result")
    return rows[0]


def require_running(container_id: str, service_name: str) -> None:
    state = inspect_json(container_id).get("State") or {}
    if state.get("Running") is not True:
        raise PublicWebError(f"production {service_name} container is not running")


def require_db_healthy(container_id: str) -> None:
    require_running(container_id, "db")
    health = (inspect_json(container_id).get("State") or {}).get("Health") or {}
    if health and health.get("Status") != "healthy":
        raise PublicWebError("production DB container is not healthy")


def service_id(name: str, *, required: bool) -> str:
    value = compose("ps", "-q", name).splitlines()
    container_id = value[0].strip() if value else ""
    if required and not container_id:
        raise PublicWebError(f"production service missing: {name}")
    return container_id


def db_volume_identity(container_id: str) -> str:
    mounts = inspect_json(container_id).get("Mounts") or []
    for mount in mounts:
        if mount.get("Destination") == "/var/lib/postgresql/data":
            return "|".join(
                str(mount.get(key) or "")
                for key in ("Type", "Name", "Source", "Destination")
            )
    raise PublicWebError("production DB volume mount not found")


def snapshot(db_id: str, api_id: str, worker_id: str) -> dict[str, str]:
    return {
        "db_container": db_id,
        "db_volume": db_volume_identity(db_id),
        "env_checksum": file_sha256(ENV_FILE),
        "api_container": api_id,
        "worker_container": worker_id,
    }


def require_health(url: str) -> None:
    code = run(
        [
            "curl",
            "-fsS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "10",
            url,
        ]
    )
    if code != "200":
        raise PublicWebError("production API health check failed")


def http_status(url: str) -> int:
    code = run(
        [
            "curl",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "20",
            url,
        ]
    )
    if not code.isdigit():
        raise PublicWebError("public page verification failed")
    return int(code)


def collect_statuses() -> dict[str, int]:
    deadline = time.monotonic() + 45
    last: dict[str, int] = {}
    while True:
        last = {url: http_status(url) for url in PUBLIC_URLS}
        try:
            require_public_statuses(last)
            return last
        except PublicWebError:
            if time.monotonic() >= deadline:
                return last
            time.sleep(3)


def remove_public_web() -> None:
    compose("stop", "public_web")
    compose("rm", "-sf", "public_web")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--origin-url", required=True)
    parser.add_argument("--health-url", required=True)
    args = parser.parse_args()
    release_sha = args.release_sha.strip().lower()

    head = git("rev-parse", "HEAD")
    origin_production = git("rev-parse", "origin/production")
    origin_url = git("remote", "get-url", "origin")
    require_remote_release(
        repository_path=str(Path.cwd()),
        origin_url=origin_url,
        expected_origin=args.origin_url,
        head=head,
        origin_production=origin_production,
        release_sha=release_sha,
    )
    require_health(args.health_url)

    db_id = service_id("db", required=True)
    api_id = service_id("api", required=True)
    worker_id = service_id("worker", required=True)
    require_db_healthy(db_id)
    require_running(api_id, "api")
    require_running(worker_id, "worker")
    before = snapshot(db_id, api_id, worker_id)

    existed_before = bool(service_id("public_web", required=False))
    listeners = occupied_public_ports(run(["ss", "-ltn"]))
    require_ports_free_for_first_rollout(
        service_exists=existed_before, listeners=listeners
    )

    compose(*PUBLIC_WEB_UP)
    after_ids = (
        service_id("db", required=True),
        service_id("api", required=True),
        service_id("worker", required=True),
    )
    after = snapshot(*after_ids)
    require_identities_unchanged(before, after)
    if not service_id("public_web", required=True):
        raise PublicWebError("public_web is not running")
    require_running(service_id("public_web", required=True), "public_web")

    statuses = collect_statuses()
    try:
        require_public_statuses(statuses)
    except PublicWebError:
        if must_remove_new_public_web(existed_before=existed_before, verified=False):
            remove_public_web()
        raise

    print("PUBLIC_WEB_HEALTH=PASS")
    print("DB_CONTAINER_UNCHANGED=true")
    print("DB_VOLUME_UNCHANGED=true")
    print("ENV_FILE_UNCHANGED=true")
    print("API_CONTAINER_UNCHANGED=true")
    print("WORKER_CONTAINER_UNCHANGED=true")
    print("PUBLIC_WEB_RUNNING=true")
    print("PUBLIC_HOME=200")
    print("PUBLIC_PRIVACY=200")
    print("PUBLIC_TERMS=200")
    print("PUBLIC_UNRELATED=404")
    print("PUBLIC_WEB=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublicWebError as exc:
        print(f"PUBLIC_WEB_BLOCKED={exc}")
        raise SystemExit(2) from exc
