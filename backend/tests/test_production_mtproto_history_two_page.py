from __future__ import annotations

import ast
import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

PROBE_PATH = Path(__file__).resolve().parents[2] / "ops/production/diagnose_mtproto_history_two_page.py"
PROBE_SPEC = importlib.util.spec_from_file_location("history_two_page_probe", PROBE_PATH)
assert PROBE_SPEC and PROBE_SPEC.loader
probe = importlib.util.module_from_spec(PROBE_SPEC)
sys.modules[PROBE_SPEC.name] = probe
PROBE_SPEC.loader.exec_module(probe)


SCRIPT = Path("ops/production/diagnose_mtproto_history_two_page.py").read_text()


def _success(*, page2: bool = False) -> str:
    lines = [
        f"{probe.REMOTE_BEGIN}=true",
        "STAGE_0_ACCOUNT_EXACTLY_ONE=true",
        "STAGE_0_MANUAL_SELECTED_GROUP_EXACTLY_ONE=true",
        "INITIAL_STATE=true",
        "HISTORY_COMPLETE_BEFORE=false",
        "BACKFILL_CURSOR_PRESENT_BEFORE=false",
        f"PAGE2_REQUIRED={'true' if page2 else 'false'}",
        "SESSION_DECRYPT_PASS=true",
        "STRING_SESSION_PARSE_PASS=true",
        "REFERENCE_DECRYPT_PASS=true",
        "REFERENCE_PARSE_PASS=true",
        "REFERENCE_PEER_MATCH_PASS=true",
        "PAGE1_PASS=true",
        "PAGE1_MESSAGES_SEEN=100",
        "PAGE1_ENTRIES_CONVERTED=100",
        "PAGE1_ENTRIES_NONE=0",
    ]
    if page2:
        lines.extend(
            [
                "PAGE2_PASS=true",
                "PAGE2_MESSAGES_SEEN=100",
                "PAGE2_ENTRIES_CONVERTED=100",
                "PAGE2_ENTRIES_NONE=0",
            ]
        )
    lines.extend(
        [
            f"MESSAGES_SEEN_TOTAL={'200' if page2 else '100'}",
            f"ENTRIES_CONVERTED_TOTAL={'200' if page2 else '100'}",
            f"CONNECT_CALL_COUNT={'2' if page2 else '1'}",
            f"IS_USER_AUTHORIZED_CALL_COUNT={'2' if page2 else '1'}",
            f"ITER_MESSAGES_CALL_COUNT={'2' if page2 else '1'}",
            f"TELEGRAM_NETWORK_CALLS={'6' if page2 else '3'}",
            f"{probe.REMOTE_END}=true",
        ]
    )
    return "\n".join(lines) + "\n"


def test_embedded_child_compiles_independently() -> None:
    tree = ast.parse(SCRIPT)
    children = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "PAGE_SIZE = 100" in node.value
    ]
    assert len(children) == 1
    compile(children[0], "<history-two-page-child>", "exec")


def test_child_owns_page_size_100() -> None:
    assert "PAGE_SIZE = 100" in probe.REMOTE_HELPER


def test_max_total_messages_is_200() -> None:
    assert probe.MAX_MESSAGES == 200
    parsed = probe.parse_output(_success(page2=True), "", 0)
    assert int(parsed["MESSAGES_SEEN_TOTAL"]) <= 200


@pytest.mark.parametrize(
    ("latest", "complete", "cursor", "expected"),
    [
        (None, False, 12, False),
        (100, False, 12, True),
        (100, True, 12, False),
        (100, False, None, False),
    ],
)
def test_state_correctly_decides_page2_required(
    latest: int | None, complete: bool, cursor: int | None, expected: bool
) -> None:
    assert probe.page2_required_before(
        latest=latest, history_complete=complete, cursor=cursor
    ) is expected


