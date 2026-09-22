from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "verify_telegram_bot_retirement.py"
SPEC = importlib.util.spec_from_file_location("verifier", SOURCE)
verifier = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(verifier)


def success_transcript() -> str:
    return "\n".join(  # noqa: FLY002
        [
            "M4BM1_BEGIN=true", "REMOTE_HEAD_PASS=true", "REMOTE_PRODUCTION_REF_PASS=true", "REMOTE_WORKTREE_CLEAN=true",
            "DB_RUNNING_PASS=true", "API_RUNNING_PASS=true", "WORKER_RUNNING_PASS=true", "DB_HEALTH_PASS=true",
            "BOT_ENV_EMPTY_PASS=true", "BOT_COMPOSE_ENV_EMPTY_PASS=true", "BOT_CONTAINER_ENV_EMPTY_PASS=true",
            "MTPROTO_CREDENTIALS_PRESERVED_PASS=true", "CREDENTIAL_KEY_PRESERVED_PASS=true", "DB_CREDENTIAL_PRESERVED_PASS=true",
            "TELEGRAM_MTPROTO_AI_DISABLED_PASS=true", "HEALTH_PASS=true", "ALEMBIC_0046_PASS=true", "TELEGRAM_NETWORK_CALLS=0",
            "DB_WRITES=0", "ENV_WRITES=0", "SERVICE_RECREATIONS=0", "M4BM1_TERMINAL=success", "M4BM1_END=true",
        ]
    ) + "\n"


def failure(stage="STAGE_1_ENV"):
    return "\n".join(["M4BM1_BEGIN=true", f"FAILURE_STAGE={stage}", "RAW_EXCEPTION_CLASS=ValueError", "TELEGRAM_NETWORK_CALLS=0", "DB_WRITES=0", "ENV_WRITES=0", "SERVICE_RECREATIONS=0", "M4BM1_TERMINAL=failure"]) + "\n"


def test_protocol_accepts_success_and_sanitized_failure():
    assert verifier.parse_output(success_transcript()) == "success"
    assert verifier.parse_output(failure()) == "failure"


@pytest.mark.parametrize("text", ["M4BM1_BEGIN=true\n", success_transcript().replace("DB_WRITES=0", "DB_WRITES=1"), failure().replace("RAW_EXCEPTION_CLASS=ValueError", "RAW_EXCEPTION_CLASS=ValueError:secret")])
def test_protocol_fail_closed(text):
    with pytest.raises(ValueError):
        verifier.parse_output(text)


def test_health_retries_then_succeeds_without_mutation():
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


def test_health_exhausts_exactly_30_attempts():
    attempts = []
    def request(*_args, **_kwargs):
        attempts.append(1)
        raise OSError("unavailable")
    with pytest.raises(RuntimeError, match="exhausted"):
        verifier._health("http://127.0.0.1:18080/health", request=request, sleeper=lambda _: None)
    assert len(attempts) == 30


def test_alembic_requires_exact_head(monkeypatch):
    monkeypatch.setattr(verifier, "_run", lambda _: "0046 (head)")
    verifier._require_alembic(["docker", "compose"])
    monkeypatch.setattr(verifier, "_run", lambda _: "0046")
    with pytest.raises(RuntimeError):
        verifier._require_alembic(["docker", "compose"])


def test_target_contract():
    target = verifier.load_target(ROOT / "target.json")
    assert target["origin_url"] == verifier.CANONICAL_ORIGIN
    assert target["repository_path"] == "/opt/secretary"


def test_source_has_no_provider_or_mutation_capability():
    text = SOURCE.read_text()
    for forbidden in ("deleteWebhook", "getWebhookInfo", "api.telegram.org", "restart", "os.replace", ".flush(", ".commit(", '"up"'):
        assert forbidden not in text
    assert '"config"' in text and '"ps"' in text and '"exec"' in text


def test_bundle_compiles_and_contains_remote_main():
    result = subprocess.run(["python3", str(SOURCE), "bundle"], capture_output=True, text=True, check=True)
    assert "def remote_main" in result.stdout
    compile(result.stdout, "<bundle>", "exec")


