"""Local-only protocol and static tests for M4BD1."""

import ast
import importlib.util
import subprocess
import unittest
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("acceptance", OPS / "manual_mtproto_postdeploy_acceptance.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def valid():
    lines = [f"{key}=true" for key, _ in probe.GUARDS]
    lines += [f"PRODUCTION_RELEASE={probe.RELEASE}", "ALEMBIC=0046"]
    lines += [f"{key}=0" for key in probe.FIELDS]
    lines += ["TELEGRAM_NETWORK_CALLS=0", "DB_WRITES=0", "M4BD1_TERMINAL=success"]
    return "\n".join(lines) + "\n"


class AcceptanceProbeTests(unittest.TestCase):
    def test_success_protocol_and_all_aggregate_fields(self):
        self.assertEqual(probe.parse_output(valid()), "success")

    def test_premature_eof_fails_closed(self):
        transcript = valid()
        for count in range(len(transcript.splitlines(keepends=True))):
            with self.subTest(count=count), self.assertRaises(probe.Incomplete):
                probe.parse_output("".join(transcript.splitlines(keepends=True)[:count]))

    def test_unsafe_or_unknown_output_fails_closed(self):
        transcript = valid()
        for unsafe in (transcript + "ACCOUNT_ID=secret\n", transcript.replace("ALEMBIC=0046", "ALEMBIC=0045"), "M4BD1_TERMINAL=success\n"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                probe.parse_output(unsafe)

    def test_guard_failure_is_terminal_and_zero_write_network(self):
        lines = []
        for key, _stage in probe.GUARDS:
            lines.append(f"{key}={'false' if key == 'DB_HEALTH_PASS' else 'true'}")
            if key == "DB_HEALTH_PASS":
                break
        lines += ["FAILURE_STAGE=STAGE_0_DB_HEALTH", "RAW_EXCEPTION_CLASS=RuntimeError", "TELEGRAM_NETWORK_CALLS=0", "DB_WRITES=0", "M4BD1_TERMINAL=failure"]
        self.assertEqual(probe.parse_output("\n".join(lines) + "\n"), "failure")

    def test_child_contains_only_read_only_aggregate_sql(self):
        source = probe.child_source()
        self.assertNotIn("TelegramClient", source)
        self.assertNotIn("fetch_history", source)
        self.assertNotIn("fetch_message", source)
        self.assertNotIn("reconcile_scope", source)
        tree = ast.parse(source)
        attrs = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertFalse(attrs & {"flush", "commit", "add", "add_all", "delete"})
        self.assertIn("autoflush=False", source)

    def test_child_reports_required_acceptance_dimensions(self):
        source = probe.child_source()
        for field in probe.FIELDS:
            self.assertIn(f'emit("{field}"', source)
        self.assertIn('emit("TELEGRAM_NETWORK_CALLS", 0)', source)
        self.assertIn('emit("DB_WRITES", 0)', source)

    def test_embedding_and_pending_job_queries_are_aggregate_only(self):
        source = probe.child_source()
        self.assertIn("obj.embedding is not None", source)
        self.assertIn("JOB_STATUS_PENDING", source)
        self.assertIn("JOB_STATUS_RUNNING", source)
        self.assertIn("JOB_TYPE_EMBED_OBJECT", source)
        self.assertIn("object_ids", source)

    def test_alembic_contract_and_stdin_isolation(self):
        command = probe.alembic_command(["docker", "compose"])
        self.assertIn('PGPASSWORD="$POSTGRES_PASSWORD"', command[-1])
        self.assertIn("-h 127.0.0.1", command[-1])
        self.assertIn('-U "${POSTGRES_USER:-secretary}"', command[-1])
        self.assertIn('-d "${POSTGRES_DB:-secretary}"', command[-1])
        self.assertEqual(command[1:4], ["compose", "exec", "-T"])

    def test_wrapper_syntax_and_pinned_public_key_transport(self):
        wrapper = OPS / "manual_mtproto_postdeploy_acceptance_probe.sh"
        subprocess.run(["bash", "-n", str(wrapper)], check=True)
        source = wrapper.read_text()
        for option in ("StrictHostKeyChecking=yes", "HostKeyAlgorithms=ssh-ed25519", "PasswordAuthentication=no", "KbdInteractiveAuthentication=no", "PreferredAuthentications=publickey"):
            self.assertIn(option, source)
        bundle = subprocess.run(["python3", str(OPS / "manual_mtproto_postdeploy_acceptance.py"), "bundle"], capture_output=True, text=True, check=True).stdout
        self.assertIn("remote_main()", bundle)


if __name__ == "__main__":
    unittest.main()
