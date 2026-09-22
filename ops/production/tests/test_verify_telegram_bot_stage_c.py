from __future__ import annotations

import importlib.util
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
    assert verifier.RELEASE == "bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4"
    target = verifier.load_target(ROOT / "target.json")
    assert target["origin_url"] == verifier.CANONICAL_ORIGIN
    assert target["repository_path"] == "/opt/secretary"


def test_authoritative_branch_accepts_exact_single_line(monkeypatch) -> None:
    monkeypatch.setattr(verifier, "_run", lambda _: "a" * 40 + "\trefs/heads/production")
    assert verifier.authoritative_branch("production") == "a" * 40


@pytest.mark.parametrize("output", [
    "a" * 40 + " refs/heads/production",
    "a" * 40 + "\trefs/heads/production\n" + "b" * 40 + "\trefs/heads/production",
    "A" * 40 + "\trefs/heads/production",
    "a" * 40 + "\trefs/heads/main",
])
def test_authoritative_branch_rejects_malformed_duplicate_or_unexpected(monkeypatch, output) -> None:
    monkeypatch.setattr(verifier, "_run", lambda _: output)
    with pytest.raises(ValueError):
        verifier.authoritative_branch("production")


def test_authoritative_branch_does_not_use_tracking_ref(monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(verifier, "_run", lambda command: commands.append(command) or ("a" * 40 + "\trefs/heads/production"))
    verifier.authoritative_branch("production")
    assert commands == [["git", "ls-remote", "origin", "refs/heads/production"]]


def test_remote_authoritative_mismatch_stops_before_runtime(monkeypatch, capsys) -> None:
    commands = []

    def fake_run(command):
        commands.append(command)
        if command == ["git", "remote", "get-url", "origin"]:
            return verifier.CANONICAL_ORIGIN
        if command == ["git", "rev-parse", "HEAD"]:
            return verifier.RELEASE
        if command == ["git", "ls-remote", "origin", "refs/heads/production"]:
            return "0" * 40 + "\trefs/heads/production"
        raise AssertionError(command)

    monkeypatch.setattr(verifier, "_run", fake_run)
    assert verifier.remote_main() == 2
    output = capsys.readouterr().out
    assert "FAILURE_STAGE=STAGE_0_PRODUCTION_REF" in output
    assert not any(command[:2] == ["docker", "compose"] for command in commands)


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
    assert "origin/production" not in text
    assert "fetch" not in text
    assert "origin/production" not in wrapper
    assert "fetch --prune origin main production" not in wrapper


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
