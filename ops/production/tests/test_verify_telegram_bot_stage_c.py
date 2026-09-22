from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "verify_telegram_bot_stage_c.py"
SPEC = importlib.util.spec_from_file_location("stage_c", SOURCE)
verifier = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(verifier)
_ORIGINAL_OPENAPI = verifier._openapi_paths


def success() -> str:
    values = {
        "M4BR1_BEGIN": "true", "REMOTE_HEAD_PASS": "true", "REMOTE_PRODUCTION_REF_PASS": "true",
        "REMOTE_WORKTREE_CLEAN": "true", "DB_RUNNING_PASS": "true", "API_RUNNING_PASS": "true",
        "WORKER_RUNNING_PASS": "true", "DB_HEALTH_PASS": "true", "ALEMBIC_0046_PASS": "true",
        "APP_HEALTH_PASS": "true", "BOT_CONTAINER_ENV_ABSENT_PASS": "true",
        "MTPROTO_CREDENTIALS_PRESERVED_PASS": "true", "TELEGRAM_MTPROTO_AI_DISABLED_PASS": "true",
        "LEGACY_BOT_ROUTES_ABSENT_PASS": "true", "MTPROTO_ROUTE_PRESENT_PASS": "true",
        "BOT_SETTINGS_MODEL_ABSENT_PASS": "true", "MTPROTO_ACCOUNT_COUNT": "1",
        "ACTIVE_SCOPE_COUNT": "28", "LEGACY_BOT_OBJECT_COUNT": "3", "LEGACY_BOT_INBOX_READABLE": "true",
        "TELEGRAM_NETWORK_CALLS": "0", "DB_WRITES": "0", "ENV_WRITES": "0",
        "SERVICE_RECREATIONS": "0", "M4BR1_TERMINAL": "success", "M4BR1_END": "true",
    }
    return "\n".join(f"{key}={values[key]}" for key in verifier.SUCCESS_FIELDS) + "\n"


def failure() -> str:
    return "\n".join([  # noqa: FLY002
        "M4BR1_BEGIN=true", "FAILURE_STAGE=STAGE_2_READ_ONLY_STATE",
        "RAW_EXCEPTION_CLASS=RuntimeError", "TELEGRAM_NETWORK_CALLS=0", "DB_WRITES=0",
        "ENV_WRITES=0", "SERVICE_RECREATIONS=0", "M4BR1_TERMINAL=failure",
    ]) + "\n"


def test_protocol_accepts_success_and_sanitized_failure() -> None:
    assert verifier.parse_output(success()) == "success"
    assert verifier.parse_output(failure()) == "failure"


@pytest.mark.parametrize("bad", [
    success().replace("LEGACY_BOT_OBJECT_COUNT=3", "SECRET=leak\nLEGACY_BOT_OBJECT_COUNT=3"),
    success().replace("DB_WRITES=0", "DB_WRITES=1"),
    failure().replace("RAW_EXCEPTION_CLASS=RuntimeError", "RAW_EXCEPTION_CLASS=RuntimeError:secret"),
    failure().replace("M4BR1_TERMINAL=failure", "UNKNOWN=x\nM4BR1_TERMINAL=failure"),
    failure().replace("M4BR1_BEGIN=true", "M4BR1_BEGIN=true\nUNKNOWN_PASS=true"),
])
def test_protocol_rejects_unknown_or_unsafe_output(bad: str) -> None:
    with pytest.raises(ValueError):
        verifier.parse_output(bad)


def test_protocol_rejects_duplicate_and_out_of_order_fields() -> None:
    lines = success().splitlines()
    duplicate = "\n".join([lines[0], lines[1], *lines[1:]]) + "\n"
    swapped = lines[:]
    alembic = swapped.index("ALEMBIC_0046_PASS=true")
    health = swapped.index("APP_HEALTH_PASS=true")
    swapped[alembic], swapped[health] = swapped[health], swapped[alembic]
    for bad in (duplicate, "\n".join(swapped) + "\n"):
        with pytest.raises(ValueError):
            verifier.parse_output(bad)


def test_exact_release_and_target_contract() -> None:
    assert verifier.RELEASE == "bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b"
    target = verifier.load_target(ROOT / "target.json")
    assert target["origin_url"] == verifier.CANONICAL_ORIGIN
    assert target["repository_path"] == "/opt/secretary"


def test_authoritative_branch_accepts_exact_single_line(monkeypatch) -> None:
    monkeypatch.setattr(verifier, "_run", lambda _: "a" * 40 + "\trefs/heads/production")
    assert verifier.authoritative_branch("production", verifier.CANONICAL_ORIGIN) == "a" * 40


@pytest.mark.parametrize("output", [
    "a" * 40 + " refs/heads/production",
    "a" * 40 + "\trefs/heads/production\n" + "b" * 40 + "\trefs/heads/production",
    "A" * 40 + "\trefs/heads/production",
    "a" * 40 + "\trefs/heads/main",
    "",
])
def test_authoritative_branch_rejects_malformed_duplicate_or_unexpected(monkeypatch, output) -> None:
    monkeypatch.setattr(verifier, "_run", lambda _: output)
    with pytest.raises(ValueError):
        verifier.authoritative_branch("production", verifier.CANONICAL_ORIGIN)


@pytest.mark.parametrize("branch,origin", [
    ("../production", verifier.CANONICAL_ORIGIN),
    ("/production", verifier.CANONICAL_ORIGIN),
    ("bad branch", verifier.CANONICAL_ORIGIN),
    ("production", "origin"),
    ("production", "https://github.com/other/secretary.git"),
    ("production", ""),
])
def test_authoritative_branch_rejects_invalid_branch_or_noncanonical_url(branch, origin) -> None:
    with pytest.raises(ValueError):
        verifier.authoritative_branch(branch, origin)


