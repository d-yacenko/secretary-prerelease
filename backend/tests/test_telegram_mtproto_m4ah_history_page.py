from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ops.production import diagnose_mtproto_auth_readonly as auth_diagnostic
from ops.production import diagnose_mtproto_history_page as diagnostic


def _verified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_diagnostic,
        "_verified_entry",
        lambda *_args: "web-itx.duckdns.org ssh-ed25519 AAAA\n",
    )


def test_reuses_exact_pinned_transport_and_temp_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    _verified(monkeypatch)
    observed: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["input"] = kwargs["input"]
        path = next(item.split("=", 1)[1] for item in argv if item.startswith("UserKnownHostsFile="))
        observed["exists"] = Path(path).exists()
        return subprocess.CompletedProcess(
            argv,
            0,
            f"{diagnostic.REMOTE_BEGIN}=true\nFIRST_PAGE_PASS=true\nMESSAGES_SEEN=0\nENTRIES_CONVERTED=0\nENTRIES_NONE=0\n{diagnostic.REMOTE_END}=true\n",
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
    assert "-F" not in argv and "-c" not in argv and "sh" not in argv
    assert observed["exists"] is True
    assert diagnostic.REMOTE_HELPER in observed["input"]


def test_transport_retry_is_bounded_to_three_pre_remote_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    _verified(monkeypatch)
    paths: list[str] = []

    def fake_run(argv, **_kwargs):
        paths.append(next(item.split("=", 1)[1] for item in argv if item.startswith("UserKnownHostsFile=")))
        return subprocess.CompletedProcess(argv, 255, "", "Host key verification failed")

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
    with pytest.raises(diagnostic.HistoryPageError):
        diagnostic._run_once()
    assert len(paths) == 3
    assert len(set(paths)) == 3


def test_stage_order_and_single_provider_iterator_creation() -> None:
    helper = diagnostic.REMOTE_HELPER
    assert helper.index("if head.returncode") < helper.index("probe =")
    assert helper.index("if len(accounts) != 1") < helper.index("TelegramClient(")
    assert helper.count("await client.connect()") == 1
    assert helper.count("await client.is_user_authorized()") == 1
    assert helper.count("client.iter_messages(") == 1
    assert "limit=PAGE_SIZE, reverse=False" in helper
    assert "PAGE_SIZE = 100" in helper
    assert "await client.disconnect()" in helper


def test_exact_history_conversion_and_no_application_fetch_or_materialization() -> None:
    helper = diagnostic.REMOTE_HELPER
    assert "_history_entry_from_message(message)" in helper
    assert "fetch_history" not in helper
    assert "TelegramObjectMaterializer" not in helper
    assert "materialize" not in helper.lower()
    assert "session.add" not in helper
    assert "INSERT" not in helper
    assert "UPDATE" not in helper
    assert "DELETE" not in helper
    assert "send_message" not in helper
    assert "edit_message" not in helper
    assert "delete_messages" not in helper
    assert "iter_dialogs" not in helper
    assert "send_code" not in helper
    assert "sign_in" not in helper


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("FAILURE_STAGE=STAGE_3_ITERATION\nRAW_EXCEPTION_CLASS=ServerError\nMESSAGE_ORDINAL=0\n", "STAGE_3_ITERATION"),
        ("FAILURE_STAGE=STAGE_3_CONVERSION\nRAW_EXCEPTION_CLASS=ValueError\nMESSAGE_ORDINAL=100\n", "STAGE_3_CONVERSION"),
        ("FIRST_PAGE_PASS=true\nMESSAGES_SEEN=100\nENTRIES_CONVERTED=100\nENTRIES_NONE=0\n", "FIRST_PAGE_PASS"),
    ],
)
def test_page_output_accepts_only_aggregate_failure_or_success_fields(payload: str, expected: str) -> None:
    parsed = diagnostic.parse_page_output(payload, "", 0)
    assert parsed["FAILURE_STAGE"] == expected if expected.startswith("STAGE_") else expected in parsed


def test_ordinal_and_count_bounds_are_fail_closed() -> None:
    for line in (
        "MESSAGE_ORDINAL=101",
        "MESSAGES_SEEN=101",
        "ENTRIES_CONVERTED=101",
        "ENTRIES_NONE=101",
        "ITER_MESSAGES_CALL_COUNT=2",
    ):
        with pytest.raises(diagnostic.HistoryPageError):
            diagnostic.parse_page_output(line, "", 0)


def test_page_output_redacts_unknown_malformed_and_stderr() -> None:
    for payload, stderr in (
        ("SECRET=token", ""),
        ("RAW_EXCEPTION_CLASS=ValueError:secret", ""),
        ("FIRST_PAGE_PASS=maybe", ""),
        ("FIRST_PAGE_PASS=true\nFIRST_PAGE_PASS=false", ""),
        ("FIRST_PAGE_PASS=true", "raw traceback secret"),
    ):
        with pytest.raises(diagnostic.HistoryPageError):
            diagnostic.parse_page_output(payload, stderr, 0)


