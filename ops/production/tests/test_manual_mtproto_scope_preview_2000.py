"""Local-only child-logic and protocol tests for M4BB2."""

import ast
import asyncio
import importlib.util
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace

OPS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scope_probe", OPS / "manual_mtproto_scope_preview_2000.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
CHILD = probe.child_source()


def valid(*, retained=2000, matches=3, truncated=False):
    lines = [f"{key}=true" for key, _ in probe.GUARDS]
    lines += [
        "ACCOUNT_EXACTLY_ONE=true", "CONFIGURED_FOLDER_EXACTLY_ONE=true", "IGNORE_MUTED=true",
        f"DIALOGS_SCANNED_RETAINED={retained}", f"SCOPE_MATCH_COUNT={matches}",
        "SKIPPED_BROADCAST=1", "SKIPPED_BOT=2", "SKIPPED_UNSUPPORTED=3", "SKIPPED_OTHER=0",
        f"TRUNCATED={'true' if truncated else 'false'}", "TELEGRAM_NETWORK_CALLS=6",
        "M4BB2_TERMINAL=success",
    ]
    return "\n".join(lines) + "\n"


def child_scan_function(*, converter=None, matcher=None):
    tree = ast.parse(CHILD)
    node = next(item for item in tree.body if isinstance(item, ast.AsyncFunctionDef) and item.name == "scan_dialogs")
    namespace = {
        "SCOPE_DIALOG_SCAN_LIMIT": 2000,
        "DialogConversionError": type("DialogConversionError", (RuntimeError,), {}),
        "_dialog_from_dialog": converter or (lambda value: (value, None)),
        "dialog_matches_filter": matcher or (lambda _definition, _dialog: True),
    }
    exec(compile(ast.Module([node], type_ignores=[]), "child", "exec"), namespace)  # noqa: S102
    return namespace["scan_dialogs"]


class FakeDialogs:
    def __init__(self, dialogs, *, fail=None):
        self.dialogs = dialogs
        self.fail = fail
        self.requested = []
        self.consumed = 0

    def iter_dialogs(self, *, limit):
        self.requested.append(limit)

        async def iterator():
            for item in self.dialogs:
                self.consumed += 1
                if self.fail is not None and self.consumed == self.fail:
                    raise RuntimeError("provider")
                yield item

        return iterator()


def run_scan(dialogs, *, converter=None, matcher=None, fail=None):
    client = FakeDialogs(dialogs, fail=fail)
    result = asyncio.run(child_scan_function(converter=converter, matcher=matcher)(client, object()))
    return result, client