def test_noncanonical_url_does_not_query_git(monkeypatch) -> None:
    def fail_if_called(_command):
        raise AssertionError("queried")

    monkeypatch.setattr(verifier, "_run", fail_if_called)
    with pytest.raises(ValueError):
        verifier.authoritative_branch("production", "https://github.com/other/secretary.git")


def test_authoritative_branch_uses_explicit_canonical_url(monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(verifier, "_run", lambda command: commands.append(command) or ("a" * 40 + "\trefs/heads/production"))
    verifier.authoritative_branch("production", verifier.CANONICAL_ORIGIN)
    assert commands == [["git", "ls-remote", verifier.CANONICAL_ORIGIN, "refs/heads/production"]]
    assert commands[0][2] != "origin"


def test_remote_wrong_origin_stops_before_authoritative_lookup(monkeypatch, capsys) -> None:
    commands = []

    def fake_run(command):
        commands.append(command)
        if command == ["git", "remote", "get-url", "origin"]:
            return "https://github.com/other/secretary.git"
        raise AssertionError(command)

    monkeypatch.setattr(verifier, "_run", fake_run)
    assert verifier.remote_main() == 2
    output = capsys.readouterr().out
    assert "FAILURE_STAGE=STAGE_0_CANONICAL_REPO" in output
    assert not any(command[:2] == ["git", "ls-remote"] for command in commands)
    assert not any(command[:2] == ["docker", "compose"] for command in commands)


def test_remote_authoritative_mismatch_stops_before_runtime(monkeypatch, capsys) -> None:
    commands = []

    def fake_run(command):
        commands.append(command)
        if command == ["git", "remote", "get-url", "origin"]:
            return verifier.CANONICAL_ORIGIN
        if command == ["git", "rev-parse", "HEAD"]:
            return verifier.RELEASE
        if command == ["git", "ls-remote", verifier.CANONICAL_ORIGIN, "refs/heads/production"]:
            return "0" * 40 + "\trefs/heads/production"
        raise AssertionError(command)

    monkeypatch.setattr(verifier, "_run", fake_run)
    assert verifier.remote_main() == 2
    output = capsys.readouterr().out
    assert "FAILURE_STAGE=STAGE_0_PRODUCTION_REF" in output
    assert commands[0] == ["git", "remote", "get-url", "origin"]
    assert ["git", "ls-remote", verifier.CANONICAL_ORIGIN, "refs/heads/production"] in commands
    assert not any(command[:2] == ["docker", "compose"] for command in commands)


def test_remote_dirty_worktree_stops_before_runtime(monkeypatch, capsys) -> None:
    def fake_run(command):
        if command == ["git", "remote", "get-url", "origin"]:
            return verifier.CANONICAL_ORIGIN
        if command == ["git", "rev-parse", "HEAD"]:
            return verifier.RELEASE
        if command == ["git", "ls-remote", verifier.CANONICAL_ORIGIN, "refs/heads/production"]:
            return verifier.RELEASE + "\trefs/heads/production"
        if command == ["git", "status", "--porcelain"]:
            return " M file"
        raise AssertionError(command)

    monkeypatch.setattr(verifier, "_run", fake_run)
    assert verifier.remote_main() == 2
    assert "FAILURE_STAGE=STAGE_0_WORKTREE" in capsys.readouterr().out


def test_bundle_compiles_and_remote_entrypoint_exists() -> None:
    result = subprocess.run(["python3", str(SOURCE), "bundle"], capture_output=True, text=True, check=True)
    compile(result.stdout, "<bundle>", "exec")
    assert "def remote_main" in result.stdout


def test_source_is_read_only_and_has_no_provider_capability() -> None:
    text = SOURCE.read_text()
    for forbidden in ("deleteWebhook", "getWebhookInfo", "api.telegram.org", ".flush(", ".commit(", "os.replace", "reconcile_scope", "fetch_history"):
        assert forbidden not in text
    assert "SERVICE_RECREATIONS" in text and "DB_WRITES" in text and "ENV_WRITES" in text


def test_no_tracking_ref_or_production_fetch_dependency_remains() -> None:
    text = SOURCE.read_text()
    wrapper = (ROOT / "verify_telegram_bot_stage_c.sh").read_text()
    for forbidden in ("origin/production", "fetch", "checkout", "reset", 'ls-remote", "origin"'):
        assert forbidden not in text
        assert forbidden not in wrapper
    assert '["git", "ls-remote", origin_url, f"refs/heads/{branch}"]' in text
    assert 'authoritative main "$ORIGIN"' in wrapper
    assert 'authoritative production "$ORIGIN"' in wrapper
    markers = (
        'target "$TARGET"',
        "rev-parse --show-toplevel",
        "branch --show-current",
        "status --porcelain",
        "remote get-url origin",
        'authoritative main "$ORIGIN"',
        "rev-parse HEAD",
        'authoritative production "$ORIGIN"',
            "ssh-keyscan -t",
    )
    positions = [wrapper.index(marker) for marker in markers]
    assert positions == sorted(positions)


def test_child_uses_generic_read_and_aggregate_only() -> None:
    text = SOURCE.read_text()
    assert "RecentSourceService" in text
    assert "LEGACY_BOT_OBJECT_COUNT" in text
    assert "Object.metadata_[\"transport\"]" in text
    assert "ObjectOut" not in text
    assert "order_by(Object.created_at.asc(), Object.id.asc())" in text
    assert ".limit(1000)" in text


def test_first_ineligible_candidate_does_not_mask_later_eligible_candidate() -> None:
    candidates = ["hidden", "visible"]
    assert verifier._has_eligible_candidate(candidates, lambda value: value == "visible") is True


def test_no_eligible_candidate_is_false() -> None:
    assert verifier._has_eligible_candidate(["hidden", "deleted"], lambda _value: False) is False


def test_read_check_does_not_emit_identifiers_or_content() -> None:
    text = SOURCE.read_text()
    assert "print(candidate.id" not in text
    assert "print(candidate.body" not in text
    assert "print(candidate.title" not in text


def test_health_retries_bounded_then_succeeds() -> None:
    attempts = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): return False
    def request(*_args, **_kwargs):
        attempts.append(1)
        if len(attempts) < 4:
            raise OSError("unavailable")
        return Response()
    sleeps = []
    verifier._health("http://127.0.0.1:18080/health", attempts=30, delay=2, request=request, sleeper=sleeps.append)
    assert len(attempts) == 4 and sleeps == [2, 2, 2]


