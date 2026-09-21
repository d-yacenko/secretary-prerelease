"""Local-only protocol and static safety checks for M4AW2."""

import ast
import importlib.util
import subprocess
import unittest
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "eligibility", OPS / "manual_mtproto_inbox_eligibility.py"
)
eligibility = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eligibility)


def valid(
    *,
    active=False,
    imported=49,
    transport_visible=None,
    inbox=None,
    first_page_telegram=None,
    first_50_telegram=None,
    inbound=None,
    outbound=None,
    first_page_total=30,
):
    transport_visible = (
        imported
        if transport_visible is None and active
        else (0 if transport_visible is None else transport_visible)
    )
    inbox = transport_visible if inbox is None else inbox
    first_page_telegram = (
        (1 if inbox else 0) if first_page_telegram is None else first_page_telegram
    )
    first_50_telegram = (
        (1 if inbox else 0) if first_50_telegram is None else first_50_telegram
    )
    inbound = imported if inbound is None else inbound
    outbound = 0 if outbound is None else outbound
    lines = [f"{key}=true" for key, _ in eligibility.GUARDS]
    lines.extend(
        [
            "ACCOUNT_EXACTLY_ONE=true",
            "MANUAL_SELECTED_EXACTLY_ONE=true",
            "MANUAL_SELECTED=true",
            f"SCOPE_ACTIVE={'true' if active else 'false'}",
            "HISTORY_COMPLETE=true",
            "BACKFILL_CURSOR_PRESENT=false",
            f"IMPORTED_OBJECT_COUNT={imported}",
            f"TRANSPORT_VISIBLE_COUNT={transport_visible}",
            f"INBOUND_COUNT={inbound}",
            f"OUTBOUND_COUNT={outbound}",
            f"INBOX_ELIGIBLE_COUNT={inbox}",
            f"FIRST_PAGE_TOTAL_COUNT={first_page_total}",
            f"FIRST_PAGE_TELEGRAM_COUNT={first_page_telegram}",
            f"FIRST_50_TELEGRAM_COUNT={first_50_telegram}",
            "TELEGRAM_NETWORK_CALLS=0",
            "M4AW2_TERMINAL=success",
        ]
    )
    return "\n".join(lines) + "\n"