def test_initial_first_page_derives_second_page_cursor_without_emitting_id() -> None:
    cutoff = datetime.now(UTC) - timedelta(days=14)
    entries = [
        SimpleNamespace(message_id=101, occurred_at=cutoff + timedelta(days=1)),
        SimpleNamespace(message_id=99, occurred_at=cutoff + timedelta(days=1)),
    ]
    cursor, complete = probe.initial_page2_state(entries, has_more=True, cutoff=cutoff)
    assert cursor == 99
    assert complete is False
    parsed = probe.parse_output(_success(), "", 0)
    assert "99" not in "\n".join(parsed.values())


@pytest.mark.parametrize(
    "stage",
    ["STAGE_3_PAGE1_ITERATION", "STAGE_3_PAGE1_CONVERSION"],
)
def test_page1_value_or_type_failure_has_page1_stage(stage: str) -> None:
    output = (
        f"{probe.REMOTE_BEGIN}=true\nFAILURE_STAGE={stage}\n"
        "RAW_EXCEPTION_CLASS=ValueError\nMESSAGE_ORDINAL=1\n"
        "TELEGRAM_NETWORK_CALLS=3\n"
        f"{probe.REMOTE_END}=true\n"
    )
    assert probe.parse_output(output, "", 0)["FAILURE_STAGE"] == stage


@pytest.mark.parametrize(
    "stage",
    ["STAGE_5_PAGE2_ITERATION", "STAGE_5_PAGE2_CONVERSION"],
)
def test_page2_value_or_type_failure_has_page2_stage(stage: str) -> None:
    output = (
        f"{probe.REMOTE_BEGIN}=true\nPAGE1_PASS=true\n"
        "PAGE1_MESSAGES_SEEN=100\nPAGE1_ENTRIES_CONVERTED=100\n"
        "PAGE1_ENTRIES_NONE=0\nPAGE2_REQUIRED=true\n"
        f"FAILURE_STAGE={stage}\nRAW_EXCEPTION_CLASS=TypeError\n"
        "MESSAGE_ORDINAL=1\nTELEGRAM_NETWORK_CALLS=6\n"
        f"{probe.REMOTE_END}=true\n"
    )
    assert probe.parse_output(output, "", 0)["FAILURE_STAGE"] == stage


def test_realistic_page2_iteration_failure_is_accepted() -> None:
    output = (
        f"{probe.REMOTE_BEGIN}=true\nPAGE1_PASS=true\n"
        "PAGE1_MESSAGES_SEEN=100\nPAGE1_ENTRIES_CONVERTED=100\n"
        "PAGE1_ENTRIES_NONE=0\nPAGE2_REQUIRED=true\n"
        "FAILURE_STAGE=STAGE_5_PAGE2_ITERATION\n"
        "RAW_EXCEPTION_CLASS=TypeError\nMESSAGE_ORDINAL=1\n"
        "TELEGRAM_NETWORK_CALLS=6\n"
        f"{probe.REMOTE_END}=true\n"
    )
    assert probe.parse_output(output, "", 0)["PAGE1_PASS"] == "true"


def test_realistic_page2_conversion_failure_is_accepted() -> None:
    output = (
        f"{probe.REMOTE_BEGIN}=true\nPAGE1_PASS=true\n"
        "PAGE1_MESSAGES_SEEN=100\nPAGE1_ENTRIES_CONVERTED=100\n"
        "PAGE1_ENTRIES_NONE=0\nPAGE2_REQUIRED=true\n"
        "FAILURE_STAGE=STAGE_5_PAGE2_CONVERSION\n"
        "RAW_EXCEPTION_CLASS=InvalidHistoryEntry\nMESSAGE_ORDINAL=1\n"
        "TELEGRAM_NETWORK_CALLS=6\n"
        f"{probe.REMOTE_END}=true\n"
    )
    assert probe.parse_output(output, "", 0)["RAW_EXCEPTION_CLASS"] == "InvalidHistoryEntry"


