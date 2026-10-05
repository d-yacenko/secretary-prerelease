#!/usr/bin/env python3
"""Fail-closed read-only HG2 repair preflight. Prints aggregate facts only."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from deploy import (
    CANONICAL_ORIGIN,
    REPOSITORY_ROOT,
    TARGET_FILE,
    DeployError,
    _fingerprint_for_line,
    _host_from_target,
    _run_local,
)
from remote_hg2_repair_preflight import FACT_ORDER, PRODUCTION_SHA

HERE = Path(__file__).resolve().parent
REMOTE_HELPER = HERE / "remote_hg2_repair_preflight.py"
EXPECTED_ALEMBIC = "0054"
SUCCESS_PREFIX = (
    "HG2_PREFLIGHT_MARKER=started",
    "HG2_PREFLIGHT_GUARDS=pass",
    "HG2_PREFLIGHT_READ_ONLY=on",
)
SUCCESS_SUFFIX = (
    "YANDEX_PROVIDER_UIDVALIDITY_KNOWN=false",
    "PROVIDER_NETWORK_CALLS=0",
    "HG2_PREFLIGHT_TERMINAL=success",
)
BLOCKED_STAGES = {
    "arguments",
    "cwd",
    "origin",
    "worktree",
    "head",
    "production_ref",
    "db_running",
    "api_running",
    "worker_running",
    "db_health",
    "api_health",
    "alembic",
    "command",
    "read_only",
    "census_output",
    "release_sha",
    "origin_production",
    "target",
    "host_key",
    "ssh",
    "local_repo",
}
_EMAIL_MARK = re.compile(r"@")
_UUID_MARK = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class PreflightClientError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def require_release_sha(value: str) -> str:
    if value != PRODUCTION_SHA:
        raise PreflightClientError("release_sha")
    return value


def require_origin_production(value: str) -> None:
    if value != PRODUCTION_SHA:
        raise PreflightClientError("origin_production")


def _reject_identity(line: str) -> None:
    if _EMAIL_MARK.search(line) or _UUID_MARK.search(line):
        raise PreflightClientError("malformed")


def _integer_value(text: str) -> int:
    if not text.isdecimal():
        raise PreflightClientError("malformed")
    if text != "0" and text.startswith("0"):
        raise PreflightClientError("malformed")
    return int(text)


def parse_remote_output(text: str) -> dict[str, int | bool]:
    lines = text.splitlines()
    if lines and lines[-1] == "":
        lines = lines[:-1]
    for line in lines:
        _reject_identity(line)
    blocked = _parse_blocked(lines)
    if blocked is not None:
        raise PreflightClientError(blocked)
    expected = [*SUCCESS_PREFIX, *FACT_ORDER, *SUCCESS_SUFFIX]
    if len(lines) != len(expected):
        raise PreflightClientError("malformed")
    facts: dict[str, int | bool] = {}
    seen: set[str] = set()
    for line, prefix in zip(lines, expected, strict=True):
        if prefix in SUCCESS_PREFIX or prefix in SUCCESS_SUFFIX:
            if line != prefix:
                raise PreflightClientError("malformed")
            continue
        key_prefix = f"{prefix}="
        if not line.startswith(key_prefix) or prefix in seen:
            raise PreflightClientError("malformed")
        seen.add(prefix)
        facts[prefix] = _integer_value(line[len(key_prefix) :])
    if tuple(facts) != FACT_ORDER:
        raise PreflightClientError("malformed")
    return facts


def _parse_blocked(lines: list[str]) -> str | None:
    body = lines
    if lines and lines[0] == "HG2_PREFLIGHT_MARKER=started":
        body = lines[1:]
    if not body or not body[0].startswith("HG2_PREFLIGHT_BLOCKED="):
        return None
    if len(body) != 3:
        raise PreflightClientError("malformed")
    stage = body[0].split("=", 1)[1]
    if stage not in BLOCKED_STAGES or body[0] != f"HG2_PREFLIGHT_BLOCKED={stage}":
        raise PreflightClientError("malformed")
    if body[1] != "HG2_PREFLIGHT_ERROR_CLASS=RemotePreflightError" and not re.fullmatch(
        r"HG2_PREFLIGHT_ERROR_CLASS=[A-Za-z][A-Za-z0-9]{0,40}",
        body[1],
    ):
        raise PreflightClientError("malformed")
    if body[2] != "PROVIDER_NETWORK_CALLS=0":
        raise PreflightClientError("malformed")
    return stage


def format_facts(facts: dict[str, int]) -> str:
    if tuple(facts) != FACT_ORDER:
        raise PreflightClientError("malformed")
    for value in facts.values():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PreflightClientError("malformed")
    lines = [
        *SUCCESS_PREFIX,
        *[f"{key}={facts[key]}" for key in FACT_ORDER],
        *SUCCESS_SUFFIX,
    ]
    rendered = "\n".join(lines) + "\n"
    parse_remote_output(rendered)
    return rendered


def _load_target() -> dict:
    data = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    if data.get("repository_path") != "/opt/secretary":
        raise PreflightClientError("target")
    if data.get("origin_url") != CANONICAL_ORIGIN:
        raise PreflightClientError("target")
    if not str(data.get("host_key_sha256", "")).startswith("SHA256:"):
        raise PreflightClientError("target")
    if data.get("health_url") != "http://127.0.0.1:18080/health":
        raise PreflightClientError("target")
    return data


def _known_hosts(target: dict) -> str:
    host = _host_from_target(target["ssh_target"])
    scan = subprocess.run(
        ["ssh-keyscan", "-T", "5", "-p", str(target["ssh_port"]), host],
        text=True,
        capture_output=True,
        check=False,
    )
    if scan.returncode not in (0, 1) or not scan.stdout.strip():
        raise PreflightClientError("host_key")
    matching = [
        line
        for line in scan.stdout.splitlines()
        if line and not line.startswith("#") and _fingerprint_for_line(line) == target["host_key_sha256"]
    ]
    if not matching:
        raise PreflightClientError("host_key")
    return "\n".join(matching) + "\n"


def _ssh(target: dict, known_hosts: str, remote_command: str, stdin: str) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as hosts_file:
        hosts_file.write(known_hosts)
        hosts_file.flush()
        command = [
            "ssh",
            "-p",
            str(target["ssh_port"]),
            "-o",
            "BatchMode=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "PreferredAuthentications=publickey",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={hosts_file.name}",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            target["ssh_target"],
            remote_command,
        ]
        return subprocess.run(command, input=stdin, text=True, capture_output=True, check=False)


def _require_local() -> None:
    root = Path(_run_local(["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "--show-toplevel"]))
    if root.resolve() != REPOSITORY_ROOT.resolve():
        raise PreflightClientError("local_repo")
    origin = _run_local(["git", "-C", str(REPOSITORY_ROOT), "remote", "get-url", "origin"])
    if origin != CANONICAL_ORIGIN:
        raise PreflightClientError("local_repo")
    if _run_local(["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain"]):
        raise PreflightClientError("local_repo")
    _run_local(["git", "-C", str(REPOSITORY_ROOT), "fetch", "--prune", "origin", "production"])
    require_origin_production(
        _run_local(["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "origin/production"])
    )
    require_release_sha(PRODUCTION_SHA)


def _blocked(code: str) -> None:
    print(f"HG2_PREFLIGHT_BLOCKED={code}")
    print("HG2_PREFLIGHT_ERROR_CLASS=PreflightClientError")
    print("PROVIDER_NETWORK_CALLS=0")


def main() -> int:
    if len(sys.argv) != 1:
        _blocked("arguments")
        return 2
    try:
        _require_local()
        target = _load_target()
        known_hosts = _known_hosts(target)
        remote = (
            f"cd {shlex.quote(target['repository_path'])} && "
            f"python3 - {shlex.quote(PRODUCTION_SHA)} {shlex.quote(target['health_url'])}"
        )
        result = _ssh(target, known_hosts, remote, REMOTE_HELPER.read_text(encoding="utf-8"))
        facts = parse_remote_output(result.stdout)
        sys.stdout.write(format_facts({key: int(facts[key]) for key in FACT_ORDER}))
        return 0 if result.returncode == 0 else 1
    except PreflightClientError as exc:
        _blocked(exc.code)
        return 2
    except (DeployError, OSError, json.JSONDecodeError):
        _blocked("local_repo")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
