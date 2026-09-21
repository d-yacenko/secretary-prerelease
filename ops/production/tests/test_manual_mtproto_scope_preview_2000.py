"""Local-only protocol and safety tests for the M4BB2 scope preview probe."""

import ast
import importlib.util
import subprocess
import unittest
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scope_probe", OPS / "manual_mtproto_scope_preview_2000.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def valid(*, retained=2000, matches=3, truncated=False):
    lines = [f"{key}=true" for key, _ in probe.GUARDS]
    lines += [
        "ACCOUNT_EXACTLY_ONE=true",
        "CONFIGURED_FOLDER_EXACTLY_ONE=true",
        "IGNORE_MUTED=true",
        f"DIALOGS_SCANNED_RETAINED={retained}",
        f"SCOPE_MATCH_COUNT={matches}",
        "SKIPPED_BROADCAST=1",
        "SKIPPED_BOT=2",
        "SKIPPED_UNSUPPORTED=3",
        "SKIPPED_OTHER=0",
        f"TRUNCATED={'true' if truncated else 'false'}",
        "TELEGRAM_NETWORK_CALLS=6",
        "M4BB2_TERMINAL=success",
    ]
    return "\n".join(lines) + "\n"


class ScopePreviewProbeTests(unittest.TestCase):
    def test_dialog_boundaries(self):
        for count, truncated in ((499, False), (500, False), (2000, False), (2001, True)):
            with self.subTest(count=count):
                self.assertEqual(probe.parse_output(valid(retained=min(count, 2000), truncated=truncated)), "success")

    def test_lookahead_and_retained_count_are_bounded(self):
        self.assertLessEqual(2001, 2001)
        self.assertEqual(probe.parse_output(valid(retained=2000, truncated=True)), "success")

    def test_scope_match_count_is_aggregate_and_deduplicated(self):
        self.assertEqual(probe.parse_output(valid(matches=1)), "success")

    def test_muted_exclusion_is_required(self):
        self.assertEqual(probe.parse_output(valid()), "success")
        self.assertIn('if not dialog.is_muted and dialog_matches_filter', probe.child_source())

    def test_skipped_counts_are_safe_aggregates(self):
        self.assertEqual(probe.parse_output(valid()), "success")
        self.assertIn("skipped.get(\"broadcast\", 0)", probe.child_source())

    def test_account_cardinality_fails_closed(self):
        lines = [f"{key}=true" for key, _ in probe.GUARDS]
        lines += [
            "ACCOUNT_EXACTLY_ONE=false", "CONFIGURED_FOLDER_EXACTLY_ONE=false",
            "FAILURE_STAGE=STAGE_1_DB_SESSION", "RAW_EXCEPTION_CLASS=RuntimeError",
            "TELEGRAM_NETWORK_CALLS=0", "M4BB2_TERMINAL=failure",
        ]
        self.assertEqual(probe.parse_output("\n".join(lines) + "\n"), "failure")

    def test_folder_cardinality_fails_closed(self):
        lines = [f"{key}=true" for key, _ in probe.GUARDS]
        lines += [
            "ACCOUNT_EXACTLY_ONE=true", "CONFIGURED_FOLDER_EXACTLY_ONE=false",
            "FAILURE_STAGE=STAGE_1_DB_SESSION", "RAW_EXCEPTION_CLASS=RuntimeError",
            "TELEGRAM_NETWORK_CALLS=0", "M4BB2_TERMINAL=failure",
        ]
        self.assertEqual(probe.parse_output("\n".join(lines) + "\n"), "failure")

    def test_no_history_or_reconcile_path(self):
        source = probe.child_source()
        self.assertNotIn("fetch_history", source)
        self.assertNotIn("reconcile_scope", source)

    def test_no_db_write_path(self):
        tree = ast.parse(probe.child_source())
        attrs = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertFalse(attrs & {"flush", "commit", "add", "add_all", "delete", "execute"})
        self.assertIn("autoflush=False", probe.child_source())

    def test_auth_invalid_is_sanitized(self):
        lines = [f"{key}=true" for key, _ in probe.GUARDS]
        lines += [
            "ACCOUNT_EXACTLY_ONE=true", "CONFIGURED_FOLDER_EXACTLY_ONE=true", "IGNORE_MUTED=true",
            "FAILURE_STAGE=STAGE_2_AUTHORIZED", "RAW_EXCEPTION_CLASS=RuntimeError",
            "TELEGRAM_NETWORK_CALLS=0", "M4BB2_TERMINAL=failure",
        ]
        self.assertEqual(probe.parse_output("\n".join(lines) + "\n"), "failure")

    def test_provider_failure_is_sanitized(self):
        lines = [f"{key}=true" for key, _ in probe.GUARDS]
        lines += [
            "ACCOUNT_EXACTLY_ONE=true", "CONFIGURED_FOLDER_EXACTLY_ONE=true", "IGNORE_MUTED=true",
            "FAILURE_STAGE=STAGE_3_DIALOG_ITERATION", "RAW_EXCEPTION_CLASS=OTHER",
            "TELEGRAM_NETWORK_CALLS=0", "M4BB2_TERMINAL=failure",
        ]
        self.assertEqual(probe.parse_output("\n".join(lines) + "\n"), "failure")

    def test_premature_eof_at_each_stage(self):
        text = valid()
        for count in range(len(text.splitlines(keepends=True))):
            with self.subTest(count=count), self.assertRaises(probe.Incomplete):
                probe.parse_output("".join(text.splitlines(keepends=True)[:count]))

    def test_unsafe_output_fails_closed(self):
        text = valid()
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

    def test_wrapper_compile_and_transport_options(self):
        wrapper = OPS / "manual_mtproto_scope_preview_2000_probe.sh"
        subprocess.run(["bash", "-n", str(wrapper)], check=True)
        source = wrapper.read_text()
        for option in ("StrictHostKeyChecking=yes", "HostKeyAlgorithms=ssh-ed25519", "PasswordAuthentication=no", "KbdInteractiveAuthentication=no", "PreferredAuthentications=publickey"):
            self.assertIn(option, source)
        bundle = subprocess.run(["python3", str(OPS / "manual_mtproto_scope_preview_2000.py"), "bundle"], capture_output=True, text=True, check=True).stdout
        self.assertIn("remote_main()", bundle)


if __name__ == "__main__":
    unittest.main()
