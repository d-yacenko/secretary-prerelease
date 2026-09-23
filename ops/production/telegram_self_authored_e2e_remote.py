#!/usr/bin/env python3
"""Run the self-authored E2E harness inside the already-running API container.

The exec process receives only the acceptance environment overrides. The
harness sets process-local true only after its privacy proofs. This wrapper
does not create a container, build or pull an image, or write into the
production checkout or container filesystem.
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
STARTUP_BOOTSTRAP = "SELF_E2E_STARTUP=bootstrap"
STARTUP_COMPILED = "SELF_E2E_STARTUP=compiled"
STARTUP_IMPORTED = "SELF_E2E_STARTUP=imported"
COMPILE_FAILED = "compile_failed"
IMPORT_FAILED = "import_failed"
HARNESS_PROTOCOL = "harness_protocol"
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


def terminal_harness_outcome(output: str) -> bool:
    """Startup lines are evidence of progress, not a harness result."""
    if "SELF_AUTHORED=PASS" in output.splitlines():
        return True
    for line in output.splitlines():
        if line.startswith(("SELF_E2E_BLOCKED=", "SELF_E2E_FAILED=")):
            return True
        prefix = "SELF_E2E_REMOTE_BLOCKED="
        if line.startswith(prefix) and line[len(prefix) :] in {
            "compile_failed",
            "import_failed",
            "harness_protocol",
        }:
            return True
    return False


def classify_child_output(output: str, returncode: int) -> tuple[str, int]:
    if terminal_harness_outcome(output):
        return output, returncode
    if "SELF_E2E_STARTUP=imported" in output.splitlines():
        return "SELF_E2E_REMOTE_BLOCKED=harness_protocol\n", 1
    return "SELF_E2E_REMOTE_BLOCKED=oneshot_failed\n", 1


def acceptance_bootstrap_source(helper_source: str) -> str:
    """Stdlib-only stdin entrypoint. It compiles and execs the helper in memory."""
    encoded = base64.b64encode(helper_source.encode("utf-8")).decode("ascii")
    return f"""import base64
import io
import sys
import types
from contextlib import redirect_stderr, redirect_stdout

HELPER_B64 = {encoded!r}


def _emit(line):
    sys.stdout.write(line + "\\n")
    sys.stdout.flush()


def _blocked(stage):
    _emit("SELF_E2E_REMOTE_BLOCKED=" + stage)
    raise SystemExit(1)


def _terminal(text):
    if "SELF_AUTHORED=PASS" in text.splitlines():
        return True
    for line in text.splitlines():
        if line.startswith("SELF_E2E_BLOCKED=") or line.startswith("SELF_E2E_FAILED="):
            return True
    return False


_emit({STARTUP_BOOTSTRAP!r})
try:
    compiled = compile(base64.b64decode(HELPER_B64).decode("utf-8"), "<helper>", "exec")
except Exception:
    _blocked({COMPILE_FAILED!r})
_emit({STARTUP_COMPILED!r})
imported = False
try:
    module = types.ModuleType("telegram_self_authored_e2e_helper")
    module.__name__ = "telegram_self_authored_e2e_helper"
    sys.modules[module.__name__] = module
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        exec(compiled, module.__dict__)
    if module.__name__ == "__main__" or not callable(getattr(module, "main", None)):
        raise RuntimeError
    imported = True
except BaseException:
    imported = False
if not imported:
    _blocked({IMPORT_FAILED!r})
_emit({STARTUP_IMPORTED!r})
captured = io.StringIO()
exit_code = None
try:
    with redirect_stdout(captured), redirect_stderr(io.StringIO()):
        result = module.main(["--live"])
    exit_code = result if isinstance(result, int) else None
except SystemExit as exc:
    exit_code = exc.code if isinstance(exc.code, int) else None
except BaseException:
    exit_code = None
held = captured.getvalue()
if exit_code is not None and _terminal(held):
    sys.stdout.write(held)
    raise SystemExit(exit_code)
_blocked({HARNESS_PROTOCOL!r})
"""


def acceptance_exec_command() -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        "/opt/secretary/.env",
        "-f",
        "infra/compose.yaml",
        "-f",
        "infra/compose.deploy.yaml",
        "exec",
        "-T",
        "-w",
        "/app",
        "-e",
        "SELF_E2E_CONFIRM=reviewed",
        "-e",
        "REHEARSAL_LONG_RUNNING_API_AI=false",
        "-e",
        "REHEARSAL_LONG_RUNNING_WORKER_AI=false",
        "api",
        "python3",
        "-B",
        "-",
    ]


def build_remote_program(helper_source: str) -> str:
    command = acceptance_exec_command()
    stdin_program = acceptance_bootstrap_source(helper_source)
    logic = (
        f"TRUE_FLAGS = {tuple(sorted(TRUE_FLAGS))!r}\n"
        + inspect.getsource(_flag_enabled)
        + "\n"
        + inspect.getsource(assess_remote_state)
        + "\n"
        + inspect.getsource(terminal_harness_outcome)
        + "\n"
        + inspect.getsource(classify_child_output)
    )
    return f"""import subprocess
import sys

{logic}
RELEASE = {PRODUCTION_RELEASE!r}
EXEC = {command!r}
STDIN_PROGRAM = {stdin_program!r}
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
    proc = subprocess.run(
        EXEC,
        input=STDIN_PROGRAM,
        cwd="/opt/secretary",
        text=True,
        capture_output=True,
        check=False,
    )
    output, code = classify_child_output(proc.stdout, proc.returncode)
    sys.stdout.write(output)
    raise SystemExit(code)
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
