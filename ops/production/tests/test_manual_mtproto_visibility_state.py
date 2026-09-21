"""Local-only protocol and static safety checks for M4AT1."""

import ast
import importlib.util
import subprocess
import unittest
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "visibility", OPS / "manual_mtproto_visibility_state.py"
)
visibility = importlib.util.module_from_spec(spec)
spec.loader.exec_module(visibility)


def valid(*, active=False, imported=49):
    lines = [f"{key}=true" for key, _ in visibility.GUARDS]
    lines.extend(
        [
            "ACCOUNT_EXACTLY_ONE=true",
            "MANUAL_SELECTED_EXACTLY_ONE=true",
            "MANUAL_SELECTED=true",
            f"SCOPE_ACTIVE={'true' if active else 'false'}",
            "HISTORY_COMPLETE=true",
            "BACKFILL_CURSOR_PRESENT=false",
            f"IMPORTED_OBJECT_COUNT={imported}",
            f"ACTIVE_VISIBLE_OBJECT_COUNT={imported if active else 0}",
            "TELEGRAM_NETWORK_CALLS=0",
            "M4AT1_TERMINAL=success",
        ]
    )
    return "\n".join(lines) + "\n"


class VisibilityProbeTests(unittest.TestCase):
    def test_inactive_scope_transcript(self):
        self.assertEqual(visibility.parse_output(valid()), "success")

    def test_active_scope_transcript(self):
        self.assertEqual(visibility.parse_output(valid(active=True)), "success")

    def test_zero_imported_objects(self):
        self.assertEqual(visibility.parse_output(valid(imported=0)), "success")

    def test_premature_eof_at_each_stage(self):
        transcript = valid()
        for count in range(len(transcript.splitlines(keepends=True))):
            with self.subTest(count=count), self.assertRaises(visibility.Incomplete):
                visibility.parse_output(
                    "".join(transcript.splitlines(keepends=True)[:count])
                )

    def test_unsafe_or_unknown_output_fails_closed(self):
        transcript = valid()
        invalid = (
            transcript + "SECRET=bad\n",
            transcript.replace("SCOPE_ACTIVE=false", "SCOPE_ACTIVE=bad"),
            transcript.replace(
                "ACTIVE_VISIBLE_OBJECT_COUNT=0", "ACTIVE_VISIBLE_OBJECT_COUNT=50"
            ),
            "M4AT1_TERMINAL=success\n",
        )
        for output in invalid:
            with self.subTest(output=output), self.assertRaises(ValueError):
                visibility.parse_output(output)

    def test_failure_transcript_is_terminal_and_zero_provider(self):
        lines = [f"{key}=true" for key, _ in visibility.GUARDS]
        lines += [
            "FAILURE_STAGE=STAGE_1_DB_SESSION",
            "RAW_EXCEPTION_CLASS=OperationalError",
            "TELEGRAM_NETWORK_CALLS=0",
            "M4AT1_TERMINAL=failure",
        ]
        self.assertEqual(visibility.parse_output("\n".join(lines) + "\n"), "failure")

    def test_partial_child_failure_is_terminal(self):
        lines = [f"{key}=true" for key, _ in visibility.GUARDS]
        lines += [
            "ACCOUNT_EXACTLY_ONE=false",
            "MANUAL_SELECTED_EXACTLY_ONE=false",
            "FAILURE_STAGE=STAGE_1_DB_SESSION",
            "RAW_EXCEPTION_CLASS=RuntimeError",
            "TELEGRAM_NETWORK_CALLS=0",
            "M4AT1_TERMINAL=failure",
        ]
        self.assertEqual(visibility.parse_output("\n".join(lines) + "\n"), "failure")

    def test_static_no_provider_or_write_path(self):
        source = (OPS / "manual_mtproto_visibility_state.py").read_text()
        tree = ast.parse(source)
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse(
            calls
            & {
                "commit",
                "flush",
                "add",
                "add_all",
                "delete",
                "execute",
                "upsert",
                "connect",
                "is_user_authorized",
                "iter_messages",
            }
        )
        for forbidden in (
            "TelegramClient",
            "fetch_history",
            "Sync",
            "login",
            "materialize",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("autoflush=False", source)
        self.assertIn("telegram_mtproto_active_object_predicate", source)

    def test_wrapper_syntax_and_pinned_public_key_transport(self):
        wrapper = OPS / "manual_mtproto_visibility_state_probe.sh"
        subprocess.run(["bash", "-n", str(wrapper)], check=True)
        source = wrapper.read_text()
        for option in (
            "StrictHostKeyChecking=yes",
            "HostKeyAlgorithms=ssh-ed25519",
            "PasswordAuthentication=no",
            "KbdInteractiveAuthentication=no",
            "PreferredAuthentications=publickey",
        ):
            self.assertIn(option, source)
        bundle = subprocess.run(
            ["python3", str(OPS / "manual_mtproto_visibility_state.py"), "bundle"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("remote_main()", bundle)


if __name__ == "__main__":
    unittest.main()