def test_page2_failure_when_not_required_is_rejected() -> None:
    output = (
        f"{probe.REMOTE_BEGIN}=true\nPAGE1_PASS=true\n"
        "PAGE1_MESSAGES_SEEN=100\nPAGE1_ENTRIES_CONVERTED=100\n"
        "PAGE1_ENTRIES_NONE=0\nPAGE2_REQUIRED=false\n"
        "FAILURE_STAGE=STAGE_5_PAGE2_ITERATION\nRAW_EXCEPTION_CLASS=TypeError\n"
        "MESSAGE_ORDINAL=1\nTELEGRAM_NETWORK_CALLS=3\n"
        f"{probe.REMOTE_END}=true\n"
    )
    with pytest.raises(probe.HistoryProbeError):
        probe.parse_output(output, "", 0)


def test_page2_pass_and_page2_failure_are_rejected() -> None:
    output = (
        f"{probe.REMOTE_BEGIN}=true\nPAGE1_PASS=true\n"
        "PAGE1_MESSAGES_SEEN=100\nPAGE1_ENTRIES_CONVERTED=100\n"
        "PAGE1_ENTRIES_NONE=0\nPAGE2_REQUIRED=true\nPAGE2_PASS=true\n"
        "FAILURE_STAGE=STAGE_5_PAGE2_ITERATION\nRAW_EXCEPTION_CLASS=TypeError\n"
        "MESSAGE_ORDINAL=1\nTELEGRAM_NETWORK_CALLS=6\n"
        f"{probe.REMOTE_END}=true\n"
    )
    with pytest.raises(probe.HistoryProbeError):
        probe.parse_output(output, "", 0)


def test_page1_pass_and_page1_failure_are_rejected() -> None:
    output = (
        f"{probe.REMOTE_BEGIN}=true\nPAGE1_PASS=true\n"
        "FAILURE_STAGE=STAGE_3_PAGE1_ITERATION\nRAW_EXCEPTION_CLASS=ValueError\n"
        "MESSAGE_ORDINAL=1\nTELEGRAM_NETWORK_CALLS=3\n"
        f"{probe.REMOTE_END}=true\n"
    )
    with pytest.raises(probe.HistoryProbeError):
        probe.parse_output(output, "", 0)


@pytest.mark.parametrize(
    "stage",
    ["STAGE_2_PAGE1_CONNECT", "STAGE_2_PAGE1_AUTHORIZED", "STAGE_4_PAGE2_CONNECT", "STAGE_4_PAGE2_AUTHORIZED"],
)
def test_auth_exceptions_retain_page_specific_stage(stage: str) -> None:
    prefix = ""
    if stage.startswith("STAGE_4_"):
        prefix = (
            "PAGE1_PASS=true\nPAGE1_MESSAGES_SEEN=100\n"
            "PAGE1_ENTRIES_CONVERTED=100\nPAGE1_ENTRIES_NONE=0\n"
            "PAGE2_REQUIRED=true\n"
        )
    output = (
        f"{probe.REMOTE_BEGIN}=true\n{prefix}FAILURE_STAGE={stage}\n"
        "RAW_EXCEPTION_CLASS=AuthKeyError\nMESSAGE_ORDINAL=0\n"
        "TELEGRAM_NETWORK_CALLS=1\n"
        f"{probe.REMOTE_END}=true\n"
    )
    assert probe.parse_output(output, "", 0)["FAILURE_STAGE"] == stage


def test_conversion_none_is_conversion_failure() -> None:
    output = (
        f"{probe.REMOTE_BEGIN}=true\nFAILURE_STAGE=STAGE_3_PAGE1_CONVERSION\n"
        "RAW_EXCEPTION_CLASS=InvalidHistoryEntry\nMESSAGE_ORDINAL=1\n"
        "TELEGRAM_NETWORK_CALLS=3\n"
        f"{probe.REMOTE_END}=true\n"
    )
    assert probe.parse_output(output, "", 0)["RAW_EXCEPTION_CLASS"] == "InvalidHistoryEntry"


def test_invalid_history_entry_is_a_local_safe_class() -> None:
    assert "class InvalidHistoryEntry" in probe.REMOTE_HELPER
    assert "InvalidHistoryEntry()" in probe.REMOTE_HELPER


def test_structural_failures_are_terminal_and_sanitized() -> None:
    assert "raise SystemExit(0)" in probe.REMOTE_HELPER
    assert "stderr" not in probe.REMOTE_HELPER.split("child =", 1)[1].split('"""', 1)[0]


