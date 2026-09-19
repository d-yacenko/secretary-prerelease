from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ops.production import diagnose_mtproto_auth_readonly as diagnostic


def _verified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        diagnostic,
        "_verified_entry",
        lambda *_args: "web-itx.duckdns.org ssh-ed25519 AAAA\n",
    )


def test_ssh_argv_is_exact_and_temp_file_lives_through_process(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _verified(monkeypatch)
    observed: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["input"] = kwargs["input"]
        known_hosts = next(item.split("=", 1)[1] for item in argv if item.startswith("UserKnownHostsFile="))
        observed["exists_during"] = Path(known_hosts).exists()
        return subprocess.CompletedProcess(argv, 0, diagnostic.REMOTE_BEGIN + "\n" + diagnostic.REMOTE_END + "\n", "")

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
    assert diagnostic.run_diagnostic() == 0
    argv = observed["argv"]
    assert argv[:2] == ["ssh", "-p"]
    assert "BatchMode=yes" in argv
    assert "StrictHostKeyChecking=yes" in argv
    assert "GlobalKnownHostsFile=/dev/null" in argv
    assert "HostKeyAlgorithms=ssh-ed25519" in argv
    assert "ConnectTimeout=5" in argv
    assert observed["exists_during"] is True
    assert "sh" not in argv and "-F" not in argv and "-c" not in argv
    assert diagnostic.REMOTE_HELPER in observed["input"]
    assert capsys.readouterr().out.count("ATTEMPT=") == 1


def test_pin_mismatch_fails_before_ssh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnostic, "_verified_entry", lambda *_args: (_ for _ in ()).throw(diagnostic.DiagnosticError("pin")))
    calls = 0

    def fake_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("SSH must not run")

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.run_diagnostic()
    assert calls == 0


def test_transport_retries_at_most_three_times_with_fresh_temp_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _verified(monkeypatch)
    paths: list[str] = []

    def fake_run(argv, **_kwargs):
        paths.append(next(item.split("=", 1)[1] for item in argv if item.startswith("UserKnownHostsFile=")))
        return subprocess.CompletedProcess(argv, 255, "", "Host key verification failed")

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.run_diagnostic()
    assert len(paths) == 3
    assert len(set(paths)) == 3


def test_authentication_failure_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    _verified(monkeypatch)
    calls = 0

    def fake_run(argv, **_kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(argv, 255, "", "Permission denied")

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.run_diagnostic()
    assert calls == 1


def test_remote_helper_has_one_session_and_no_mutation_or_provider_path() -> None:
    helper = diagnostic.REMOTE_HELPER
    assert helper.count("REMOTE_DIAGNOSTIC_BEGIN") == 1
    assert "telethon" not in helper.lower()
    assert "decrypt_session" not in helper
    assert "docker compose up" not in helper
    assert "docker compose down" not in helper
    assert "docker compose restart" not in helper
    assert "git checkout" not in helper
    assert "git reset" not in helper
    assert "INSERT" not in helper
    assert "UPDATE" not in helper
    assert "DELETE" not in helper
    for forbidden in ("provider_ref", "access_hash", "api_hash", "bearer"):
        assert forbidden not in helper
