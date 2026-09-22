from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "verify_telegram_bot_stage_c.py"
SPEC = importlib.util.spec_from_file_location("stage_c", SOURCE)
verifier = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(verifier)


def success() -> str:
    values = {
        "M4BR1_BEGIN": "true", "REMOTE_HEAD_PASS": "true", "REMOTE_PRODUCTION_REF_PASS": "true",
        "REMOTE_WORKTREE_CLEAN": "true", "DB_RUNNING_PASS": "true", "API_RUNNING_PASS": "true",
        "WORKER_RUNNING_PASS": "true", "DB_HEALTH_PASS": "true", "APP_HEALTH_PASS": "true",
        "ALEMBIC_0046_PASS": "true", "LEGACY_BOT_ROUTES_ABSENT_PASS": "true",
        "MTPROTO_ROUTE_PRESENT_PASS": "true", "BOT_SETTINGS_MODEL_ABSENT_PASS": "true",
        "BOT_CONTAINER_ENV_ABSENT_PASS": "true", "MTPROTO_CREDENTIALS_PRESERVED_PASS": "true",
        "TELEGRAM_MTPROTO_AI_DISABLED_PASS": "true", "MTPROTO_ACCOUNT_COUNT": "1",
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
    monkeypatch.setattr(verifier, "_run", lambda _: "MTPROTO_ACCOUNT_COUNT=1\nACTIVE_SCOPE_COUNT=28\nLEGACY_BOT_OBJECT_COUNT=2\nLEGACY_BOT_INBOX_READABLE=true")
    assert verifier._child(["docker", "compose"])["ACTIVE_SCOPE_COUNT"] == "28"
    monkeypatch.setattr(verifier, "_run", lambda _: "MTPROTO_ACCOUNT_COUNT=1\nSECRET=x")
    with pytest.raises(ValueError):
        verifier._child(["docker", "compose"])


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
  authoritative)
    [ "${4:-}" = "$CANONICAL_ORIGIN" ] || exit 2
    if [ "${3:-}" = main ]; then printf '%s\\n' "$MAIN_SHA"
    elif [ "${3:-}" = production ]; then printf '%s\\n' "$PROD_SHA"
    else exit 2; fi ;;
  *) exit 2 ;;
esac
""")
    for name in ("ssh", "ssh-keyscan", "ssh-keygen"):
        _install(bindir / name, f"""#!/bin/bash
printf '{name} %s\\n' "$*" >> "$WRAPPER_LOG"
exit 1
""")
    env = os.environ.copy()
    env.update({
        "PATH": f"{bindir}:{env.get('PATH', '')}",
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
