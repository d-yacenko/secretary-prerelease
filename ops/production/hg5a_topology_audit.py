#!/usr/bin/env python3
"""Fail-closed read-only HG5A Task/People topology audit. Aggregate facts only."""

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
from remote_hg5a_topology_audit import BLOCKED_STAGES, PRODUCTION_SHA, fact_key_order

HERE = Path(__file__).resolve().parent
REMOTE_HELPER = HERE / "remote_hg5a_topology_audit.py"
EXPECTED_ALEMBIC = "0054"
SUCCESS_PREFIX = (
    "AUDIT_MARKER=started",
    "AUDIT_PREFLIGHT=pass",
    "AUDIT_READ_ONLY=on",
    "PRODUCTION_SHA_OK=true",
    "ALEMBIC_0054_OK=true",
)
SUCCESS_SUFFIX = (
    "PROVIDER_NETWORK_CALLS=0",
    "AUDIT_TERMINAL=success",
)
_EMAIL_MARK = re.compile(r"@")
_UUID_MARK = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_APPROVED_KEY = re.compile(
    r"^(?:USER_COUNT|TASK_SEMANTIC_WINDOW_COUNT|TASK_SEMANTIC_TASK_TOTAL|"
    r"TASK_WINDOW_[0-9]+_TASK_COUNT|TASK_IDS_DUPLICATED_ACROSS_WINDOWS|"
    r"TASK_WINDOW_UNION_UNIQUE_COUNT|ACTIVE_PERSON_TOTAL|PEOPLE_PAGES_ENUMERATED|"
    r"PEOPLE_ENUMERATED_UNIQUE|PEOPLE_DUPLICATED_ACROSS_CURRENT_PAGES|"
    r"PEOPLE_UNANCHORED|PEOPLE_SINGLE_WINDOW_ANCHORED|PEOPLE_MULTI_WINDOW_ANCHORED|"
    r"PEOPLE_INCOMPLETE_ANCHORS|PEOPLE_UNMAPPED_ANCHORS|PEOPLE_RELEVANT_TO_WINDOW_[0-9]+|"
    r"PEOPLE_WINDOW_RELEVANCE_MEMBERSHIPS|PEOPLE_MULTI_WINDOW_MAX_SPAN|"
    r"PEOPLE_WITH_ONE_TASK_ANCHOR|PEOPLE_WITH_MULTIPLE_TASK_ANCHORS|"
    r"CURRENT_PEOPLE_PAGE_COUNT|CURRENT_PEOPLE_PAGE_WINDOW_ALIGNED_COUNT|"
    r"CURRENT_PEOPLE_PAGE_WINDOW_MISMATCH_COUNT)$"
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
    if not text.isdecimal() or (text != "0" and text.startswith("0")):
        raise PreflightClientError("malformed")
    return int(text)


def _parse_fact_lines(lines: list[str]) -> dict[str, int]:
    facts: dict[str, int] = {}
    for line in lines:
        if "=" not in line:
            raise PreflightClientError("malformed")
        key, value_text = line.split("=", 1)
        if not _APPROVED_KEY.fullmatch(key) or key in facts:
            raise PreflightClientError("malformed")
        facts[key] = _integer_value(value_text)
    if "TASK_SEMANTIC_WINDOW_COUNT" not in facts:
        raise PreflightClientError("malformed")
    try:
        order = fact_key_order(facts["TASK_SEMANTIC_WINDOW_COUNT"])
    except Exception as exc:
        raise PreflightClientError("malformed") from exc
    if tuple(facts) != order:
        raise PreflightClientError("malformed")
    categories = (
        facts["PEOPLE_UNANCHORED"]
        + facts["PEOPLE_SINGLE_WINDOW_ANCHORED"]
        + facts["PEOPLE_MULTI_WINDOW_ANCHORED"]
        + facts["PEOPLE_INCOMPLETE_ANCHORS"]
        + facts["PEOPLE_UNMAPPED_ANCHORS"]
    )
    if categories != facts["ACTIVE_PERSON_TOTAL"]:
        raise PreflightClientError("malformed")
    if facts["PEOPLE_ENUMERATED_UNIQUE"] != facts["ACTIVE_PERSON_TOTAL"]:
        raise PreflightClientError("malformed")
    if facts["PEOPLE_DUPLICATED_ACROSS_CURRENT_PAGES"] != 0:
        raise PreflightClientError("malformed")
    if facts["TASK_IDS_DUPLICATED_ACROSS_WINDOWS"] != 0:
        raise PreflightClientError("malformed")
    if (
        facts["CURRENT_PEOPLE_PAGE_WINDOW_ALIGNED_COUNT"]
        + facts["CURRENT_PEOPLE_PAGE_WINDOW_MISMATCH_COUNT"]
        != facts["PEOPLE_SINGLE_WINDOW_ANCHORED"]
    ):
        raise PreflightClientError("malformed")
    return {key: facts[key] for key in order}


def parse_remote_output(text: str) -> dict[str, int]:
    lines = text.splitlines()
    if lines and lines[-1] == "":
        lines = lines[:-1]
    for line in lines:
        _reject_identity(line)
    blocked = _parse_blocked(lines)
    if blocked is not None:
        raise PreflightClientError(blocked)
    if len(lines) < len(SUCCESS_PREFIX) + len(SUCCESS_SUFFIX):
        raise PreflightClientError("malformed")
    prefix = tuple(lines[: len(SUCCESS_PREFIX)])
    suffix = tuple(lines[-len(SUCCESS_SUFFIX) :])
    if prefix != SUCCESS_PREFIX or suffix != SUCCESS_SUFFIX:
        raise PreflightClientError("malformed")
    return _parse_fact_lines(lines[len(SUCCESS_PREFIX) : -len(SUCCESS_SUFFIX)])


def _parse_blocked(lines: list[str]) -> str | None:
    body = lines
    if lines and lines[0] == "AUDIT_MARKER=started":
        body = lines[1:]
    if not body or not body[0].startswith("AUDIT_BLOCKED="):
        return None
    if len(body) != 3:
        raise PreflightClientError("malformed")
    stage = body[0].split("=", 1)[1]
    if stage not in BLOCKED_STAGES or body[0] != f"AUDIT_BLOCKED={stage}":
        raise PreflightClientError("malformed")
    if body[1] != "AUDIT_ERROR_CLASS=RemotePreflightError" and not re.fullmatch(
        r"AUDIT_ERROR_CLASS=[A-Za-z][A-Za-z0-9]{0,40}",
        body[1],
    ):
        raise PreflightClientError("malformed")
    if body[2] != "PROVIDER_NETWORK_CALLS=0":
        raise PreflightClientError("malformed")
    return stage


def format_facts(facts: dict[str, int]) -> str:
    order = fact_key_order(facts["TASK_SEMANTIC_WINDOW_COUNT"])
    if tuple(facts) != order:
        raise PreflightClientError("malformed")
    for value in facts.values():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PreflightClientError("malformed")
    lines = [
        *SUCCESS_PREFIX,
        *[f"{key}={facts[key]}" for key in order],
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
    print(f"AUDIT_BLOCKED={code}")
    print("AUDIT_ERROR_CLASS=PreflightClientError")
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
        sys.stdout.write(format_facts({key: int(facts[key]) for key in fact_key_order(facts["TASK_SEMANTIC_WINDOW_COUNT"])}))
        return 0 if result.returncode == 0 else 1
    except PreflightClientError as exc:
        _blocked(exc.code)
        return 2
    except (DeployError, OSError, json.JSONDecodeError):
        _blocked("local_repo")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
