#!/usr/bin/env python3
"""Fail-closed publisher for the nginx static branding pages.

Run later from a canonical, clean, up-to-date local main. This task does not
execute it. It reuses target.json and never discovers a host. It does not
start a container or change nginx.
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
REMOTE_HELPER = HERE / "remote_public_web.py"
CANONICAL_ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")


class PublicWebError(RuntimeError):
    pass


def assess_local_checkout(
    *,
    origin: str,
    porcelain: str,
    branch: str,
    head: str,
    origin_main: str,
) -> None:
    if origin != CANONICAL_ORIGIN:
        raise PublicWebError("local rollout checkout has the wrong Git origin")
    if porcelain:
        raise PublicWebError("local rollout checkout is not clean")
    if branch != "main":
        raise PublicWebError("public web rollout must run from local main")
    if head != origin_main:
        raise PublicWebError(
            "local main is stale; fast-forward it to origin/main first"
        )


def load_target(data: dict) -> dict:
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
        raise PublicWebError(f"target.json missing fields: {', '.join(missing)}")
    if not str(data["ssh_target"]).strip():
        raise PublicWebError("production ssh_target is not configured")
    if not FINGERPRINT_RE.fullmatch(str(data["host_key_sha256"]).strip()):
        raise PublicWebError("production host_key_sha256 is missing or malformed")
    if data["repository_path"] != "/opt/secretary":
        raise PublicWebError("unexpected production repository_path")
    if data["origin_url"] != CANONICAL_ORIGIN:
        raise PublicWebError("unexpected production origin_url")
    if data["compose_files"] != ["infra/compose.yaml", "infra/compose.deploy.yaml"]:
        raise PublicWebError("unexpected production compose_files")
    if data["health_url"] != "http://127.0.0.1:18080/health":
        raise PublicWebError("unexpected production health_url")
    port = data["ssh_port"]
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise PublicWebError("invalid production ssh_port")
    return data


def validate_sha(value: str) -> str:
    value = value.strip().lower()
    if not SHA_RE.fullmatch(value):
        raise PublicWebError(
            "release-sha must be an exact 40-character lowercase Git SHA"
        )
    return value


def _run_local(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "command failed").strip().splitlines()
        tail = message[-1][:300] if message else "command failed"
        raise PublicWebError(tail)
    return proc.stdout.strip()


def _host_from_target(target: str) -> str:
    host = target.rsplit("@", 1)[-1]
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host or any(ch.isspace() for ch in host):
        raise PublicWebError("invalid ssh_target")
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
        raise PublicWebError("unable to obtain production SSH host key")
    matching = [
        line
        for line in scan.stdout.splitlines()
        if line and not line.startswith("#") and _fingerprint_for_line(line) == expected
    ]
    if not matching:
        raise PublicWebError("production SSH host-key fingerprint mismatch")
    return "\n".join(matching) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-sha", required=True)
    args = parser.parse_args()
    try:
        origin = _run_local(
            ["git", "-C", str(REPOSITORY_ROOT), "remote", "get-url", "origin"]
        )
        porcelain = _run_local(
            ["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain"]
        )
        branch = _run_local(
            ["git", "-C", str(REPOSITORY_ROOT), "branch", "--show-current"]
        )
        _run_local(
            ["git", "-C", str(REPOSITORY_ROOT), "fetch", "--prune", "origin", "main"]
        )
        head = _run_local(["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"])
        origin_main = _run_local(
            ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "origin/main"]
        )
        assess_local_checkout(
            origin=origin,
            porcelain=porcelain,
            branch=branch,
            head=head,
            origin_main=origin_main,
        )
        target = load_target(json.loads(TARGET_FILE.read_text(encoding="utf-8")))
        release_sha = validate_sha(args.release_sha)
        _run_local(
            [
                "git",
                "-C",
                str(REPOSITORY_ROOT),
                "cat-file",
                "-e",
                f"{release_sha}^{{commit}}",
            ]
        )
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
    except (PublicWebError, OSError, json.JSONDecodeError) as exc:
        print(f"PUBLIC_WEB_BLOCKED={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