def test_fresh_client_per_page_and_single_iterator_per_page() -> None:
    assert SCRIPT.count("TelegramClient(StringSession") == 1
    assert "first = await page(1" in SCRIPT
    assert "second = await page(2" in SCRIPT
    assert SCRIPT.count("client.iter_messages(") == 1


def test_max_two_pages() -> None:
    assert "page(3" not in SCRIPT
    assert "MAX_MESSAGES = 200" in probe.REMOTE_HELPER


def test_disconnect_per_page() -> None:
    assert SCRIPT.count("await client.disconnect()") == 1
    assert "finally:" in SCRIPT


def test_no_application_fetch_history() -> None:
    assert "fetch_history(" not in probe.REMOTE_HELPER
    assert "TelegramMtprotoHistoryService" not in probe.REMOTE_HELPER


def test_no_db_writes_or_materializer() -> None:
    forbidden = ("session.add", "session.flush", "session.commit", "materializer", "upsert_mtproto")
    assert not any(token in probe.REMOTE_HELPER for token in forbidden)


def test_no_login_discovery_or_write_rpc() -> None:
    forbidden = ("send_code", "submit_code", "send_message", "edit_message", "delete_messages", "iter_dialogs", "get_messages", "send_read_acknowledge")
    assert not any(token in probe.REMOTE_HELPER for token in forbidden)


def test_no_content_or_identifier_output() -> None:
    parsed = probe.parse_output(_success(), "", 0)
    forbidden_keys = {"message_id", "peer_id", "sender_id", "session", "reference", "timestamp"}
    assert not any(key.lower() in forbidden_keys for key in parsed)
    assert "message.message" not in "\n".join(parsed.values())


def test_stderr_nonzero_and_malformed_fail_closed() -> None:
    with pytest.raises(probe.HistoryProbeError):
        probe.parse_output(_success(), "hidden stderr", 0)
    with pytest.raises(probe.HistoryProbeError):
        probe.parse_output(_success(), "", 1)
    with pytest.raises(probe.HistoryProbeError):
        probe.parse_output(_success() + "SECRET=bad\n", "", 0)


def test_success_counts_are_consistent_and_entries_none_zero() -> None:
    parsed = probe.parse_output(_success(page2=True), "", 0)
    assert parsed["PAGE1_MESSAGES_SEEN"] == parsed["PAGE1_ENTRIES_CONVERTED"]
    assert parsed["PAGE2_MESSAGES_SEEN"] == parsed["PAGE2_ENTRIES_CONVERTED"]
    assert parsed["PAGE1_ENTRIES_NONE"] == parsed["PAGE2_ENTRIES_NONE"] == "0"
    assert int(parsed["MESSAGES_SEEN_TOTAL"]) <= 200


def test_page2_false_cannot_emit_page2_result() -> None:
    with pytest.raises(probe.HistoryProbeError):
        probe.parse_output(_success() + "PAGE2_PASS=true\n", "", 0)


def test_page2_success_requires_page2_counts() -> None:
    output = _success(page2=True).replace("PAGE2_ENTRIES_NONE=0\n", "")
    with pytest.raises(probe.HistoryProbeError):
        probe.parse_output(output, "", 0)


def test_raw_exception_class_is_identifier_only() -> None:
    output = _success().replace(
        f"{probe.REMOTE_END}=true", "RAW_EXCEPTION_CLASS=bad message\n" + f"{probe.REMOTE_END}=true"
    )
    with pytest.raises(probe.HistoryProbeError):
        probe.parse_output(output, "", 0)


def test_ssh_budget_and_strict_target_are_fixed() -> None:
    argv = probe.build_ssh_argv("/tmp/known_hosts")
    assert probe.MAX_ATTEMPTS == 3
    assert argv[-3:] == [probe.EXPECTED_TARGET, "python3", "-"]
    assert "HostKeyAlgorithms=ssh-ed25519" in argv
    assert "StrictHostKeyChecking=yes" in argv
    assert "GlobalKnownHostsFile=/dev/null" in argv
