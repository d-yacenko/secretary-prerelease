"""Local-only tests for the fail-closed Stage B retirement harness."""

import importlib.util
import subprocess
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

OPS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("retire_telegram_bot", OPS / "retire_telegram_bot.py")
assert SPEC and SPEC.loader
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def env_text(token: str = "BOT_SECRET") -> str:
    return (
        "POSTGRES_PASSWORD=db-secret\n"
        "TELEGRAM_API_ID=123\n"
        "TELEGRAM_API_HASH=api-secret\n"
        "SECRETARY_CREDENTIAL_KEY=credential-secret\n"
        "TELEGRAM_MTPROTO_AI_ENABLED=false\n"
        f"TELEGRAM_BOT_TOKEN={token}\n"
        "TELEGRAM_BOT_USERNAME=secretary_bot\n"
        "TELEGRAM_WEBHOOK_SECRET=webhook-secret\n"
        "TELEGRAM_WEBHOOK_URL=https://example.invalid/hook\n"
        "OTHER_SETTING=preserve me\n"
    )


def success_transcript() -> str:
    lines = ["M4BJ1_BEGIN=true"]
    for key in harness.SUCCESS_FIELDS[1:-2]:
        lines.append(f"{key}=true" if key.endswith("PASS") else f"{key}=2")
    lines.extend(("M4BJ1_TERMINAL=success", "M4BJ1_END=true"))
    return "\n".join(lines) + "\n"


def test_exact_four_key_mutation_preserves_other_bytes(tmp_path: Path):
    path = tmp_path / ".env"
    before = env_text()
    path.write_text(before, encoding="utf-8")
    original_mode = path.stat().st_mode & 0o7777
    old, new = harness.clear_bot_environment(path)
    assert old == before
    assert harness.neutralized_equal(old, new)
    after = path.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=\n" in after
    assert "TELEGRAM_WEBHOOK_URL=\n" in after
    assert "OTHER_SETTING=preserve me\n" in after
    assert path.stat().st_mode & 0o7777 == original_mode


@pytest.mark.parametrize(
    "bad",
    [
        env_text().replace("TELEGRAM_BOT_TOKEN=BOT_SECRET\n", ""),
        env_text() + "TELEGRAM_BOT_TOKEN=duplicate\n",
        env_text().replace("TELEGRAM_BOT_TOKEN=BOT_SECRET", "TELEGRAM_BOT_TOKEN: BOT_SECRET"),
    ],
)
def test_missing_duplicate_or_malformed_bot_key_fails_closed(tmp_path: Path, bad: str):
    path = tmp_path / ".env"
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(ValueError):
        harness.clear_bot_environment(path)
    assert path.read_text(encoding="utf-8") == bad


def test_provider_delete_and_readback_are_exactly_two_calls_and_token_stays_in_process():
    seen: list[str] = []

    class Response:
        def __init__(self, payload: dict):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            import json

            return json.dumps(self.payload).encode()

    def fake_urlopen(request, timeout):
        assert timeout == 15
        assert request.method == "POST"
        seen.append(request.full_url)
        if request.full_url.endswith("/deleteWebhook"):
            assert request.data == b"drop_pending_updates=true"
            return Response({"ok": True, "result": True})
        return Response({"ok": True, "result": {"url": ""}})

    with patch.object(urllib.request, "urlopen", side_effect=fake_urlopen):
        harness.delete_webhook_once("BOT_SECRET")
        harness.verify_webhook_empty("BOT_SECRET")
    assert len(seen) == 2
    assert all("BOT_SECRET" in url for url in seen)
    with patch.object(subprocess, "run") as run:
        run.assert_not_called()


def test_provider_failure_is_sanitized_and_prevents_env_mutation(tmp_path: Path):
    path = tmp_path / ".env"
    before = env_text()
    path.write_text(before, encoding="utf-8")
    with patch.object(harness, "_provider_json", side_effect=RuntimeError("secret BOT_SECRET")), pytest.raises(
        RuntimeError, match="provider request failed|secret BOT_SECRET"
    ):
        harness.delete_webhook_once("BOT_SECRET")
    assert path.read_text(encoding="utf-8") == before


def test_output_protocol_accepts_success_and_rejects_eof_or_unsafe():
    transcript = success_transcript()
    assert harness.parse_output(transcript) == "success"
    for cut in range(len(transcript.splitlines())):
        with pytest.raises(ValueError):
            harness.parse_output("\n".join(transcript.splitlines()[:cut]) + "\n")
    with pytest.raises(ValueError):
        harness.parse_output(transcript.replace("M4BJ1_END=true", "SECRET=BOT_SECRET"))


