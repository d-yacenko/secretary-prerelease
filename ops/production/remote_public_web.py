#!/usr/bin/env python3
"""Publish branding pages into the existing static web root.

Streamed over verified SSH by public_web_rollout.py. It replaces only three
regular files under /var/www/web-itx and does not change the front-door server,
Docker, or Secretary runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_PATH = Path("/opt/secretary")
ENV_FILE = REPOSITORY_PATH / ".env"
STATIC_ROOT = Path("/var/www/web-itx")
CANONICAL_ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"
BRANDING_HOST = "web-itx.duckdns.org"
FILE_MODE = 0o644
DIRECTORY_MODE = 0o755
PAGE_FILES = {
    "index.html": "infra/public/index.html",
    "privacy/index.html": "infra/public/privacy.html",
    "terms/index.html": "infra/public/terms.html",
}
OWNED_PATHS = tuple(PAGE_FILES)
CREATED_DIRECTORIES = ("privacy", "terms")
VERIFY_URLS = (
    (f"https://{BRANDING_HOST}/", 200, "index.html"),
    (f"https://{BRANDING_HOST}/privacy", 200, "privacy/index.html"),
    (f"https://{BRANDING_HOST}/privacy/", 200, "privacy/index.html"),
    (f"https://{BRANDING_HOST}/terms", 200, "terms/index.html"),
    (f"https://{BRANDING_HOST}/terms/", 200, "terms/index.html"),
    (f"https://{BRANDING_HOST}/not-a-branding-page", 404, None),
)
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
MUTATING_COMPOSE = {"up", "stop", "rm", "down", "restart", "kill", "pause", "unpause"}
IDENTITY_KEYS = (
    "db_container",
    "db_volume",
    "env_checksum",
    "api_container",
    "worker_container",
)


class PublicWebError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileSnapshot:
    existed: bool
    data: bytes | None
    mode: int | None
    uid: int | None
    gid: int | None
    mtime_ns: int | None


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


def require_identities_unchanged(before: dict[str, str], after: dict[str, str]) -> None:
    for key in IDENTITY_KEYS:
        if not before.get(key) or before.get(key) != after.get(key):
            raise PublicWebError("db, api, worker, or env identity changed")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_pages(repository: Path) -> tuple[dict[str, bytes], dict[str, str]]:
    pages: dict[str, bytes] = {}
    for target, source in PAGE_FILES.items():
        pages[target] = (repository / source).read_bytes()
    return pages, page_manifest(pages)


def page_manifest(pages: dict[str, bytes]) -> dict[str, str]:
    if set(pages) != set(OWNED_PATHS):
        raise PublicWebError("unexpected branding path")
    return {rel: sha256_bytes(data) for rel, data in pages.items()}


def require_page_manifest(pages: dict[str, bytes], manifest: dict[str, str]) -> None:
    actual = page_manifest(pages)
    if actual != manifest:
        raise PublicWebError("branding source hash mismatch")


def verify_branding_responses(
    observed: dict[str, tuple[int, bytes]], pages: dict[str, bytes]
) -> None:
    for url, status, rel in VERIFY_URLS:
        got = observed.get(url)
        if got is None or got[0] != status:
            raise PublicWebError("public page verification failed")
        if rel is None:
            continue
        if sha256_bytes(got[1]) != sha256_bytes(pages[rel]):
            raise PublicWebError("public page verification failed")


def _owned_path(root: Path, relative: str) -> Path:
    if relative not in OWNED_PATHS:
        raise PublicWebError("unexpected branding path")
    path = root.joinpath(*relative.split("/"))
    if path.is_symlink():
        raise PublicWebError("refusing to replace a symlink")
    return path


def _snapshot(path: Path) -> FileSnapshot:
    if not path.exists():
        return FileSnapshot(False, None, None, None, None, None)
    if not path.is_file():
        raise PublicWebError("branding target is not a regular file")
    info = path.stat()
    return FileSnapshot(
        True,
        path.read_bytes(),
        info.st_mode & 0o777,
        info.st_uid,
        info.st_gid,
        info.st_mtime_ns,
    )


def _apply_owner(path: Path, uid: int, gid: int) -> None:
    try:
        os.chown(path, uid, gid)
    except PermissionError:
        if os.geteuid() == 0:
            raise


def _install(path: Path, data: bytes, uid: int, gid: int) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, FILE_MODE)
        _apply_owner(Path(temporary), uid, gid)
        os.replace(temporary, path)
    except Exception:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def _restore(path: Path, snapshot: FileSnapshot) -> None:
    if not snapshot.existed:
        if path.is_file() and not path.is_symlink():
            path.unlink()
        return
    assert snapshot.data is not None
    assert snapshot.mode is not None
    assert snapshot.uid is not None
    assert snapshot.gid is not None
    assert snapshot.mtime_ns is not None
    _install(path, snapshot.data, snapshot.uid, snapshot.gid)
    os.chmod(path, snapshot.mode)
    os.utime(path, ns=(snapshot.mtime_ns, snapshot.mtime_ns))


def publish_branding_files(
    root: Path,
    pages: dict[str, bytes],
    manifest: dict[str, str],
    *,
    verify,
    identity_after,
) -> None:
    require_page_manifest(pages, manifest)
    root = root.resolve()
    snapshots = {rel: _snapshot(_owned_path(root, rel)) for rel in OWNED_PATHS}
    template = snapshots["index.html"]
    if template.existed:
        uid, gid = template.uid, template.gid
    else:
        info = root.stat()
        uid, gid = info.st_uid, info.st_gid
    assert uid is not None and gid is not None
    created: list[Path] = []
    try:
        for name in CREATED_DIRECTORIES:
            directory = root / name
            if directory.is_symlink():
                raise PublicWebError("refusing to use a symlink directory")
            if directory.exists() and not directory.is_dir():
                raise PublicWebError("branding parent is not a directory")
            if not directory.exists():
                directory.mkdir(mode=DIRECTORY_MODE)
                created.append(directory)
        for rel, data in pages.items():
            _install(_owned_path(root, rel), data, uid, gid)
        identity_after()
        verify()
    except Exception:
        for rel in reversed(OWNED_PATHS):
            _restore(_owned_path(root, rel), snapshots[rel])
        for directory in reversed(created):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        raise


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
    if args and args[0] in MUTATING_COMPOSE:
        raise PublicWebError("static publisher must not mutate Docker or Compose")
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


def service_id(name: str) -> str:
    value = compose("ps", "-q", name).splitlines()
    container_id = value[0].strip() if value else ""
    if not container_id:
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


def fetch_public(url: str) -> tuple[int, bytes]:
    with tempfile.NamedTemporaryFile() as handle:
        code = run(
            [
                "curl",
                "-sS",
                "-o",
                handle.name,
                "-w",
                "%{http_code}",
                "--max-time",
                "20",
                url,
            ]
        )
        if not code.isdigit():
            raise PublicWebError("public page verification failed")
        return int(code), Path(handle.name).read_bytes()


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
    db_id = service_id("db")
    api_id = service_id("api")
    worker_id = service_id("worker")
    require_db_healthy(db_id)
    require_running(api_id, "api")
    require_running(worker_id, "worker")
    before = snapshot(db_id, api_id, worker_id)
    pages, manifest = load_pages(REPOSITORY_PATH)

    def identity_after() -> None:
        require_identities_unchanged(
            before,
            snapshot(service_id("db"), service_id("api"), service_id("worker")),
        )

    def verify() -> None:
        observed = {url: fetch_public(url) for url, _status, _rel in VERIFY_URLS}
        verify_branding_responses(observed, pages)

    publish_branding_files(
        STATIC_ROOT, pages, manifest, verify=verify, identity_after=identity_after
    )
    print("PUBLIC_WEB_HEALTH=PASS")
    print("DB_CONTAINER_UNCHANGED=true")
    print("DB_VOLUME_UNCHANGED=true")
    print("ENV_FILE_UNCHANGED=true")
    print("API_CONTAINER_UNCHANGED=true")
    print("WORKER_CONTAINER_UNCHANGED=true")
    print("PUBLIC_HOME=200")
    print("PUBLIC_PRIVACY=200")
    print("PUBLIC_PRIVACY_SLASH=200")
    print("PUBLIC_TERMS=200")
    print("PUBLIC_TERMS_SLASH=200")
    print("PUBLIC_UNRELATED=404")
    print("PUBLIC_WEB=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublicWebError as exc:
        print(f"PUBLIC_WEB_BLOCKED={exc}")
        raise SystemExit(2) from exc