@pytest.mark.parametrize(
    ("stage", "exception", "ordinal"),
    [
        ("STAGE_3_CONVERSION", "ValueError", 1),
        ("STAGE_3_CONVERSION", "TypeError", 37),
        ("STAGE_3_ITERATION", "ServerError", 0),
        ("STAGE_3_ITERATION", "TimeoutError", 38),
        ("STAGE_3_ITERATION", "TimeoutError", 100),
        ("STAGE_2_CONNECT", "ConnectionError", 0),
        ("STAGE_2_AUTHORIZED", "AuthError", 0),
        ("STAGE_2_AUTHORIZED", "AuthorizationFalse", 0),
        ("STAGE_3_CONVERSION", "InvalidHistoryEntry", 1),
    ],
)
def test_failure_protocol_always_carries_bounded_message_ordinal(
    stage: str, exception: str, ordinal: int
) -> None:
    payload = (
        f"FAILURE_STAGE={stage}\n"
        f"RAW_EXCEPTION_CLASS={exception}\n"
        f"MESSAGE_ORDINAL={ordinal}\n"
    )
    parsed = diagnostic.parse_page_output(payload, "", 0)
    assert parsed["FAILURE_STAGE"] == stage
    assert parsed["RAW_EXCEPTION_CLASS"] == exception
    assert parsed["MESSAGE_ORDINAL"] == str(ordinal)


def test_failure_without_ordinal_is_rejected() -> None:
    with pytest.raises(diagnostic.HistoryPageError):
        diagnostic.parse_page_output(
            "FAILURE_STAGE=STAGE_3_ITERATION\nRAW_EXCEPTION_CLASS=ServerError\n", "", 0
        )


def test_none_conversion_is_terminal_and_cannot_pass_page() -> None:
    helper = diagnostic.REMOTE_HELPER
    assert 'failure_class = "InvalidHistoryEntry"' in helper
    assert 'failure_stage = "STAGE_3_CONVERSION"' in helper
    assert "if entry is None:" in helper
    assert "break" in helper[helper.index("if entry is None:") :]
    with pytest.raises(diagnostic.HistoryPageError):
        diagnostic.parse_page_output(
            "FAILURE_STAGE=STAGE_3_CONVERSION\n"
            "RAW_EXCEPTION_CLASS=InvalidHistoryEntry\n"
            "MESSAGE_ORDINAL=1\nFIRST_PAGE_PASS=true\n",
            "",
            0,
        )


def test_success_protocol_has_zero_none_entries_and_aggregate_counts() -> None:
    parsed = diagnostic.parse_page_output(
        "ITER_MESSAGES_ONE_ITEM_OR_EMPTY_PASS=true\n"
        "FIRST_PAGE_PASS=true\nMESSAGES_SEEN=4\n"
        "ENTRIES_CONVERTED=4\nENTRIES_NONE=0\n",
        "",
        0,
    )
    assert parsed["ENTRIES_NONE"] == "0"
    assert "RAW_EXCEPTION_CLASS" not in parsed


def test_success_protocol_rejects_nonzero_none_missing_counts_and_mismatch() -> None:
    payloads = (
        "FIRST_PAGE_PASS=true\nMESSAGES_SEEN=4\nENTRIES_CONVERTED=4\nENTRIES_NONE=1\n",
        "FIRST_PAGE_PASS=true\nENTRIES_NONE=0\n",
        "FIRST_PAGE_PASS=true\nMESSAGES_SEEN=4\nENTRIES_CONVERTED=3\nENTRIES_NONE=0\n",
    )
    for payload in payloads:
        with pytest.raises(diagnostic.HistoryPageError):
            diagnostic.parse_page_output(payload, "", 0)


def _child_source() -> str:
    match = re.search(r'probe = r"""(.*?)\n"""', diagnostic.REMOTE_HELPER, re.DOTALL)
    assert match is not None
    return match.group(1)


def test_embedded_child_compiles_and_owns_page_size() -> None:
    source = _child_source()
    compile(source, "<m4ah-child>", "exec")
    assert "PAGE_SIZE = 100" in source
    assert "limit=PAGE_SIZE, reverse=False" in source


@pytest.mark.parametrize(
    ("stage", "exception"),
    [("STAGE_1_IMPORTS", "ImportError"), ("STAGE_1_DB_SESSION", "OperationalError")],
)
def test_child_bootstrap_failures_use_sanitized_protocol(stage: str, exception: str) -> None:
    parsed = diagnostic.parse_page_output(
        f"FAILURE_STAGE={stage}\nRAW_EXCEPTION_CLASS={exception}\n"
        "MESSAGE_ORDINAL=0\nTELEGRAM_NETWORK_CALLS=0\n",
        "",
        0,
    )
    assert parsed["FAILURE_STAGE"] == stage
    assert parsed["MESSAGE_ORDINAL"] == "0"
    assert parsed["TELEGRAM_NETWORK_CALLS"] == "0"
    assert "raise SystemExit(0)" in _child_source()