def test_failure_protocol_is_sanitized_and_bounded():
    output = (
        "M4BJ1_BEGIN=true\nCANONICAL_REPO_PASS=true\n"
        "FAILURE_STAGE=STAGE_3_DELETE_WEBHOOK\nRAW_EXCEPTION_CLASS=RuntimeError\n"
        "TELEGRAM_NETWORK_CALLS=1\nM4BJ1_TERMINAL=failure\n"
    )
    assert harness.parse_output(output) == "failure"
    with pytest.raises(ValueError):
        harness.parse_output(output.replace("RAW_EXCEPTION_CLASS=RuntimeError", "TOKEN=secret"))


def test_recreate_scope_never_contains_db_and_bundle_is_local_only():
    source = Path(harness.__file__).read_text(encoding="utf-8")
    assert '"api", "worker"' in source
    assert '"db"' not in source[source.index('"up", "-d"') : source.index('"up", "-d"') + 100]
    bundle = subprocess.run(
        ["python3", str(harness.__file__), "bundle"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "def remote_main" in bundle
    assert "BOT_SECRET" not in bundle


def test_compile_and_wrapper_syntax():
    subprocess.run(["python3", "-m", "py_compile", str(harness.__file__)], check=True)
    subprocess.run(["bash", "-n", str(Path(harness.__file__).with_suffix(".sh"))], check=True)


def test_target_loader_is_single_identity_source():
    target = harness.load_target()
    assert target["origin_url"] == harness.CANONICAL_ORIGIN
    wrapper = Path(harness.__file__).with_suffix(".sh").read_text(encoding="utf-8")
    assert "web-itx.duckdns.org" not in wrapper
    assert "SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs" not in wrapper
    assert '"$HELPER" target' in wrapper
    assert "https://github.com/d-yacenko/secretary-prerelease.git" not in wrapper
    assert "origin main production" in wrapper


def test_alembic_current_contract_requires_exact_head_marker(monkeypatch):
    command = harness._compose() + ["exec", "-T", "api", "alembic", "current"]
    seen: list[list[str]] = []

    def fake_run(args, **_kwargs):
        seen.append(args)
        return "0046 (head)\n"

    monkeypatch.setattr(harness, "_run", fake_run)
    harness._require_alembic(harness._compose(), "0046")
    assert seen == [command]
    monkeypatch.setattr(harness, "_run", lambda *_args, **_kwargs: "0045 (head)")
    with pytest.raises(RuntimeError):
        harness._require_alembic(harness._compose(), "0046")


def _remote_main_context(monkeypatch, tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text(env_text(), encoding="utf-8")
    events: list[str] = []
    values = harness._env_assignments(env_text())

    def fake_run(command, **_kwargs):
        if command[:3] == ["git", "remote", "get-url"]:
            return harness.CANONICAL_ORIGIN
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return harness.RELEASE
        if command[:3] == ["git", "rev-parse", "origin/production"]:
            return harness.RELEASE
        if command[:3] == ["git", "status", "--porcelain"]:
            return ""
        if command[:3] == ["git", "fetch", "--prune"]:
            events.append("fetch")
            return ""
        if command[-3:] == ["ps", "-q", "db"]:
            return "db-container"
        if command[-3:] == ["ps", "-q", "api"]:
            return "api-container"
        if command[-3:] == ["ps", "-q", "worker"]:
            return "worker-container"
        if command[:2] == ["docker", "inspect"]:
            return "db-volume"
        if "--force-recreate" in command:
            events.append("recreate")
            assert command[-2:] == ["api", "worker"]
            return ""
        return ""

    monkeypatch.setattr(harness, "_run", fake_run)
    monkeypatch.setattr(harness, "_require_running_container", lambda *_args, **_kwargs: None)
    def actual_environment(container):
        events.append(f"inspect:{container}")
        return {
            **{key: "" for key in harness.BOT_KEYS},
            **{key: values[key] for key in (*harness.MT_PROTO_KEYS, *harness.INVARIANT_KEYS)},
            "TELEGRAM_MTPROTO_AI_ENABLED": "false",
        }

    monkeypatch.setattr(harness, "_container_environment", actual_environment)
    monkeypatch.setattr(
        harness,
        "_remote_env_and_snapshot",
        lambda: (path, values, env_text(), "db-container", "db-volume", "api-old", "worker-old"),
    )
    monkeypatch.setattr(harness, "_require_alembic", lambda *_args: None)

    def config(_compose):
        post = harness._env_assignments(path.read_text(encoding="utf-8"))
        service = {key: post.get(key, "") for key in (*harness.BOT_KEYS, *harness.MT_PROTO_KEYS, *harness.INVARIANT_KEYS, "TELEGRAM_MTPROTO_AI_ENABLED")}
        return {"services": {"api": {"environment": service}, "worker": {"environment": service}, "db": {}}}

    monkeypatch.setattr(harness, "_compose_config", config)
    return path, events


def test_remote_delete_failure_stops_before_readback_env_and_recreate(monkeypatch, tmp_path, capsys):
    _remote_main_context(monkeypatch, tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(harness, "delete_webhook_once", lambda _token: (calls.append("delete"), (_ for _ in ()).throw(RuntimeError("provider")))[1])
    monkeypatch.setattr(harness, "verify_webhook_empty", lambda _token: calls.append("readback"))
    monkeypatch.setattr(harness, "clear_bot_environment", lambda _path: calls.append("env"))
    assert harness.remote_main() == 2
    output = capsys.readouterr().out
    assert harness.parse_output(output) == "failure"
    assert "STAGE_3_DELETE_WEBHOOK" in output
    assert "TELEGRAM_NETWORK_CALLS=1" in output
    assert calls == ["delete"]


def test_remote_readback_failure_stops_before_env_and_recreate(monkeypatch, tmp_path, capsys):
    _remote_main_context(monkeypatch, tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(harness, "delete_webhook_once", lambda _token: calls.append("delete"))
    monkeypatch.setattr(harness, "verify_webhook_empty", lambda _token: (calls.append("readback"), (_ for _ in ()).throw(RuntimeError("provider")))[1])
    monkeypatch.setattr(harness, "clear_bot_environment", lambda _path: calls.append("env"))
    assert harness.remote_main() == 2
    output = capsys.readouterr().out
    assert harness.parse_output(output) == "failure"
    assert "STAGE_3_VERIFY_WEBHOOK" in output
    assert "TELEGRAM_NETWORK_CALLS=2" in output
    assert calls == ["delete", "readback"]


def test_remote_success_proves_destructive_order_and_two_provider_calls(monkeypatch, tmp_path, capsys):
    path, events = _remote_main_context(monkeypatch, tmp_path)
    monkeypatch.setattr(harness, "delete_webhook_once", lambda _token: events.append("delete"))
    monkeypatch.setattr(harness, "verify_webhook_empty", lambda _token: events.append("readback"))
    real_write = harness.write_planned_bot_environment

    def write(path_arg, expected, planned, mode):
        events.append("env")
        return real_write(path_arg, expected, planned, mode)

    monkeypatch.setattr(harness, "write_planned_bot_environment", write)
    assert harness.remote_main() == 0
    output = capsys.readouterr().out
    assert harness.parse_output(output) == "success"
    assert "TELEGRAM_NETWORK_CALLS=2" in output
    assert [event for event in events if event in {"delete", "readback", "env", "recreate"}] == [
        "delete",
        "readback",
        "env",
        "recreate",
    ]
    assert "inspect:api-container" in events
    assert "inspect:worker-container" in events
    assert "db" not in events
    assert path.read_text(encoding="utf-8").count("TELEGRAM_BOT_TOKEN=\n") == 1


def test_remote_production_ref_fetch_failure_is_before_provider(monkeypatch, tmp_path, capsys):
    _remote_main_context(monkeypatch, tmp_path)
    calls: list[str] = []
    original_run = harness._run

    def fail_fetch(command, **kwargs):
        if command[:3] == ["git", "fetch", "--prune"]:
            raise RuntimeError("fetch failed")
        return original_run(command, **kwargs)

    monkeypatch.setattr(harness, "_run", fail_fetch)
    monkeypatch.setattr(harness, "delete_webhook_once", lambda _token: calls.append("delete"))
    monkeypatch.setattr(harness, "clear_bot_environment", lambda _path: calls.append("env"))
    assert harness.remote_main() == 2
    output = capsys.readouterr().out
    assert harness.parse_output(output) == "failure"
    assert "STAGE_0_PRODUCTION_REF_FETCH" in output
    assert "TELEGRAM_NETWORK_CALLS=0" in output
    assert calls == []


def test_remote_production_ref_mismatch_is_before_provider(monkeypatch, tmp_path, capsys):
    _remote_main_context(monkeypatch, tmp_path)
    calls: list[str] = []
    original_run = harness._run

    def mismatched_ref(command, **kwargs):
        if command[:3] == ["git", "rev-parse", "origin/production"]:
            return "0" * 40
        return original_run(command, **kwargs)

    monkeypatch.setattr(harness, "_run", mismatched_ref)
    monkeypatch.setattr(harness, "delete_webhook_once", lambda _token: calls.append("delete"))
    assert harness.remote_main() == 2
    output = capsys.readouterr().out
    assert harness.parse_output(output) == "failure"
    assert "STAGE_0_PRODUCTION_REF" in output
    assert "TELEGRAM_NETWORK_CALLS=0" in output
    assert calls == []


def test_remote_db_unhealthy_is_before_provider(monkeypatch, tmp_path, capsys):
    _remote_main_context(monkeypatch, tmp_path)
    monkeypatch.setattr(
        harness,
        "_remote_env_and_snapshot",
        lambda: (_ for _ in ()).throw(RuntimeError("database unhealthy")),
    )
    calls: list[str] = []
    monkeypatch.setattr(harness, "delete_webhook_once", lambda _token: calls.append("delete"))
    assert harness.remote_main() == 2
    output = capsys.readouterr().out
    assert harness.parse_output(output) == "failure"
    assert "STAGE_0_DB_HEALTH" in output
    assert "TELEGRAM_NETWORK_CALLS=0" in output
    assert calls == []


def test_env_change_after_provider_readback_stops_before_recreate(monkeypatch, tmp_path, capsys):
    _, events = _remote_main_context(monkeypatch, tmp_path)
    monkeypatch.setattr(harness, "delete_webhook_once", lambda _token: events.append("delete"))
    monkeypatch.setattr(harness, "verify_webhook_empty", lambda _token: events.append("readback"))
    real_write = harness.write_planned_bot_environment

    def changed(path_arg, expected, planned, mode):
        path_arg.write_text(expected + "RACE=changed\n", encoding="utf-8")
        return real_write(path_arg, expected, planned, mode)

    monkeypatch.setattr(harness, "write_planned_bot_environment", changed)
    assert harness.remote_main() == 2
    output = capsys.readouterr().out
    assert harness.parse_output(output) == "failure"
    assert "STAGE_4_ENV_MUTATION" in output
    assert events == ["fetch", "delete", "readback"]


def test_invalid_resolved_mtproto_environment_stops_before_provider(monkeypatch, tmp_path, capsys):
    _remote_main_context(monkeypatch, tmp_path)
    monkeypatch.setattr(
        harness,
        "_validate_resolved_environment",
        lambda *_args: (_ for _ in ()).throw(ValueError("invalid API ID")),
    )
    calls: list[str] = []
    monkeypatch.setattr(harness, "delete_webhook_once", lambda _token: calls.append("delete"))
    assert harness.remote_main() == 2
    output = capsys.readouterr().out
    assert harness.parse_output(output) == "failure"
    assert "STAGE_1_ENV_PREFLIGHT" in output
    assert "TELEGRAM_NETWORK_CALLS=0" in output
    assert calls == []


@pytest.mark.parametrize(
    "transform",
    [
        lambda text: text.replace("TELEGRAM_BOT_TOKEN=BOT_SECRET\n", ""),
        lambda text: text + "TELEGRAM_BOT_TOKEN=duplicate\n",
        lambda text: text.replace("TELEGRAM_BOT_TOKEN=BOT_SECRET", "TELEGRAM_BOT_TOKEN: BOT_SECRET"),
    ],
)
def test_malformed_bot_env_fails_through_remote_main_before_provider(monkeypatch, tmp_path, capsys, transform):
    path, events = _remote_main_context(monkeypatch, tmp_path)
    malformed = transform(env_text())
    path.write_text(malformed, encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(harness, "delete_webhook_once", lambda _token: calls.append("delete"))
    assert harness.remote_main() == 2
    output = capsys.readouterr().out
    assert harness.parse_output(output) == "failure"
    assert "STAGE_1_ENV_PREFLIGHT" in output
    assert "TELEGRAM_NETWORK_CALLS=0" in output
    assert calls == []
    assert "recreate" not in events


def test_actual_worker_environment_failure_is_named_after_two_provider_calls(monkeypatch, tmp_path, capsys):
    _remote_main_context(monkeypatch, tmp_path)
    monkeypatch.setattr(harness, "delete_webhook_once", lambda _token: None)
    monkeypatch.setattr(harness, "verify_webhook_empty", lambda _token: None)
    inspected: list[str] = []

    def fail_worker(container):
        inspected.append(container)
        if container == "worker-container":
            raise RuntimeError("worker environment mismatch")
        return {**{key: "" for key in harness.BOT_KEYS}, "TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "api-secret", "SECRETARY_CREDENTIAL_KEY": "credential-secret", "POSTGRES_PASSWORD": "db-secret", "TELEGRAM_MTPROTO_AI_ENABLED": "false"}

    monkeypatch.setattr(harness, "_container_environment", fail_worker)
    assert harness.remote_main() == 2
    output = capsys.readouterr().out
    assert harness.parse_output(output) == "failure"
    assert "STAGE_5_CONTAINER_ENV" in output
    assert "TELEGRAM_NETWORK_CALLS=2" in output
    assert inspected == ["api-container", "worker-container"]