class ScopePreviewProbeTests(unittest.TestCase):
    def test_child_boundaries(self):
        for count, expected_truncated in ((499, False), (500, False), (2000, False), (2001, True)):
            with self.subTest(count=count):
                (retained, _matched, _skipped, truncated), client = run_scan(
                    [SimpleNamespace(peer_id=index, is_muted=False) for index in range(count)]
                )
                self.assertEqual(client.requested, [2001])
                self.assertEqual(client.consumed, min(count, 2001))
                self.assertEqual(len(retained), min(count, 2000))
                self.assertEqual(truncated, expected_truncated)

    def test_child_source_is_current_production_compatible(self):
        self.assertNotIn("TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT", CHILD)
        self.assertNotIn("fetch_dialog_universe", CHILD)
        self.assertIn("SCOPE_DIALOG_SCAN_LIMIT = 2000", CHILD)
        self.assertIn("iter_dialogs(limit=SCOPE_DIALOG_SCAN_LIMIT + 1)", CHILD)

    def test_child_skips_only_retained_window(self):
        converter = lambda value: (None, "bot") if value.peer_id % 2 == 0 else (value, None)
        (retained, _matched, skipped, truncated), _client = run_scan(
            [SimpleNamespace(peer_id=index, is_muted=False) for index in range(2001)], converter=converter
        )
        self.assertTrue(truncated)
        self.assertEqual(len(retained), 1000)
        self.assertEqual(skipped, {"bot": 1000})

    def test_child_muted_exclusion_and_peer_dedupe(self):
        dialogs = [
            SimpleNamespace(peer_id=7, is_muted=False), SimpleNamespace(peer_id=7, is_muted=False),
            SimpleNamespace(peer_id=8, is_muted=True), SimpleNamespace(peer_id=9, is_muted=False),
        ]
        retained, matched, _skipped, _truncated = run_scan(dialogs)[0]
        self.assertEqual(len(retained), 4)
        self.assertEqual(matched, {7, 9})

    def test_account_cardinality_fail_closed_network_zero(self):
        lines = [f"{key}=true" for key, _ in probe.GUARDS] + [
            "ACCOUNT_EXACTLY_ONE=false", "CONFIGURED_FOLDER_EXACTLY_ONE=false",
            "FAILURE_STAGE=STAGE_1_ACCOUNT_CARDINALITY", "RAW_EXCEPTION_CLASS=RuntimeError",
            "TELEGRAM_NETWORK_CALLS=0", "M4BB2_TERMINAL=failure",
        ]
        self.assertEqual(probe.parse_output("\n".join(lines) + "\n"), "failure")

    def test_folder_cardinality_fail_closed_network_zero(self):
        lines = [f"{key}=true" for key, _ in probe.GUARDS] + [
            "ACCOUNT_EXACTLY_ONE=true", "CONFIGURED_FOLDER_EXACTLY_ONE=false",
            "FAILURE_STAGE=STAGE_1_FOLDER_CARDINALITY", "RAW_EXCEPTION_CLASS=RuntimeError",
            "TELEGRAM_NETWORK_CALLS=0", "M4BB2_TERMINAL=failure",
        ]
        self.assertEqual(probe.parse_output("\n".join(lines) + "\n"), "failure")

    def test_provider_stage_failures_are_nonzero(self):
        for stage in ("STAGE_2_FOLDER_DISCOVERY", "STAGE_2_AUTHORIZED", "STAGE_2_FOLDER_DEFINITIONS", "STAGE_3_DIALOG_CONNECT", "STAGE_3_DIALOG_AUTHORIZED", "STAGE_3_DIALOG_ITERATION", "STAGE_3_DIALOG_CONVERSION"):
            lines = [f"{key}=true" for key, _ in probe.GUARDS] + [
                "ACCOUNT_EXACTLY_ONE=true", "CONFIGURED_FOLDER_EXACTLY_ONE=true", "IGNORE_MUTED=true",
                f"FAILURE_STAGE={stage}", "RAW_EXCEPTION_CLASS=OTHER", "TELEGRAM_NETWORK_CALLS=1",
                "M4BB2_TERMINAL=failure",
            ]
            with self.subTest(stage=stage):
                self.assertEqual(probe.parse_output("\n".join(lines) + "\n"), "failure")

    def test_fake_provider_iteration_and_conversion_failures(self):
        with self.assertRaises(RuntimeError):
            run_scan([SimpleNamespace(peer_id=1, is_muted=False)], fail=1)
        with self.assertRaises(RuntimeError):
            run_scan([SimpleNamespace(peer_id=1, is_muted=False)], converter=lambda _value: (_ for _ in ()).throw(ValueError()))

    def test_disconnect_is_finally_attempted(self):
        self.assertIn("finally:\n            await disconnect(folder_client)", CHILD)
        self.assertIn("finally:\n            await disconnect(dialog_client)", CHILD)
        self.assertIn("with suppress(Exception):", CHILD)

    def test_no_history_message_reconcile_or_db_write(self):
        self.assertNotIn("fetch_history", CHILD)
        self.assertNotIn("fetch_message", CHILD)
        self.assertNotIn("reconcile_scope", CHILD)
        tree = ast.parse(CHILD)
        attrs = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertFalse(attrs & {"flush", "commit", "add", "add_all", "delete", "execute"})
        self.assertIn("autoflush=False", CHILD)

    def test_protocol_success_and_bounds(self):
        self.assertEqual(probe.parse_output(valid(retained=2000, truncated=False)), "success")
        self.assertEqual(probe.parse_output(valid(retained=2000, truncated=True)), "success")

    def test_premature_eof_and_unsafe_output_fail_closed(self):
        text = valid()
        for count in range(len(text.splitlines(keepends=True))):
            with self.subTest(count=count), self.assertRaises(probe.Incomplete):
                probe.parse_output("".join(text.splitlines(keepends=True)[:count]))
        for unsafe in (text + "SECRET=value\n", text.replace("TRUNCATED=false", "TRUNCATED=maybe"), "M4BB2_TERMINAL=success\n"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                probe.parse_output(unsafe)

    def test_alembic_contract_and_stdin_isolation(self):
        command = probe.alembic_command(["docker", "compose"])
        self.assertIn('PGPASSWORD="$POSTGRES_PASSWORD"', command[-1])
        self.assertIn("-h 127.0.0.1", command[-1])
        self.assertIn('-U "${POSTGRES_USER:-secretary}"', command[-1])
        self.assertIn('-d "${POSTGRES_DB:-secretary}"', command[-1])
        self.assertEqual(command[1:4], ["compose", "exec", "-T"])

    def test_wrapper_syntax_helper_compile_and_transport_options(self):
        wrapper = OPS / "manual_mtproto_scope_preview_2000_probe.sh"
        subprocess.run(["bash", "-n", str(wrapper)], check=True)
        source = wrapper.read_text()
        for option in ("StrictHostKeyChecking=yes", "HostKeyAlgorithms=ssh-ed25519", "PasswordAuthentication=no", "KbdInteractiveAuthentication=no", "PreferredAuthentications=publickey"):
            self.assertIn(option, source)
        bundle = subprocess.run(["python3", str(OPS / "manual_mtproto_scope_preview_2000.py"), "bundle"], capture_output=True, text=True, check=True).stdout
        self.assertIn("remote_main()", bundle)


if __name__ == "__main__":
    unittest.main()