def _remote_fixture(monkeypatch, tmp_path, *, env_updates=None, container_updates=None, head=None, production=None):
    monkeypatch.chdir(tmp_path)
    values = {
        "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_BOT_USERNAME": "", "TELEGRAM_WEBHOOK_SECRET": "", "TELEGRAM_WEBHOOK_URL": "",
        "TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "hash", "SECRETARY_CREDENTIAL_KEY": "key", "POSTGRES_PASSWORD": "db",
        "TELEGRAM_MTPROTO_AI_ENABLED": "false",
    }
    values.update(env_updates or {})
    (tmp_path / ".env").write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n")
    services = {"api": {"environment": dict(values)}, "worker": {"environment": dict(values)}, "db": {"environment": {}}}
    config = {"services": services}
    container_values = {"api": dict(values), "worker": dict(values)}
    for service, updates in (container_updates or {}).items():
        container_values[service].update(updates)
    def fake_run(command):
        if command[:3] == ["git", "remote", "get-url"]: return verifier.CANONICAL_ORIGIN
        if command[:3] == ["git", "fetch", "--prune"]: return ""
        if command[:3] == ["git", "rev-parse", "HEAD"]: return head or verifier.RELEASE
        if command[:3] == ["git", "rev-parse", "origin/production"]: return production or verifier.RELEASE
        if command[:3] == ["git", "status", "--porcelain"]: return ""
        if " config " in (" " + " ".join(command) + " ") or command[-3:] == ["config", "--format", "json"]: return json.dumps(config)
        if command[-3:-1] == ["ps", "-q"]:
            return {"db": "db-id", "api": "api-id", "worker": "worker-id"}[command[-1]]
        if command[:3] == ["docker", "inspect", "-f"]:
            fmt = command[3]
            if "State" in fmt: return json.dumps({"Status": "running", "Health": {"Status": "healthy"}})
            if "Mounts" in fmt: return "volume=/var/lib/postgresql/data"
            if "Config.Env" in fmt:
                container = command[-1]
                service = {"api-id": "api", "worker-id": "worker"}[container]
                return json.dumps([f"{k}={v}" for k, v in container_values[service].items()])
        if "alembic" in command:
            return "0046 (head)"
        raise AssertionError(command)
    monkeypatch.setattr(verifier, "_run", fake_run)
    monkeypatch.setattr(verifier, "_health", lambda *_args, **_kwargs: None)


def test_remote_success_is_read_only(monkeypatch, tmp_path, capsys):
    _remote_fixture(monkeypatch, tmp_path)
    assert verifier.remote_main() == 0
    output = capsys.readouterr().out
    assert verifier.parse_output(output) == "success"
    assert "DB_WRITES=0" in output and "SERVICE_RECREATIONS=0" in output


@pytest.mark.parametrize(("kwargs", "stage"), [
    ({"head": "bad"}, "STAGE_0_REMOTE_HEAD"),
    ({"production": "bad"}, "STAGE_0_PRODUCTION_REF"),
    ({"env_updates": {"TELEGRAM_BOT_TOKEN": "secret"}}, "STAGE_1_ENV"),
    ({"env_updates": {"TELEGRAM_API_HASH": ""}}, "STAGE_1_ENV"),
    ({"env_updates": {"TELEGRAM_MTPROTO_AI_ENABLED": "true"}}, "STAGE_1_ENV"),
    ({"container_updates": {"api": {"TELEGRAM_API_HASH": "other"}}}, "STAGE_1_CONTAINER_ENV"),
])
def test_remote_failures_are_staged_and_zero_mutation(monkeypatch, tmp_path, capsys, kwargs, stage):
    _remote_fixture(monkeypatch, tmp_path, **kwargs)
    assert verifier.remote_main() == 2
    output = capsys.readouterr().out
    assert f"FAILURE_STAGE={stage}" in output
    assert verifier.parse_output(output) == "failure"
    assert "TELEGRAM_NETWORK_CALLS=0" in output
