#!/usr/bin/env python3
"""Stream the self-authored E2E harness into an isolated production one-shot.

The container inherits the production Telegram AI flag. The harness sets
process-local true only after its privacy proofs. This wrapper does not
deploy, recreate, restart, or mutate the production checkout.
"""

from __future__ import annotations

import argparse
import base64
import inspect
import json
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parent.parent
TARGET_FILE = HERE / "target.json"
HELPER_FILE = HERE / "telegram_self_authored_e2e.py"
CANONICAL_ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"
PRODUCTION_RELEASE = "8ad52f0653f9f90e1932c49532dc4f993ea1a9cc"
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
TRUE_FLAGS = {"1", "true", "yes", "on"}
ONESHOT_HELPER_NAME = "telegram_self_authored_e2e.py"
ONESHOT_HELPER_DEST = f"/app/{ONESHOT_HELPER_NAME}"
HOST_HELPER_PATH = f"/tmp/{ONESHOT_HELPER_NAME}"
GitRunner = Callable[[list[str]], str]


class RemoteBlocked(RuntimeError):
    pass


def _flag_enabled(value: str) -> bool:
    return value.strip().lower() in TRUE_FLAGS


def assess_remote_state(
    head: str,
    porcelain: str,
    api_flag: str,
    worker_flag: str,
    release: str,
) -> str | None:
    if head != release:
        return "production_ref"
    if porcelain.strip():
        return "worktree"
    if _flag_enabled(api_flag) or _flag_enabled(worker_flag):
        return "long_running_ai"
    return None


def require_local_checkout(git: GitRunner) -> None:
    root = Path(git(["rev-parse", "--show-toplevel"])).resolve()
    if root != REPOSITORY_ROOT.resolve():
        raise RemoteBlocked("checkout")
    if git(["remote", "get-url", "origin"]) != CANONICAL_ORIGIN:
        raise RemoteBlocked("origin")
    if git(["status", "--porcelain"]):
        raise RemoteBlocked("dirty_worktree")
    if git(["branch", "--show-current"]) != "main":
        raise RemoteBlocked("branch")
    git(["fetch", "--prune", "origin", "main", "production"])
    if git(["rev-parse", "HEAD"]) != git(["rev-parse", "origin/main"]):
        raise RemoteBlocked("stale_main")
    if git(["rev-parse", "origin/production"]) != PRODUCTION_RELEASE:
        raise RemoteBlocked("production_ref")


def load_target(path: Path = TARGET_FILE) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "ssh_target",
        "ssh_port",
        "host_key_sha256",
        "repository_path",
        "origin_url",
        "health_url",
        "compose_files",
    }
    if not required <= data.keys():
        raise RemoteBlocked("target")
    if data["repository_path"] != "/opt/secretary":
        raise RemoteBlocked("target")
    if data["origin_url"] != CANONICAL_ORIGIN:
        raise RemoteBlocked("target")
    if data["compose_files"] != ["infra/compose.yaml", "infra/compose.deploy.yaml"]:
        raise RemoteBlocked("target")
    if not FINGERPRINT_RE.fullmatch(str(data["host_key_sha256"]).strip()):
        raise RemoteBlocked("target")
    port = data["ssh_port"]
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise RemoteBlocked("target")
    return data


def select_host_keys(scan_text: str, expected: str, fingerprint_of: Callable[[str], str]) -> str:
    matches = [
        line
        for line in scan_text.splitlines()
        if line and not line.startswith("#") and fingerprint_of(line) == expected
    ]
    if not matches:
        raise RemoteBlocked("host_key")
    return "\n".join(matches) + "\n"


def ssh_command(target: str, port: int, known_hosts: Path) -> list[str]:
    return [
        "ssh",
        "-T",
        "-p",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "PreferredAuthentications=publickey",
        target,
        "python3 -B -",
    ]


def oneshot_compose_command(helper_path: str = HOST_HELPER_PATH) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        "/opt/secretary/.env",
        "-f",
        "infra/compose.yaml",
        "-f",
        "infra/compose.deploy.yaml",
        "run",
        "--rm",
        "--no-deps",
        "--no-build",
        "-e",
        "SELF_E2E_CONFIRM=reviewed",
        "-e",
        "REHEARSAL_LONG_RUNNING_API_AI=false",
        "-e",
        "REHEARSAL_LONG_RUNNING_WORKER_AI=false",
        "-v",
        f"{helper_path}:{ONESHOT_HELPER_DEST}:ro",
        "api",
        "python3",
        ONESHOT_HELPER_DEST,
        "--live",
    ]


