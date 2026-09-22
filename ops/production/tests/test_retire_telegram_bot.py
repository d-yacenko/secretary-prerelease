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
