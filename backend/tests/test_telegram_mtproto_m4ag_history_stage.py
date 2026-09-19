from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ops.production import diagnose_mtproto_auth_readonly as auth_diagnostic
from ops.production import diagnose_mtproto_history_stage as diagnostic


def _verified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_diagnostic,
        "_verified_entry",
        lambda *_args: "web-itx.duckdns.org ssh-ed25519 AAAA\n",
    )


def test_reuses_reviewed_transport_contract_and_exact_target() -> None:
    assert diagnostic.auth_diagnostic is auth_diagnostic
    assert diagnostic.EXPECTED_TARGET == "root@web-itx.duckdns.org"
    assert diagnostic.EXPECTED_PORT == 22
    assert diagnostic.EXPECTED_PIN == "SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs"
    assert diagnostic.MAX_ATTEMPTS == 3


def test_temp_known_hosts_lives_through_single_direct_ssh_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _verified(monkeypatch)
    observed: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["input"] = kwargs["input"]
        path = next(item.split("=", 1)[1] for item in argv if item.startswith("UserKnownHostsFile="))
        observed["known_hosts_exists"] = Path(path).exists()
        return subprocess.CompletedProcess(argv, 0, diagnostic.REMOTE_BEGIN + "\n" + diagnostic.REMOTE_END + "\n", "")

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
    assert diagnostic._run_once() == 0
    argv = observed["argv"]
    assert argv[0:3] == ["ssh", "-p", "22"]
    assert "root@web-itx.duckdns.org" in argv
    assert "BatchMode=yes" in argv
    assert "StrictHostKeyChecking=yes" in argv
    assert "GlobalKnownHostsFile=/dev/null" in argv
    assert "HostKeyAlgorithms=ssh-ed25519" in argv
    assert "ConnectTimeout=5" in argv
    assert "-F" not in argv and "-c" not in argv and "sh" not in argv
    assert observed["known_hosts_exists"] is True
    assert diagnostic.REMOTE_HELPER in observed["input"]


def test_pin_mismatch_blocks_before_ssh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_diagnostic,
        "_verified_entry",
        lambda *_args: (_ for _ in ()).throw(auth_diagnostic.DiagnosticError("pin")),
    )
    calls = 0

    def fake_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("SSH must not run")

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
    with pytest.raises(diagnostic.HistoryStageError):
        diagnostic._run_once()
    assert calls == 0


def test_pre_remote_transport_retries_three_times_with_fresh_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _verified(monkeypatch)
    paths: list[str] = []

    def fake_run(argv, **_kwargs):
        paths.append(next(item.split("=", 1)[1] for item in argv if item.startswith("UserKnownHostsFile=")))
        return subprocess.CompletedProcess(argv, 255, "", "Host key verification failed")

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
    with pytest.raises(diagnostic.HistoryStageError):
        diagnostic._run_once()
    assert len(paths) == 3
    assert len(set(paths)) == 3


def test_auth_and_remote_started_failures_do_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    for stderr, stdout in (("Permission denied", ""), ("", diagnostic.REMOTE_BEGIN + "\n")):
        _verified(monkeypatch)
        calls = 0

        def fake_run(argv, _stdout=stdout, _stderr=stderr, **_kwargs):
            nonlocal calls
            calls += 1
            return subprocess.CompletedProcess(argv, 255, _stdout, _stderr)

        monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
        with pytest.raises(diagnostic.HistoryStageError):
            diagnostic._run_once()
        assert calls == 1


def test_history_stage_order_and_single_call_limits_are_explicit() -> None:
    helper = diagnostic.REMOTE_HELPER
    assert helper.index("SESSION_DECRYPT_PASS=true") < helper.index("CONNECT_PASS=true")
    assert helper.index("CONNECT_PASS=true") < helper.index("ITER_MESSAGES_STARTED=true")
    assert helper.count("await client.connect()") == 1
    assert helper.count("await client.is_user_authorized()") == 1
    assert helper.count("client.iter_messages(") == 1
    assert "limit=1, reverse=False" in helper
    assert "await client.disconnect()" in helper


def test_stage_three_is_gated_and_application_history_is_not_used() -> None:
    helper = diagnostic.REMOTE_HELPER
    assert "if not authorized:" in helper
    assert "fetch_history" not in helper
    assert "send_message" not in helper
    assert "edit_message" not in helper
    assert "delete_messages" not in helper
    assert "send_read_acknowledge" not in helper
    assert "mark_read" not in helper
    assert "send_code" not in helper
    assert "sign_in" not in helper
    assert "iter_dialogs" not in helper
    assert "get_messages" not in helper


def test_iterator_never_emits_message_data_or_identifiers() -> None:
    helper = diagnostic.REMOTE_HELPER
    assert "async for _ in client.iter_messages" in helper
    assert "print(message" not in helper
    assert "message.id" not in helper
    assert "print(peer" not in helper
    assert "print(selection.peer_id" not in helper
    assert "print(account" not in helper
    assert "print(settings.telegram" not in helper


def test_probe_has_no_secret_decryption_output_or_mutation_commands() -> None:
    helper = diagnostic.REMOTE_HELPER
    assert "SESSION_OR_REFERENCE_PRINTED" in helper
    assert "print(session_value" not in helper
    assert "print(reference_value" not in helper
    assert "print(settings.telegram_api_id" not in helper
    assert "print(settings.telegram_api_hash" not in helper
    assert "INSERT" not in helper
    assert "UPDATE" not in helper
    assert "DELETE" not in helper
    assert "alembic upgrade" not in helper
    assert "docker compose up" not in helper
    assert "docker compose restart" not in helper
    assert "git reset" not in helper