def test_health_exhausts_at_most_thirty_attempts() -> None:
    attempts = []
    def request(*_args, **_kwargs):
        attempts.append(1)
        raise OSError("unavailable")
    with pytest.raises(RuntimeError):
        verifier._health("http://127.0.0.1:18080/health", request=request, sleeper=lambda _: None)
    assert len(attempts) == 30


def test_alembic_requires_exact_head(monkeypatch) -> None:
    monkeypatch.setattr(verifier, "_run", lambda _: "0046 (head)")
    verifier._require_alembic(["docker", "compose"])
    monkeypatch.setattr(verifier, "_run", lambda _: "0046")
    with pytest.raises(RuntimeError):
        verifier._require_alembic(["docker", "compose"])


def test_child_output_is_strict(monkeypatch) -> None:
    ok = "CHILD_STATUS=ok\nMTPROTO_ACCOUNT_COUNT=1\nACTIVE_SCOPE_COUNT=28\nLEGACY_BOT_OBJECT_COUNT=2\nLEGACY_BOT_INBOX_READABLE=true"
    monkeypatch.setattr(verifier, "_run", lambda _: ok)
    assert verifier._child(["docker", "compose"])["ACTIVE_SCOPE_COUNT"] == "28"
    monkeypatch.setattr(verifier, "_run", lambda _: "MTPROTO_ACCOUNT_COUNT=1\nSECRET=leak-id")
    with pytest.raises(verifier.VerifyError) as caught:
        verifier._child(["docker", "compose"])
    assert caught.value.stage == "STAGE_2_CHILD_PROTOCOL"


def test_cli_authoritative_requires_explicit_canonical_url(monkeypatch, capsys) -> None:
    seen = {}

    def fake(branch, origin):
        if origin != verifier.CANONICAL_ORIGIN:
            raise ValueError("invalid origin")
        seen["branch"] = branch
        seen["origin"] = origin
        return "c" * 40

    monkeypatch.setattr(verifier, "authoritative_branch", fake)
    monkeypatch.setattr("sys.argv", ["verify", "authoritative", "main", verifier.CANONICAL_ORIGIN])
    assert verifier.main() == 0
    assert capsys.readouterr().out.strip() == "c" * 40
    assert seen == {"branch": "main", "origin": verifier.CANONICAL_ORIGIN}
    monkeypatch.setattr("sys.argv", ["verify", "authoritative", "main"])
    assert verifier.main() == 2