def build_remote_program(helper_source: str) -> str:
    encoded = base64.b64encode(helper_source.encode("utf-8")).decode("ascii")
    command = oneshot_compose_command(HOST_HELPER_PATH)
    logic = (
        f"TRUE_FLAGS = {tuple(sorted(TRUE_FLAGS))!r}\n"
        + inspect.getsource(_flag_enabled)
        + "\n"
        + inspect.getsource(assess_remote_state)
    )
    return f"""import base64
import subprocess
import sys
from pathlib import Path

{logic}
RELEASE = {PRODUCTION_RELEASE!r}
HELPER_PATH = {HOST_HELPER_PATH!r}
ONESHOT = {command!r}
HELPER_B64 = {encoded!r}
CANONICAL_ORIGIN = {CANONICAL_ORIGIN!r}


def git(*args):
    proc = subprocess.run(
        ["git", *args], cwd="/opt/secretary", text=True, capture_output=True, check=False
    )
    if proc.returncode != 0:
        sys.stdout.write("SELF_E2E_REMOTE_BLOCKED=git\\n")
        raise SystemExit(2)
    return proc.stdout.strip()


def service_flag(service):
    proc = subprocess.run(
        [
            "docker", "compose", "--env-file", "/opt/secretary/.env",
            "-f", "infra/compose.yaml", "-f", "infra/compose.deploy.yaml",
            "exec", "-T", service, "printenv", "TELEGRAM_MTPROTO_AI_ENABLED",
        ],
        cwd="/opt/secretary",
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        sys.stdout.write("SELF_E2E_REMOTE_BLOCKED=long_running_probe\\n")
        raise SystemExit(2)
    return proc.stdout.strip()


try:
    head = git("rev-parse", "HEAD")
    porcelain = git("status", "--porcelain")
    origin = git("remote", "get-url", "origin")
    if origin != CANONICAL_ORIGIN:
        sys.stdout.write("SELF_E2E_REMOTE_BLOCKED=origin\\n")
        raise SystemExit(2)
    if head != RELEASE or porcelain.strip():
        reason = assess_remote_state(head, porcelain, "false", "false", RELEASE)
        sys.stdout.write(f"SELF_E2E_REMOTE_BLOCKED={{reason or 'production_ref'}}\\n")
        raise SystemExit(2)
    reason = assess_remote_state(head, porcelain, service_flag("api"), service_flag("worker"), RELEASE)
    if reason:
        sys.stdout.write(f"SELF_E2E_REMOTE_BLOCKED={{reason}}\\n")
        raise SystemExit(2)
    Path(HELPER_PATH).write_text(base64.b64decode(HELPER_B64).decode("utf-8"), encoding="utf-8")
    proc = subprocess.run(ONESHOT, cwd="/opt/secretary", text=True, capture_output=True, check=False)
    output = proc.stdout
    if proc.returncode != 0 and "SELF_AUTHORED=PASS" not in output and "SELF_E2E_" not in output:
        output = "SELF_E2E_REMOTE_BLOCKED=oneshot_failed\\n"
    sys.stdout.write(output)
    raise SystemExit(proc.returncode)
except SystemExit:
    raise
except Exception:
    sys.stdout.write("SELF_E2E_REMOTE_BLOCKED=remote_program\\n")
    raise SystemExit(1)
"""


def public_output(stdout: str, stderr: str) -> str:
    del stderr
    return stdout


def _git(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RemoteBlocked("git")
    return proc.stdout.strip()


def _fingerprint_for_line(line: str) -> str:
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
        return ""
    parts = proc.stdout.strip().split()
    return parts[1] if len(parts) >= 2 else ""


def verified_known_hosts(target: str, port: int, expected: str) -> str:
    host = target.rsplit("@", 1)[-1]
    scan = subprocess.run(
        ["ssh-keyscan", "-T", "5", "-p", str(port), host],
        text=True,
        capture_output=True,
        check=False,
    )
    if scan.returncode not in (0, 1) or not scan.stdout.strip():
        raise RemoteBlocked("host_key")
    return select_host_keys(scan.stdout, expected, _fingerprint_for_line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args(argv)
    try:
        require_local_checkout(_git)
        target = load_target()
        known = verified_known_hosts(
            target["ssh_target"], target["ssh_port"], target["host_key_sha256"]
        )
        program = build_remote_program(HELPER_FILE.read_text(encoding="utf-8"))
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as hosts:
            hosts.write(known)
            hosts.flush()
            remote = " ".join(shlex.quote(part) for part in ["python3", "-B", "-"])
            command = ssh_command(target["ssh_target"], target["ssh_port"], Path(hosts.name))
            command[-1] = f"cd {shlex.quote(target['repository_path'])} && {remote}"
            proc = subprocess.run(
                command, input=program, text=True, capture_output=True, check=False
            )
        sys.stdout.write(public_output(proc.stdout, proc.stderr))
        return proc.returncode
    except RemoteBlocked as exc:
        sys.stdout.write(f"SELF_E2E_REMOTE_BLOCKED={exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
