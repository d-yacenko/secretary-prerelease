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
        return subprocess.CompletedProcess(
            argv,
            0,
            diagnostic.REMOTE_BEGIN + "=true\nTELEGRAM_NETWORK_CALLS=0\n" + diagnostic.REMOTE_END + "=true\n",
            "",
        )

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
    _verified(monkeypatch)
    calls = 0

    def fake_auth_run(argv, **_kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(argv, 255, "", "Permission denied")

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_auth_run)
    with pytest.raises(diagnostic.HistoryStageError):
        diagnostic._run_once()
    assert calls == 1

    _verified(monkeypatch)
    calls = 0

    def fake_remote_run(argv, **_kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(argv, 0, diagnostic.REMOTE_BEGIN + "=true\n", "")

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_remote_run)
    assert diagnostic._run_once() == 2
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
    assert "SESSION_OR_REFERENCE_PRINTED" not in helper
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


def test_stage_zero_guards_precede_inner_probe_and_provider_construction() -> None:
    helper = diagnostic.REMOTE_HELPER
    assert helper.index("if head.returncode") < helper.index("probe =")
    assert helper.index("if production.returncode") < helper.index("probe =")
    assert helper.index("if clean.returncode") < helper.index("probe =")
    assert helper.index("revision =") < helper.index("probe =")
    assert helper.index("if len(accounts) != 1") < helper.index("TelegramClient(")
    assert 'emit("TELEGRAM_NETWORK_CALLS", "0")' in helper


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("UNKNOWN=true", "unknown key"),
        ("CONNECT_PASS=maybe", "invalid boolean"),
        ("CONNECT_CALL_COUNT=2", "over-bound count"),
        ("CONNECT_PASS=true\nCONNECT_PASS=false", "duplicate key"),
        ("FAILURE_STAGE=not-a-stage", "invalid failure stage"),
        ("RAW_EXCEPTION_CLASS=ValueError:secret", "exception message"),
        ("RAW_EXCEPTION_CLASS=Trace\nback", "malformed line"),
    ],
)
def test_child_output_allowlist_rejects_invalid_lines(line: str, expected: str) -> None:
    with pytest.raises(diagnostic.HistoryStageError, match="invalid child output"):
        diagnostic.parse_child_output(
            f"{diagnostic.REMOTE_BEGIN}=true\n{line}\n{diagnostic.REMOTE_END}=true\n",
            "",
            0,
        )
    assert expected


def test_raw_exception_class_allowlist_accepts_only_safe_class_name() -> None:
    parsed = diagnostic.parse_child_output(
        "RAW_EXCEPTION_CLASS=ValueError\nTELEGRAM_NETWORK_CALLS=0\n",
        "",
        0,
    )
    assert parsed["RAW_EXCEPTION_CLASS"] == "ValueError"
    for invalid in ("ValueError.message", "ValueError:secret", "Value Error", "[ValueError]"):
        with pytest.raises(diagnostic.HistoryStageError):
            diagnostic.parse_child_output(f"RAW_EXCEPTION_CLASS={invalid}\n", "", 0)


def test_child_stderr_is_never_echoed_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _verified(monkeypatch)

    def fake_run(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
            f"{diagnostic.REMOTE_BEGIN}=true\n{diagnostic.REMOTE_END}=true\n",
            "secret-session traceback",
        )

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
    assert diagnostic._run_once() == 2
    output = capsys.readouterr()
    assert "secret-session" not in output.out
    assert "traceback" not in output.out
    assert "FAILURE_STAGE=OUTPUT_ALLOWLIST" in output.out


def test_valid_diagnostic_failure_is_preserved_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _verified(monkeypatch)
    calls = 0

    def fake_run(argv, **_kwargs):
        nonlocal calls
        calls += 1
        stdout = "\n".join(
            [
                f"{diagnostic.REMOTE_BEGIN}=true",
                "FAILURE_STAGE=STAGE_2_AUTHORIZED",
                "RAW_EXCEPTION_CLASS=AuthorizationFalse",
                "TELEGRAM_NETWORK_CALLS=2",
                f"{diagnostic.REMOTE_END}=true",
            ]
        )
        return subprocess.CompletedProcess(argv, 0, stdout + "\n", "")

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
    assert diagnostic._run_once() == 0
    assert calls == 1
    assert "FAILURE_STAGE=STAGE_2_AUTHORIZED" in capsys.readouterr().out


def test_valid_success_output_is_preserved() -> None:
    payload = """SESSION_DECRYPT_PASS=true
STRING_SESSION_PARSE_PASS=true
REFERENCE_DECRYPT_PASS=true
REFERENCE_PARSE_PASS=true
REFERENCE_PEER_MATCH_PASS=true
TELEGRAM_CLIENT_CONSTRUCT_PASS=true
CONNECT_PASS=true
IS_USER_AUTHORIZED=true
ITER_MESSAGES_STARTED=true
ITER_MESSAGES_ONE_ITEM_OR_EMPTY_PASS=true
CONNECT_CALL_COUNT=1
IS_USER_AUTHORIZED_CALL_COUNT=1
ITER_MESSAGES_CALL_COUNT=1
TELEGRAM_NETWORK_CALLS=3"""
    parsed = diagnostic.parse_child_output(
        payload,
        "",
        0,
    )
    assert parsed["TELEGRAM_NETWORK_CALLS"] == "3"
