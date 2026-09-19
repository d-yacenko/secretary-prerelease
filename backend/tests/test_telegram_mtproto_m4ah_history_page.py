from __future__ import annotations

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
        ("FIRST_PAGE_PASS=true\nMESSAGES_SEEN=100\nENTRIES_CONVERTED=99\nENTRIES_NONE=1\n", "FIRST_PAGE_PASS"),
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
