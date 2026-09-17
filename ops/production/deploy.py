#!/usr/bin/env python3
"""Fail-closed production deployment entrypoint.

This script is run from the canonical, clean Executor `main` checkout. It never
discovers a host: the exact SSH target and expected host-key fingerprint come
from target.json.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parent.parent
TARGET_FILE = HERE / "target.json"
REMOTE_HELPER = HERE / "remote_deploy.py"
CANONICAL_ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
MIGRATION_PATHS = (
    "backend/alembic/versions/",
    "backend/alembic/env.py",
    "backend/alembic.ini",
    "backend/alembic/script.py.mako",
)


class DeployError(RuntimeError):
    pass


def _run_local(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "command failed").strip().splitlines()
        tail = message[-1][:300] if message else "command failed"
        raise DeployError(tail)
    return proc.stdout.strip()


def _require_canonical_local_checkout() -> None:
    root = _run_local(["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "--show-toplevel"])
    if Path(root).resolve() != REPOSITORY_ROOT.resolve():
        raise DeployError("deployment harness is not running from the canonical repository root")
    origin = _run_local(["git", "-C", str(REPOSITORY_ROOT), "remote", "get-url", "origin"])
    if origin != CANONICAL_ORIGIN:
        raise DeployError("local deployment checkout has the wrong Git origin")
    if _run_local(["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain"]):
        raise DeployError("local deployment checkout is not clean")
    branch = _run_local(["git", "-C", str(REPOSITORY_ROOT), "branch", "--show-current"])
    if branch != "main":
        raise DeployError("normal production deployment must run from local main")

    _run_local(["git", "-C", str(REPOSITORY_ROOT), "fetch", "--prune", "origin", "main"])
    head = _run_local(["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"])
    remote_main = _run_local(["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "origin/main"])
    if head != remote_main:
        raise DeployError("local main is stale; fast-forward it to origin/main before deployment")


def _load_target() -> dict:
    data = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    required = {
        "ssh_target",
        "ssh_port",
        "host_key_sha256",
        "repository_path",
        "origin_url",
        "health_url",
        "compose_files",
    }
    missing = sorted(required - data.keys())
    if missing:
        raise DeployError(f"target.json missing fields: {', '.join(missing)}")
    if not str(data["ssh_target"]).strip():
        raise DeployError("production ssh_target is not configured; host discovery is forbidden")
    fingerprint = str(data["host_key_sha256"]).strip()
    if not FINGERPRINT_RE.fullmatch(fingerprint):
        raise DeployError("production host_key_sha256 is missing or malformed; fail closed")
    if data["repository_path"] != "/opt/secretary":
        raise DeployError("unexpected production repository_path")
    if data["origin_url"] != CANONICAL_ORIGIN:
        raise DeployError("unexpected production origin_url")
    if data["compose_files"] != ["infra/compose.yaml", "infra/compose.deploy.yaml"]:
        raise DeployError("unexpected production compose_files")
    if data["health_url"] != "http://127.0.0.1:18080/health":
        raise DeployError("unexpected production health_url")
    port = data["ssh_port"]
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise DeployError("invalid production ssh_port")
    return data


def _validate_sha(name: str, value: str) -> str:
    value = value.strip().lower()
    if not SHA_RE.fullmatch(value):
        raise DeployError(f"{name} must be an exact 40-character lowercase Git SHA")
    return value


def _require_schema_neutral_release(rollback_sha: str, release_sha: str) -> None:
    for name, sha in (("rollback", rollback_sha), ("release", release_sha)):
        try:
            _run_local(["git", "-C", str(REPOSITORY_ROOT), "cat-file", "-e", f"{sha}^{{commit}}"])
        except DeployError as exc:
            raise DeployError(f"{name} SHA cannot be resolved locally") from exc

    proc = subprocess.run(
        [
            "git",
            "-C",
            str(REPOSITORY_ROOT),
            "diff",
            "--quiet",
            rollback_sha,
            release_sha,
            "--",
            *MIGRATION_PATHS,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 1:
        raise DeployError(
            "release changes migration infrastructure; separate migration deployment plan required"
        )
    if proc.returncode != 0:
        raise DeployError("unable to compare release migration infrastructure")


def _host_from_target(target: str) -> str:
    host = target.rsplit("@", 1)[-1]
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host or any(ch.isspace() for ch in host):
        raise DeployError("invalid ssh_target")
    return host


def _fingerprint_for_line(line: str) -> str | None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")
        handle.flush()
        proc = subprocess.run(
            ["ssh-keygen", "-lf", handle.name, "-E", "sha256"],
            text=True,
            capture_output=True,
            check=False,
        )
    if proc.returncode != 0:
        return None
    parts = proc.stdout.strip().split()
    return parts[1] if len(parts) >= 2 else None


def _verified_known_hosts(target: str, port: int, expected: str) -> str:
    host = _host_from_target(target)
    scan = subprocess.run(
        ["ssh-keyscan", "-T", "5", "-p", str(port), host],
        text=True,
        capture_output=True,
        check=False,
    )
    if scan.returncode not in (0, 1) or not scan.stdout.strip():
        raise DeployError("unable to obtain production SSH host key")

    matching: list[str] = []
    for line in scan.stdout.splitlines():
        if not line or line.startswith("#"):
            continue
        if _fingerprint_for_line(line) == expected:
            matching.append(line)
    if not matching:
        raise DeployError("production SSH host-key fingerprint mismatch")
    return "\n".join(matching) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--rollback-sha", required=True)
    parser.add_argument("--expected-alembic", required=True)
    args = parser.parse_args()

    try:
        _require_canonical_local_checkout()
        target = _load_target()
        release_sha = _validate_sha("release-sha", args.release_sha)
        rollback_sha = _validate_sha("rollback-sha", args.rollback_sha)
        _require_schema_neutral_release(rollback_sha, release_sha)
        expected_alembic = args.expected_alembic.strip()
        if not re.fullmatch(r"[0-9]{4}", expected_alembic):
            raise DeployError("expected-alembic must be a four-digit revision")
        helper = REMOTE_HELPER.read_text(encoding="utf-8")
        known_hosts = _verified_known_hosts(
            target["ssh_target"],
            target["ssh_port"],
            target["host_key_sha256"],
        )

        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as hosts_file:
            hosts_file.write(known_hosts)
            hosts_file.flush()
            remote_args = [
                "python3",
                "-",
                "--release-sha",
                release_sha,
                "--rollback-sha",
                rollback_sha,
                "--expected-alembic",
                expected_alembic,
                "--origin-url",
                target["origin_url"],
                "--health-url",
                target["health_url"],
            ]
            remote_command = (
                f"cd {shlex.quote(target['repository_path'])} && "
                + " ".join(shlex.quote(item) for item in remote_args)
            )
            ssh = [
                "ssh",
                "-p",
                str(target["ssh_port"]),
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                f"UserKnownHostsFile={hosts_file.name}",
                "-o",
                "GlobalKnownHostsFile=/dev/null",
                target["ssh_target"],
                remote_command,
            ]
            proc = subprocess.run(ssh, input=helper, text=True, check=False)
        return proc.returncode
    except (DeployError, OSError, json.JSONDecodeError) as exc:
        print(f"DEPLOYMENT_BLOCKED={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