def _install(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run_wrapper(tmp_path: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    bindir = tmp_path / "bin"
    if bindir.exists():
        shutil.rmtree(bindir)
    bindir.mkdir()
    log = tmp_path / "log"
    log.write_text("", encoding="utf-8")
    _install(bindir / "git", """#!/bin/bash
set -eu
printf 'git %s\\n' "$*" >> "$WRAPPER_LOG"
joined="$*"
case "$joined" in
  *fetch*|*reset*|*checkout*|*origin/production*|*origin/main*) exit 9 ;;
esac
if [ "$1" = "-C" ]; then root="$2"; shift 2; else root=""; fi
case "$*" in
  "rev-parse --show-toplevel")
    if [ "${TOPLEVEL_OK:-1}" = 1 ]; then printf '%s\\n' "$root"; else printf '%s\\n' /wrong; fi ;;
  "branch --show-current") printf '%s\\n' "${BRANCH_NAME:-main}" ;;
  "status --porcelain") printf '%s' "${PORCELAIN:-}" ;;
  "remote get-url origin") printf '%s\\n' "$LOCAL_ORIGIN" ;;
  "rev-parse HEAD") printf '%s\\n' "$HEAD_SHA" ;;
  *) exit 4 ;;
esac
""")
    _install(bindir / "python3", """#!/bin/bash
set -eu
printf 'python %s\\n' "$*" >> "$WRAPPER_LOG"
case "${2:-}" in
  target)
    printf '%s\\n' 'git@host' '22' 'SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' '/opt/secretary' "$CANONICAL_ORIGIN" ;;
  release) printf '%s\\n' "$RELEASE" ;;
  bundle) printf '%s\\n' '# bundle' ;;
  validate) "$REAL_PYTHON" "$1" validate "$3" ;;
  authoritative)
    [ "${4:-}" = "$CANONICAL_ORIGIN" ] || exit 2
    if [ "${3:-}" = main ]; then printf '%s\\n' "$MAIN_SHA"
    elif [ "${3:-}" = production ]; then printf '%s\\n' "$PROD_SHA"
    else exit 2; fi ;;
  *) exit 2 ;;
esac
""")
    _install(bindir / "ssh-keyscan", """#!/bin/bash
printf 'ssh-keyscan %s\n' "$*" >> "$WRAPPER_LOG"
if [ "${KEYSCAN_OK:-0}" = 1 ]; then printf '%s\n' 'host ssh-ed25519 AAAA'; exit 0; fi
exit 1
""")
    _install(bindir / "ssh-keygen", """#!/bin/bash
printf 'ssh-keygen %s\n' "$*" >> "$WRAPPER_LOG"
if [ "${KEYSCAN_OK:-0}" = 1 ]; then printf '%s\n' '256 SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA dummy'; exit 0; fi
exit 1
""")
    _install(bindir / "ssh", """#!/bin/bash
printf 'ssh %s\n' "$*" >> "$WRAPPER_LOG"
printf '%s\n' 'STDERR_SECRET_SHOULD_NOT_APPEAR' >&2
if [ -n "${SSH_STDOUT_FILE:-}" ]; then cat "$SSH_STDOUT_FILE"; fi
exit "${SSH_RC:-1}"
""")
    env = os.environ.copy()
    env.update({
        "PATH": f"{bindir}:{env.get('PATH', '')}",
        "REAL_PYTHON": shutil.which("python3") or "python3",
        "WRAPPER_LOG": str(log),
        "CANONICAL_ORIGIN": verifier.CANONICAL_ORIGIN,
        "RELEASE": verifier.RELEASE,
        "LOCAL_ORIGIN": verifier.CANONICAL_ORIGIN,
        "HEAD_SHA": "1" * 40,
        "MAIN_SHA": "1" * 40,
        "PROD_SHA": verifier.RELEASE,
        "TOPLEVEL_OK": "1",
        "BRANCH_NAME": "main",
        "PORCELAIN": "",
    })
    env.update(overrides)
    return subprocess.run(
        ["bash", str(ROOT / "verify_telegram_bot_stage_c.sh")],
        capture_output=True, text=True, env=env, check=False,
    )


def _log(tmp_path: Path) -> str:
    return (tmp_path / "log").read_text(encoding="utf-8")


def test_wrapper_wrong_origin_fails_before_branch_lookup_and_ssh(tmp_path) -> None:
    result = _run_wrapper(tmp_path, LOCAL_ORIGIN="https://github.com/other/secretary.git")
    assert result.returncode == 2
    assert result.stdout.strip() == "M4BR1_BLOCKED=wrong_local_origin"
    lines = _log(tmp_path).splitlines()
    assert all("authoritative" not in line for line in lines)
    assert all(not line.startswith("ssh") for line in lines)
    target_at = next(i for i, line in enumerate(lines) if line.startswith("python ") and " target " in f" {line} ")
    origin_at = next(i for i, line in enumerate(lines) if "remote get-url origin" in line)
    assert target_at < origin_at


def test_wrapper_stale_main_and_production_mismatch_stop_before_ssh(tmp_path) -> None:
    stale = _run_wrapper(tmp_path, HEAD_SHA="2" * 40, MAIN_SHA="1" * 40)
    assert stale.returncode == 2
    assert stale.stdout.strip() == "M4BR1_BLOCKED=local_main_stale"
    stale_log = _log(tmp_path)
    assert "authoritative main" in stale_log
    assert "authoritative production" not in stale_log
    assert "ssh-keyscan" not in stale_log
    mismatch = _run_wrapper(tmp_path, PROD_SHA="0" * 40)
    assert mismatch.returncode == 2
    assert mismatch.stdout.strip() == "M4BR1_BLOCKED=local_production_ref"
    assert "ssh-keyscan" not in _log(tmp_path)
    assert "origin/production" not in _log(tmp_path)


def test_wrapper_ignores_tracking_refs_and_reaches_pin_without_mutation(tmp_path) -> None:
    result = _run_wrapper(tmp_path)
    assert result.returncode == 2
    assert result.stdout.strip() == "M4BR1_BLOCKED=host_key_pin_mismatch"
    log = _log(tmp_path)
    assert f"authoritative main {verifier.CANONICAL_ORIGIN}" in log
    assert f"authoritative production {verifier.CANONICAL_ORIGIN}" in log
    for forbidden in ("fetch", "origin/production", "origin/main", "reset", "checkout"):
        assert forbidden not in log
    assert "ssh-keyscan" in log
    assert "\nssh " not in f"\n{log}"


RUNTIME_ENV = {
    "TELEGRAM_API_ID": "1",
    "TELEGRAM_API_HASH": "hash",
    "SECRETARY_CREDENTIAL_KEY": "key",
    "POSTGRES_PASSWORD": "pw",
    "TELEGRAM_MTPROTO_AI_ENABLED": "false",
}
CHILD_SUCCESS = (
    "CHILD_STATUS=ok\n"
    "MTPROTO_ACCOUNT_COUNT=1\n"
    "ACTIVE_SCOPE_COUNT=28\n"
    "LEGACY_BOT_OBJECT_COUNT=3\n"
    "LEGACY_BOT_INBOX_READABLE=true"
)


def _dotenv(*, empty_bot: bool) -> str:
    lines = [f"{key}=" for key in verifier.BOT_KEYS] if empty_bot else []
    lines.extend(f"{key}={value}" for key, value in RUNTIME_ENV.items())
    return "\n".join(lines) + "\n"


def _drive_remote(monkeypatch, capsys, *, dotenv: str, service_env: dict | None = None, service_envs: dict | None = None, container_env: dict, health_error: bool = False, child: str = CHILD_SUCCESS, child_crash: bool = False, openapi_paths: dict | None = None, openapi_mode: str = "ok", settings_out: str = "CHILD_STATUS=ok\n", settings_crash: bool = False):
    if service_envs is None:
        service_envs = {"api": service_env, "worker": service_env}
    config = {"services": {name: {"environment": values} for name, values in service_envs.items()}}

    def fake_run(command):
        if command == ["git", "remote", "get-url", "origin"]:
            return verifier.CANONICAL_ORIGIN
        if command == ["git", "rev-parse", "HEAD"]:
            return verifier.RELEASE
        if command == ["git", "ls-remote", verifier.CANONICAL_ORIGIN, "refs/heads/production"]:
            return verifier.RELEASE + "\trefs/heads/production"
        if command == ["git", "status", "--porcelain"]:
            return ""
        if command[-3:] == ["config", "--format", "json"]:
            return json.dumps(config)
        if command[-3:-1] == ["ps", "-q"]:
            return f"{command[-1]}id"
        if command[:3] == ["docker", "inspect", "-f"] and ".State" in command[3]:
            if command[4] == "dbid":
                return json.dumps({"Status": "running", "Health": {"Status": "healthy"}})
            return json.dumps({"Status": "running"})
        if command[:3] == ["docker", "inspect", "-f"] and ".Config.Env" in command[3]:
            return json.dumps(container_env[command[4]])
        if command[-2:] == ["alembic", "current"]:
            return "0046 (head)"
        if len(command) >= 2 and command[-2] == "-c":
            script = command[-1]
            if script == verifier.SETTINGS_CHILD:
                if settings_crash:
                    raise RuntimeError("settings died secret")
                return settings_out
            if script == verifier.DB_CHILD:
                if child_crash:
                    raise RuntimeError("container died secret traceback")
                return child
            raise AssertionError(script)
        raise AssertionError(command)

    def fake_read(self, encoding="utf-8", errors=None):
        if self.name == ".env":
            return dotenv
        return Path.read_text(self, encoding=encoding, errors=errors)

    class Response:
        def __init__(self, status: int, body: bytes) -> None:
            self.status = status
            self._body = body
        def read(self) -> bytes:
            return self._body
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False

    def fake_request(_url, timeout=5):
        del timeout
        if openapi_mode == "down":
            raise OSError("openapi down")
        if openapi_mode == "bad":
            return Response(200, b"not-json")
        paths = {"/telegram/mtproto/status": {}} if openapi_paths is None else openapi_paths
        return Response(200, json.dumps({"paths": paths}).encode())

    def patched_openapi():
        return _ORIGINAL_OPENAPI(request=fake_request, sleeper=lambda _delay: None, attempts=2)
    monkeypatch.setattr(verifier, "_run", fake_run)
    monkeypatch.setattr(verifier, "_openapi_paths", patched_openapi)
    monkeypatch.setattr(verifier.Path, "read_text", fake_read)
    if health_error:
        def fail_health(*_args, **_kwargs):
            raise RuntimeError("health check exhausted")
        monkeypatch.setattr(verifier, "_health", fail_health)
    else:
        monkeypatch.setattr(verifier, "_health", lambda *_args, **_kwargs: None)
    code = verifier.remote_main()
    return code, capsys.readouterr().out


def _keys(text: str) -> list[str]:
    return [line.split("=", 1)[0] for line in text.splitlines()]


@pytest.mark.parametrize("empty_bot", [True, False])
def test_remote_success_transcript_matches_parser_order(monkeypatch, capsys, empty_bot) -> None:
    lines = [f"{key}={value}" for key, value in RUNTIME_ENV.items()]
    code, stdout = _drive_remote(
        monkeypatch, capsys, dotenv=_dotenv(empty_bot=empty_bot),
        service_env=dict(RUNTIME_ENV), container_env={"apiid": lines, "workerid": lines},
    )
    assert code == 0
    assert _keys(stdout) == list(verifier.SUCCESS_FIELDS)
    assert verifier.parse_output(stdout) == "success"
    assert len(verifier.RELEASE) == 40


def test_remote_app_health_failure_after_alembic_is_valid(monkeypatch, capsys) -> None:
    lines = [f"{key}={value}" for key, value in RUNTIME_ENV.items()]
    code, stdout = _drive_remote(
        monkeypatch, capsys, dotenv=_dotenv(empty_bot=True), health_error=True,
        service_env=dict(RUNTIME_ENV), container_env={"apiid": lines, "workerid": lines},
    )
    assert code == 2
    assert verifier.parse_output(stdout) == "failure"
    assert "FAILURE_STAGE=STAGE_0_APP_HEALTH" in stdout
    assert stdout.index("ALEMBIC_0046_PASS=true") < stdout.index("FAILURE_STAGE=")
    assert "APP_HEALTH_PASS" not in stdout


def test_remote_environment_failure_after_health_is_valid(monkeypatch, capsys) -> None:
    present = {**RUNTIME_ENV, "TELEGRAM_BOT_TOKEN": ""}
    lines = [f"{key}={value}" for key, value in RUNTIME_ENV.items()]
    code, stdout = _drive_remote(
        monkeypatch, capsys, dotenv=_dotenv(empty_bot=True),
        service_env=present, container_env={"apiid": lines, "workerid": lines},
    )
    assert code == 2
    assert verifier.parse_output(stdout) == "failure"
    assert "FAILURE_STAGE=STAGE_1_ENVIRONMENT" in stdout
    assert "APP_HEALTH_PASS=true" in stdout
    assert "BOT_CONTAINER_ENV_ABSENT_PASS" not in stdout


def test_remote_child_failure_after_environment_markers_is_valid(monkeypatch, capsys) -> None:
    lines = [f"{key}={value}" for key, value in RUNTIME_ENV.items()]
    child = CHILD_SUCCESS.replace("MTPROTO_ACCOUNT_COUNT=1", "MTPROTO_ACCOUNT_COUNT=2")
    code, stdout = _drive_remote(
        monkeypatch, capsys, dotenv=_dotenv(empty_bot=True), child=child,
        service_env=dict(RUNTIME_ENV), container_env={"apiid": lines, "workerid": lines},
    )
    assert code == 2
    assert verifier.parse_output(stdout) == "failure"
    assert "FAILURE_STAGE=STAGE_2_ACCOUNT" in stdout
    assert "BOT_SETTINGS_MODEL_ABSENT_PASS=true" in stdout
    assert "MTPROTO_ACCOUNT_COUNT" not in stdout
    assert "=2" not in stdout


@pytest.mark.parametrize("service", ["api", "worker"])
def test_present_empty_bot_key_fails_in_compose_and_container(monkeypatch, capsys, service) -> None:
    clean = dict(RUNTIME_ENV)
    present = {**RUNTIME_ENV, "TELEGRAM_BOT_TOKEN": ""}
    lines = [f"{key}={value}" for key, value in RUNTIME_ENV.items()]
    compose = {"api": dict(clean), "worker": dict(clean)}
    compose[service] = present
    code, stdout = _drive_remote(
        monkeypatch, capsys, dotenv=_dotenv(empty_bot=True),
        service_envs=compose, container_env={"apiid": lines, "workerid": lines},
    )
    assert code == 2
    assert verifier.parse_output(stdout) == "failure"
    assert "FAILURE_STAGE=STAGE_1_ENVIRONMENT" in stdout
    containers = {"apiid": list(lines), "workerid": list(lines)}
    containers[f"{service}id"] = [*lines, "TELEGRAM_BOT_TOKEN="]
    code, stdout = _drive_remote(
        monkeypatch, capsys, dotenv=_dotenv(empty_bot=True),
        service_envs={"api": dict(clean), "worker": dict(clean)}, container_env=containers,
    )
    assert code == 2
    assert verifier.parse_output(stdout) == "failure"
    assert "FAILURE_STAGE=STAGE_1_ENVIRONMENT" in stdout


def test_bot_env_helpers_distinguish_legacy_file_from_runtime_absence() -> None:
    empty = {key: "" for key in verifier.BOT_KEYS}
    verifier._legacy_bot_lines_absent_or_empty({})
    verifier._legacy_bot_lines_absent_or_empty(empty)
    with pytest.raises(ValueError, match="nonempty"):
        verifier._legacy_bot_lines_absent_or_empty({"TELEGRAM_BOT_TOKEN": "x"})
    verifier._bot_keys_absent({})
    verifier._bot_keys_absent(dict(RUNTIME_ENV))
    with pytest.raises(ValueError, match="present"):
        verifier._bot_keys_absent({"TELEGRAM_BOT_TOKEN": ""})
    listed = verifier._service_env(
        {"services": {"api": {"environment": ["TELEGRAM_BOT_TOKEN=", *(f"{key}={value}" for key, value in RUNTIME_ENV.items())]}}},
        "api",
    )
    with pytest.raises(ValueError, match="present"):
        verifier._bot_keys_absent(listed)


def _install_child_modules(**options: object) -> list[str]:
    names = [
        "sqlalchemy", "app", "app.core", "app.core.config", "app.db", "app.db.models",
        "app.db.session", "app.main", "app.services", "app.services.recent_source_service",
    ]

    class Col:
        def __eq__(self, _other): return self
        def __ne__(self, _other): return self
        def is_(self, _other): return self
        def as_string(self): return self
        def __getitem__(self, _key): return self
        def asc(self): return self

    class Query:
        def select_from(self, *_args, **_kwargs): return self
        def where(self, *_args, **_kwargs): return self
        def order_by(self, *_args, **_kwargs): return self
        def limit(self, *_args, **_kwargs): return self

    class Func:
        def count(self): return "count"

    def pkg(name: str) -> types.ModuleType:
        module = types.ModuleType(name)
        module.__path__ = []  # type: ignore[attr-defined]
        module.__package__ = name.rpartition(".")[0]
        sys.modules[name] = module
        if "." in name:
            parent, _, child = name.rpartition(".")
            setattr(sys.modules[parent], child, module)
        return module

    sa = pkg("sqlalchemy")
    sa.func = Func()
    sa.or_ = lambda *_args: "or"  # type: ignore[attr-defined]
    sa.select = lambda *_args, **_kwargs: Query()  # type: ignore[attr-defined]
    pkg("app")
    pkg("app.db")
    models = pkg("app.db.models")
    for model_name in ("Object", "TelegramMtprotoAccount", "TelegramMtprotoChatSelection"):
        model = type(model_name, (), {})
        for attr in ("provider", "kind", "metadata_", "created_at", "id", "scope_active"):
            setattr(model, attr, Col())
        setattr(models, model_name, model)
    session_mod = pkg("app.db.session")
    values = list(options.get("scalar_values", [1, 28, 3]))

    class Session:
        def __init__(self) -> None:
            self.calls = 0

        def scalar(self, _statement):
            self.calls += 1
            if options.get("scalar_raise_at") == self.calls:
                raise RuntimeError("sql secret id=99")
            return values[self.calls - 1]

        def scalars(self, _statement):
            if options.get("scalars_raise"):
                raise RuntimeError("candidate sql secret")
            return options.get("rows", [types.SimpleNamespace(user_id="user-secret", id="object-secret")])

        def close(self) -> None:
            return None

    def session_local():
        if options.get("session_raise"):
            raise RuntimeError("session secret")
        return Session()

    session_mod.SessionLocal = session_local
    pkg("app.services")
    service = pkg("app.services.recent_source_service")

    class RecentSourceService:
        def __init__(self, _session, user_id) -> None:
            self.user_id = user_id

        def get_inbox_eligible(self, object_id):
            if options.get("inbox_raise"):
                raise RuntimeError(f"inbox secret {object_id}")
            return object() if options.get("readable", True) else None

    service.RecentSourceService = RecentSourceService
    return names


def _run_child_script(**options: object) -> str:
    names = [
        "sqlalchemy", "app", "app.db", "app.db.models", "app.db.session",
        "app.services", "app.services.recent_source_service",
    ]
    saved = {name: sys.modules.get(name) for name in names}
    for name in names:
        sys.modules.pop(name, None)
    blocked = {
        "sqlalchemy": "sqlalchemy",
        "models": "app.db.models",
        "session": "app.db.session",
        "recent": "app.services.recent_source_service",
    }.get(str(options.get("block") or ""))
    try:
        if options.get("block") != "sqlalchemy":
            _install_child_modules(**options)
        if blocked:
            sys.modules[blocked] = None
        main_before = "app.main" in sys.modules
        config_before = "app.core.config" in sys.modules
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exec(compile(verifier.DB_CHILD, "<db-child>", "exec"), {"__name__": "child"})  # noqa: S102
        if (not main_before and "app.main" in sys.modules) or (not config_before and "app.core.config" in sys.modules):
            raise AssertionError("narrow db child imported a forbidden module")
        return buffer.getvalue()
    finally:
        for name in names:
            sys.modules.pop(name, None)
            if saved[name] is not None:
                sys.modules[name] = saved[name]


@pytest.mark.parametrize(("options", "stage", "leaks"), [
    ({"block": "sqlalchemy"}, "STAGE_2_SQLALCHEMY", []),
    ({"block": "models"}, "STAGE_2_MODELS", []),
    ({"block": "session"}, "STAGE_2_DB_SESSION", []),
    ({"block": "recent"}, "STAGE_2_RECENT_SOURCE", []),
    ({"session_raise": True}, "STAGE_2_DB_SESSION", ["session secret"]),
    ({"scalar_raise_at": 1}, "STAGE_2_ACCOUNT", ["sql secret", "id=99"]),
    ({"scalar_values": [2]}, "STAGE_2_ACCOUNT", ["object-secret"]),
    ({"scalar_raise_at": 2}, "STAGE_2_SCOPE", ["sql secret"]),
    ({"scalar_values": [1, 27]}, "STAGE_2_SCOPE", []),
    ({"scalar_raise_at": 3}, "STAGE_2_LEGACY_AGGREGATE", ["sql secret"]),
    ({"scalar_values": [1, 28, 0]}, "STAGE_2_LEGACY_AGGREGATE", []),
    ({"scalars_raise": True}, "STAGE_2_LEGACY_CANDIDATES", ["candidate sql secret"]),
    ({"inbox_raise": True}, "STAGE_2_INBOX_READ", ["inbox secret", "object-secret"]),
    ({"readable": False, "scalar_values": [1, 28, 2]}, "STAGE_2_INBOX_READ", ["object-secret", "user-secret"]),
    ({"readable": False, "scalar_values": [1, 28, 1001], "rows": []}, "STAGE_2_CANDIDATE_BOUND", []),
])
def test_each_stage2_failure_reaches_remote_transcript(monkeypatch, capsys, options, stage, leaks) -> None:
    child_out = _run_child_script(**options)
    assert child_out == f"CHILD_STATUS=fail\nCHILD_STAGE={stage}\n"
    for leak in leaks:
        assert leak not in child_out
    lines = [f"{key}={value}" for key, value in RUNTIME_ENV.items()]
    code, stdout = _drive_remote(
        monkeypatch, capsys, dotenv=_dotenv(empty_bot=True), child=child_out,
        service_env=dict(RUNTIME_ENV), container_env={"apiid": lines, "workerid": lines},
    )
    assert code == 2
    assert verifier.parse_output(stdout) == "failure"
    assert f"FAILURE_STAGE={stage}\n" in stdout
    assert "BOT_SETTINGS_MODEL_ABSENT_PASS=true" in stdout
    assert "MTPROTO_ROUTE_PRESENT_PASS=true" in stdout
    for leak in (*leaks, "CHILD_STAGE", "MTPROTO_ACCOUNT_COUNT", "ACTIVE_SCOPE_COUNT", "LEGACY_BOT_OBJECT_COUNT"):
        assert leak not in stdout


def test_db_child_source_has_no_monolithic_bootstrap() -> None:
    text = verifier.DB_CHILD
    assert "from app.main import app" not in text
    assert "app.main" not in text
    assert "Settings" not in text
    assert "STAGE_2_BOOTSTRAP" not in SOURCE.read_text()


def test_openapi_and_settings_failures_have_distinct_transcripts(monkeypatch, capsys) -> None:
    lines = [f"{key}={value}" for key, value in RUNTIME_ENV.items()]
    common = {"dotenv": _dotenv(empty_bot=True), "service_env": dict(RUNTIME_ENV), "container_env": {"apiid": lines, "workerid": lines}}
    cases = [
        ({"openapi_mode": "down"}, "STAGE_2_OPENAPI_FETCH", "LEGACY_BOT_ROUTES_ABSENT_PASS"),
        ({"openapi_mode": "bad"}, "STAGE_2_OPENAPI_PROTOCOL", "LEGACY_BOT_ROUTES_ABSENT_PASS"),
        ({"openapi_paths": {"/telegram/link": {}, "/telegram/mtproto/status": {}}}, "STAGE_2_LEGACY_ROUTES", "LEGACY_BOT_ROUTES_ABSENT_PASS"),
        ({"openapi_paths": {"/integrations/telegram/webhook": {}}}, "STAGE_2_LEGACY_ROUTES", "LEGACY_BOT_ROUTES_ABSENT_PASS"),
        ({"openapi_paths": {}}, "STAGE_2_MTPROTO_ROUTE", "MTPROTO_ROUTE_PRESENT_PASS"),
        ({"settings_out": "CHILD_STATUS=fail\nCHILD_STAGE=STAGE_2_BOT_SETTINGS\n"}, "STAGE_2_BOT_SETTINGS", "BOT_SETTINGS_MODEL_ABSENT_PASS"),
        ({"settings_out": "SECRET=value\n"}, "STAGE_2_SETTINGS_PROTOCOL", "BOT_SETTINGS_MODEL_ABSENT_PASS"),
        ({"settings_crash": True}, "STAGE_2_SETTINGS_EXECUTION", "BOT_SETTINGS_MODEL_ABSENT_PASS"),
    ]
    for kwargs, stage, absent in cases:
        code, stdout = _drive_remote(monkeypatch, capsys, **common, **kwargs)
        assert code == 2
        assert verifier.parse_output(stdout) == "failure"
        assert f"FAILURE_STAGE={stage}\n" in stdout
        assert absent not in stdout
        assert "SECRET" not in stdout
        assert "/telegram/" not in stdout


def test_settings_child_rejects_bot_field_without_leaking_values() -> None:
    saved = sys.modules.get("app.core.config")
    module = types.ModuleType("app.core.config")

    class Settings:
        pass

    Settings.model_fields = {"telegram_bot_token": "must-not-leak"}
    module.Settings = Settings
    sys.modules["app.core.config"] = module
    try:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exec(compile(verifier.SETTINGS_CHILD, "<settings-child>", "exec"), {"__name__": "settings"})  # noqa: S102
        text = buffer.getvalue()
    finally:
        if saved is None:
            sys.modules.pop("app.core.config", None)
        else:
            sys.modules["app.core.config"] = saved
    assert text == "CHILD_STATUS=fail\nCHILD_STAGE=STAGE_2_BOT_SETTINGS\n"
    assert "must-not-leak" not in text


def test_actual_backend_package_imports_without_app_main_or_db_connection() -> None:
    backend = Path(__file__).resolve().parents[3] / "backend"
    script = """
import sys
from app.core.config import Settings
forbidden = {"telegram_bot_token", "telegram_bot_username", "telegram_webhook_secret", "telegram_webhook_url"}
assert not forbidden & set(Settings.model_fields)
from sqlalchemy import func, or_, select
from app.db.models import Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection
from app.db.session import SessionLocal
from app.services.recent_source_service import RecentSourceService
assert "app.main" not in sys.modules
assert SessionLocal is not None and RecentSourceService is not None
assert Object is not None and TelegramMtprotoAccount is not None and TelegramMtprotoChatSelection is not None
assert callable(func.count) and callable(select)
print("SMOKE_OK")
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-c", script], cwd=backend, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SMOKE_OK"


def test_child_success_protocol_has_no_identifiers() -> None:
    text = _run_child_script()
    assert text == (
        "CHILD_STATUS=ok\nMTPROTO_ACCOUNT_COUNT=1\nACTIVE_SCOPE_COUNT=28\n"
        "LEGACY_BOT_OBJECT_COUNT=3\nLEGACY_BOT_INBOX_READABLE=true\n"
    )
    assert "object-secret" not in text
    assert "user-secret" not in text


def test_malformed_child_output_and_crash_are_fixed_stage2_codes(monkeypatch, capsys) -> None:
    lines = [f"{key}={value}" for key, value in RUNTIME_ENV.items()]
    code, stdout = _drive_remote(
        monkeypatch, capsys, dotenv=_dotenv(empty_bot=True),
        child="SELECT secret-id FROM objects\n",
        service_env=dict(RUNTIME_ENV), container_env={"apiid": lines, "workerid": lines},
    )
    assert code == 2
    assert verifier.parse_output(stdout) == "failure"
    assert "FAILURE_STAGE=STAGE_2_CHILD_PROTOCOL" in stdout
    assert "secret-id" not in stdout
    assert "SELECT" not in stdout
    code, stdout = _drive_remote(
        monkeypatch, capsys, dotenv=_dotenv(empty_bot=True), child_crash=True,
        service_env=dict(RUNTIME_ENV), container_env={"apiid": lines, "workerid": lines},
    )
    assert code == 2
    assert verifier.parse_output(stdout) == "failure"
    assert "FAILURE_STAGE=STAGE_2_CHILD_EXECUTION" in stdout
    assert "secret traceback" not in stdout
    assert "container died" not in stdout


def _remote_failure_transcript(stage: str = "STAGE_2_OPENAPI_FETCH") -> str:
    prefix = []
    for key in verifier.SUCCESS_FIELDS:
        if key == "LEGACY_BOT_ROUTES_ABSENT_PASS":
            break
        prefix.append(f"{key}=true")
    tail = [
        f"FAILURE_STAGE={stage}", "RAW_EXCEPTION_CLASS=RuntimeError", "TELEGRAM_NETWORK_CALLS=0",
        "DB_WRITES=0", "ENV_WRITES=0", "SERVICE_RECREATIONS=0", "M4BR1_TERMINAL=failure",
    ]
    return "\n".join([*prefix, *tail]) + "\n"


def test_wrapper_prints_remote_verifier_failure_without_ssh_failed(tmp_path) -> None:
    transcript = _remote_failure_transcript()
    assert verifier.parse_output(transcript) == "failure"
    remote_out = tmp_path / "remote_out"
    remote_out.write_text(transcript, encoding="utf-8")
    result = _run_wrapper(tmp_path, KEYSCAN_OK="1", SSH_RC="2", SSH_STDOUT_FILE=str(remote_out))
    assert result.returncode == 2
    assert result.stdout == transcript
    assert "M4BR1_BLOCKED=ssh_failed" not in result.stdout
    assert "M4BR1_BLOCKED=" not in result.stdout
    assert "STDERR_SECRET_SHOULD_NOT_APPEAR" not in result.stdout
    assert result.stdout.count("M4BR1_BEGIN=true") == 1


def test_wrapper_ssh_transport_failure_stays_sanitized(tmp_path) -> None:
    result = _run_wrapper(tmp_path, KEYSCAN_OK="1", SSH_RC="255", SSH_STDOUT_FILE="")
    assert result.returncode == 2
    assert result.stdout.strip() == "M4BR1_BLOCKED=ssh_failed"
    assert "STDERR_SECRET_SHOULD_NOT_APPEAR" not in result.stdout
    garbage = tmp_path / "garbage"
    garbage.write_text("ssh debug secret-token\n", encoding="utf-8")
    result = _run_wrapper(tmp_path, KEYSCAN_OK="1", SSH_RC="255", SSH_STDOUT_FILE=str(garbage))
    assert result.returncode == 2
    assert result.stdout.strip() == "M4BR1_BLOCKED=ssh_failed"
    assert "secret-token" not in result.stdout
    quiet = tmp_path / "quiet"
    quiet.write_text("not a protocol\n", encoding="utf-8")
    result = _run_wrapper(tmp_path, KEYSCAN_OK="1", SSH_RC="0", SSH_STDOUT_FILE=str(quiet))
    assert result.returncode == 2
    assert result.stdout.strip() == "M4BR1_BLOCKED=remote_protocol"
    assert "not a protocol" not in result.stdout
