#!/usr/bin/env python3
"""One-shot read-only production Person census. Prints six aggregate counts."""

from __future__ import annotations

import json
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

HERE = Path(__file__).resolve().parent
REMOTE_HELPER = HERE / "remote_people_p1_person_census.py"
PRODUCTION_SHA = "296b4735f9473ea60ef22f1827ed94260603128e"
FACTS = (
    "PERSON_TOTAL",
    "PERSON_VISIBLE",
    "PERSON_WITH_EDGES",
    "PERSON_INCIDENT_EDGES",
    "PERSON_TASK_EDGES",
    "PERSON_FLOW_EDGES",
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
}


class CensusClientError(RuntimeError):
    def __init__(self, code: str, *, consumed: bool = False) -> None:
        self.code = code
        self.consumed = consumed
        super().__init__(code)


def require_release_sha(value: str) -> str:
    if value != PRODUCTION_SHA:
        raise CensusClientError("release_sha")
    return value


def require_origin_production(value: str) -> None:
    if value != PRODUCTION_SHA:
        raise CensusClientError("origin_production")


def classify(facts: dict[str, int]) -> str:
    if facts["PERSON_VISIBLE"] == 0:
        return "P1_REAL_DATA_NOT_USEFUL_YET"
    if facts["PERSON_TASK_EDGES"] == 0 and facts["PERSON_FLOW_EDGES"] == 0:
        return "P1_REAL_DATA_NOT_USEFUL_YET"
    return "P1_REAL_DATA_CANDIDATE_EXISTS"


def _blocked_stage(line: str) -> str | None:
    prefix = "CENSUS_BLOCKED="
    if not line.startswith(prefix):
        return None
    stage = line[len(prefix) :]
    if stage not in BLOCKED_STAGES:
        return None
    return stage


def parse_remote_output(text: str) -> dict[str, int]:
    lines = text.splitlines()
    consumed = "CENSUS_MARKER=started" in lines
    if lines == []:
        raise CensusClientError("malformed", consumed=False)
    pre_marker = _blocked_stage(lines[0]) if len(lines) == 1 else None
    if pre_marker is not None:
        raise CensusClientError(pre_marker, consumed=False)
    if (
        len(lines) == 2
        and lines[0] == "CENSUS_MARKER=started"
        and _blocked_stage(lines[1]) is not None
    ):
        raise CensusClientError(_blocked_stage(lines[1]) or "malformed", consumed=True)
    expected = [
        "CENSUS_MARKER=started",
        "CENSUS_PREFLIGHT=pass",
        "CENSUS_READ_ONLY=on",
        *[f"{key}=" for key in FACTS],
    ]
    if len(lines) != len(expected):
        raise CensusClientError("malformed", consumed=consumed)
    facts: dict[str, int] = {}
    for line, prefix in zip(lines, expected, strict=True):
        if not prefix.endswith("="):
            if line != prefix:
                raise CensusClientError("malformed", consumed=consumed)
            continue
        key = prefix[:-1]
        if not line.startswith(prefix) or not line[len(prefix) :].isdecimal():
            raise CensusClientError("malformed", consumed=consumed)
        facts[key] = int(line[len(prefix) :])
    if set(facts) != set(FACTS):
        raise CensusClientError("malformed", consumed=consumed)
    return facts


def format_facts(facts: dict[str, int]) -> str:
    if set(facts) != set(FACTS):
        raise CensusClientError("malformed")
    return "".join(f"{key}={facts[key]}\n" for key in FACTS)


def _load_target() -> dict:
    data = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    if data.get("repository_path") != "/opt/secretary":
        raise CensusClientError("target")
    if data.get("origin_url") != CANONICAL_ORIGIN:
        raise CensusClientError("target")
    if not str(data.get("host_key_sha256", "")).startswith("SHA256:"):
        raise CensusClientError("target")
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
        raise CensusClientError("host_key")
    matching = [
        line
        for line in scan.stdout.splitlines()
        if line and not line.startswith("#") and _fingerprint_for_line(line) == target["host_key_sha256"]
    ]
    if not matching:
        raise CensusClientError("host_key")
    return "\n".join(matching) + "\n"


def _ssh(target: dict, known_hosts: str, remote_command: str, stdin: str | None) -> subprocess.CompletedProcess[str]:
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
        raise CensusClientError("local_repo")
    origin = _run_local(["git", "-C", str(REPOSITORY_ROOT), "remote", "get-url", "origin"])
    if origin != CANONICAL_ORIGIN:
        raise CensusClientError("local_repo")
    if _run_local(["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain"]):
        raise CensusClientError("local_repo")
    _run_local(["git", "-C", str(REPOSITORY_ROOT), "fetch", "--prune", "origin", "production"])
    require_origin_production(
        _run_local(["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "origin/production"])
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("CENSUS_BOOTSTRAP_BLOCKED=release_sha", file=sys.stderr)
        return 2
    try:
        require_release_sha(sys.argv[1])
        _require_local()
        target = _load_target()
        known_hosts = _known_hosts(target)
        probe = _ssh(target, known_hosts, "true", None)
        if probe.returncode != 0:
            raise CensusClientError("ssh")
        remote = (
            f"cd {shlex.quote(target['repository_path'])} && "
            f"python3 - {shlex.quote(PRODUCTION_SHA)} {shlex.quote(target['health_url'])}"
        )
        result = _ssh(target, known_hosts, remote, REMOTE_HELPER.read_text(encoding="utf-8"))
        facts = parse_remote_output(result.stdout)
        sys.stdout.write(format_facts(facts))
        return 0 if result.returncode == 0 else 1
    except CensusClientError as exc:
        print(f"CENSUS_BOOTSTRAP_BLOCKED={exc.code}", file=sys.stderr)
        if exc.consumed:
            print("CENSUS_AUTHORIZATION_CONSUMED=true", file=sys.stderr)
        return 2
    except (DeployError, OSError, json.JSONDecodeError):
        print("CENSUS_BOOTSTRAP_BLOCKED=local", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