def test_child_import_failure_is_executable_and_sanitized() -> None:
    hook = (
        "import builtins\n"
        "_real_import = builtins.__import__\n"
        "def _blocked(name, *args, **kwargs):\n"
        "    if name == 'sqlalchemy':\n"
        "        raise ImportError('hidden')\n"
        "    return _real_import(name, *args, **kwargs)\n"
        "builtins.__import__ = _blocked\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", hook + _child_source()],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    parsed = diagnostic.parse_page_output(result.stdout, result.stderr, result.returncode)
    assert parsed == {
        "FAILURE_STAGE": "STAGE_1_IMPORTS",
        "RAW_EXCEPTION_CLASS": "ImportError",
        "MESSAGE_ORDINAL": "0",
        "TELEGRAM_NETWORK_CALLS": "0",
    }


def test_child_runtime_scope_and_parent_fail_closed_handling() -> None:
    source = _child_source()
    assert "except Exception as exc:" in source
    assert 'emit_failure("STAGE_1_IMPORTS", exc)' in source
    assert 'emit_failure("STAGE_1_DB_SESSION", exc)' in source
    for payload, stderr, returncode in (
        ("SECRET=raw", "", 0),
        ("FAILURE_STAGE=STAGE_1_IMPORTS\nRAW_EXCEPTION_CLASS=ImportError\n", "", 1),
        ("", "raw traceback secret", 0),
    ):
        with pytest.raises(diagnostic.HistoryPageError):
            diagnostic.parse_page_output(payload, stderr, returncode)


def test_parent_never_preserves_nonzero_child_output(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _verified(monkeypatch)

    def fake_run(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv,
            1,
            f"{diagnostic.REMOTE_BEGIN}=true\nraw-secret\n",
            "traceback secret",
        )

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
    assert diagnostic._run_once() == 2
    output = capsys.readouterr().out
    assert "raw-secret" not in output
    assert "traceback secret" not in output
    assert "FAILURE_STAGE=OUTPUT_ALLOWLIST" in output
    assert "MESSAGE_ORDINAL=0" in output


def test_nested_child_stderr_is_fail_closed_without_forwarding() -> None:
    helper = diagnostic.REMOTE_HELPER
    nested = helper[helper.index('result = run(COMPOSE + ["exec"') :]
    assert "if result.returncode != 0 or result.stderr:" in nested
    assert nested.index("if result.returncode != 0 or result.stderr:") < nested.index(
        "print(result.stdout, end=\"\")"
    )
    assert 'stop("STAGE_1_RUNTIME", RuntimeError())' in nested
    assert 'emit("HISTORY_PAGE_REMOTE_END", "true")' in nested

    with pytest.raises(diagnostic.HistoryPageError):
        diagnostic.parse_page_output(
            "FIRST_PAGE_PASS=true\nMESSAGES_SEEN=0\nENTRIES_CONVERTED=0\nENTRIES_NONE=0\n",
            "child stderr secret",
            0,
        )


def test_nested_runtime_failure_protocol_contains_only_safe_fields() -> None:
    parsed = diagnostic.parse_page_output(
        "FAILURE_STAGE=STAGE_1_RUNTIME\n"
        "RAW_EXCEPTION_CLASS=RuntimeError\n"
        "MESSAGE_ORDINAL=0\nTELEGRAM_NETWORK_CALLS=0\n",
        "",
        0,
    )
    assert set(parsed) == {
        "FAILURE_STAGE",
        "RAW_EXCEPTION_CLASS",
        "MESSAGE_ORDINAL",
        "TELEGRAM_NETWORK_CALLS",
    }


def test_stage_transitions_are_narrow_and_not_counter_inferred() -> None:
    helper = diagnostic.REMOTE_HELPER
    assert 'failure_stage = "STAGE_2_CONNECT"' in helper
    assert 'failure_stage = "STAGE_2_AUTHORIZED"' in helper
    assert 'failure_stage = "STAGE_3_ITERATION"' in helper
    assert 'failure_stage = "STAGE_3_CONVERSION"' in helper
    assert "authorized_calls == 0" not in helper
    assert "authorized_calls == 0 else" not in helper
    assert "min(messages_seen + 1, PAGE_SIZE)" in helper
    assert "failure_ordinal = messages_seen" in helper


def test_child_failure_does_not_retry_after_remote_start(monkeypatch: pytest.MonkeyPatch) -> None:
    _verified(monkeypatch)
    calls = 0

    def fake_run(argv, **_kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            argv,
            0,
            f"{diagnostic.REMOTE_BEGIN}=true\nFAILURE_STAGE=STAGE_3_CONVERSION\nRAW_EXCEPTION_CLASS=ValueError\nMESSAGE_ORDINAL=1\n{diagnostic.REMOTE_END}=true\n",
            "",
        )

    monkeypatch.setattr(diagnostic.subprocess, "run", fake_run)
    assert diagnostic._run_once() == 0
    assert calls == 1