class InboxProbeTests(unittest.TestCase):
    def test_inactive_scope_transcript(self):
        self.assertEqual(eligibility.parse_output(valid()), "success")

    def test_active_scope_transcript(self):
        self.assertEqual(eligibility.parse_output(valid(active=True)), "success")

    def test_zero_imported_objects(self):
        self.assertEqual(
            eligibility.parse_output(
                valid(
                    imported=0,
                    inbox=0,
                    first_page_telegram=0,
                    first_50_telegram=0,
                    first_page_total=0,
                )
            ),
            "success",
        )

    def test_transport_visible_and_first_page_positive(self):
        self.assertEqual(
            eligibility.parse_output(
                valid(
                    active=True,
                    imported=4,
                    inbox=4,
                    first_page_telegram=4,
                    first_50_telegram=4,
                    first_page_total=4,
                )
            ),
            "success",
        )

    def test_inbox_eligible_but_first_page_zero(self):
        self.assertEqual(
            eligibility.parse_output(
                valid(
                    imported=4,
                    transport_visible=4,
                    inbox=4,
                    first_page_telegram=0,
                    first_50_telegram=2,
                )
            ),
            "success",
        )

    def test_transport_visible_zero_diagnostic(self):
        self.assertEqual(
            eligibility.parse_output(
                valid(
                    imported=4,
                    transport_visible=0,
                    inbox=0,
                    first_page_telegram=0,
                    first_50_telegram=0,
                )
            ),
            "success",
        )

    def test_outbound_only(self):
        self.assertEqual(
            eligibility.parse_output(
                valid(
                    imported=3,
                    transport_visible=3,
                    inbound=0,
                    outbound=3,
                    inbox=0,
                    first_page_telegram=0,
                    first_50_telegram=0,
                )
            ),
            "success",
        )

    def test_premature_eof_at_each_stage(self):
        transcript = valid()
        for count in range(len(transcript.splitlines(keepends=True))):
            with self.subTest(count=count), self.assertRaises(eligibility.Incomplete):
                eligibility.parse_output(
                    "".join(transcript.splitlines(keepends=True)[:count])
                )

    def test_unsafe_or_unknown_output_fails_closed(self):
        transcript = valid()
        invalid = (
            transcript + "SECRET=bad\n",
            transcript.replace("SCOPE_ACTIVE=false", "SCOPE_ACTIVE=bad"),
            transcript.replace(
                "TRANSPORT_VISIBLE_COUNT=0", "TRANSPORT_VISIBLE_COUNT=50"
            ),
            "M4AW2_TERMINAL=success\n",
        )
        for output in invalid:
            with self.subTest(output=output), self.assertRaises(ValueError):
                eligibility.parse_output(output)

    def test_failure_transcript_is_terminal_and_zero_provider(self):
        lines = [f"{key}=true" for key, _ in eligibility.GUARDS]
        lines += [
            "FAILURE_STAGE=STAGE_1_DB_SESSION",
            "RAW_EXCEPTION_CLASS=OperationalError",
            "TELEGRAM_NETWORK_CALLS=0",
            "M4AW2_TERMINAL=failure",
        ]
        self.assertEqual(eligibility.parse_output("\n".join(lines) + "\n"), "failure")

    def test_alembic_exact_revision_success_transcript(self):
        self.assertEqual(eligibility.parse_output(valid()), "success")

    def test_alembic_wrong_revision_fails_at_stage_zero(self):
        lines = [
            f"{key}={'false' if key == 'ALEMBIC_0046_PASS' else 'true'}"
            for key, _ in eligibility.GUARDS
        ]
        lines += [
            "FAILURE_STAGE=STAGE_0_ALEMBIC",
            "RAW_EXCEPTION_CLASS=RuntimeError",
            "TELEGRAM_NETWORK_CALLS=0",
            "M4AW2_TERMINAL=failure",
        ]
        self.assertEqual(eligibility.parse_output("\n".join(lines) + "\n"), "failure")

    def test_partial_child_failure_is_terminal(self):
        lines = [f"{key}=true" for key, _ in eligibility.GUARDS]
        lines += [
            "ACCOUNT_EXACTLY_ONE=false",
            "MANUAL_SELECTED_EXACTLY_ONE=false",
            "FAILURE_STAGE=STAGE_1_DB_SESSION",
            "RAW_EXCEPTION_CLASS=RuntimeError",
            "TELEGRAM_NETWORK_CALLS=0",
            "M4AW2_TERMINAL=failure",
        ]
        self.assertEqual(eligibility.parse_output("\n".join(lines) + "\n"), "failure")

    def test_static_no_provider_or_write_path(self):
        source = (OPS / "manual_mtproto_inbox_eligibility.py").read_text()
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
        self.assertIn("RecentSourceService", source)
        for forbidden in ("enqueue_summaries", "build_inbox_conversation_groups"):
            self.assertNotIn(forbidden, source)

    def test_alembic_uses_credential_host_contract_and_isolated_stdin(self):
        command = eligibility.alembic_command(["docker", "compose"])
        shell_command = command[-1]
        for fragment in (
            'PGPASSWORD="$POSTGRES_PASSWORD"',
            "-h 127.0.0.1",
            '-U "${POSTGRES_USER:-secretary}"',
            '-d "${POSTGRES_DB:-secretary}"',
            "-At",
            '-c "SELECT version_num FROM alembic_version"',
        ):
            self.assertIn(fragment, shell_command)
        self.assertEqual(command[1:4], ["compose", "exec", "-T"])
        remote = (OPS / "manual_mtproto_inbox_eligibility.py").read_text()
        self.assertIn('run(alembic_command(compose), stdin="")', remote)
        self.assertNotIn("stdout", shell_command)

    def test_wrapper_syntax_and_pinned_public_key_transport(self):
        wrapper = OPS / "manual_mtproto_inbox_eligibility_probe.sh"
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
            ["python3", str(OPS / "manual_mtproto_inbox_eligibility.py"), "bundle"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("remote_main()", bundle)


if __name__ == "__main__":
    unittest.main()
