"""Local bridge integration tests: every network/runtime command is a stub."""

import ast
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "protocol", OPS / "manual_mtproto_structural_protocol.py"
)
protocol = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(protocol)


def child_output(failure=None):
    lines = []
    for key, stage in protocol.CHECKS:
        lines.append(f"{key}={'false' if stage == failure else 'true'}")
        if stage == failure:
            break
        if stage == "DB_QUERY":
            lines += ["ACCOUNT_EXACTLY_ONE=true", "MANUAL_SELECTED_EXACTLY_ONE=true"]
        if stage == "HISTORY_STATE_READ":
            lines += [
                "INITIAL_STATE=true",
                "HISTORY_COMPLETE_BEFORE=false",
                "BACKFILL_CURSOR_PRESENT_BEFORE=false",
            ]
    return (
        "\n".join(
            lines
            + [
                f"FAILURE_SUBSTAGE={failure or 'NONE'}",
                f"RAW_EXCEPTION_CLASS={'RuntimeError' if failure else 'NONE'}",
                "TELEGRAM_NETWORK_CALLS=0",
                "M4AN2_CHILD_TERMINAL=complete",
            ]
        )
        + "\n"
    )


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            TEST_ROOT=str(self.root),
            CHILD_OUTPUT=child_output(),
        )
        self.env["TEST_PIN"] = json.loads((OPS / "target.json").read_text())[
            "host_key_sha256"
        ]
        self.stub(
            "git",
            """import sys
if 'get-url' in sys.argv: print('https://github.com/d-yacenko/secretary-prerelease.git')
elif 'rev-parse' in sys.argv: print('23fa07df213d5a70a6dc1d3c8b32af39228107eb')
""",
        )
        self.stub("ssh-keyscan", "print('local mock key')")
        self.stub("ssh-keygen", "import os\nprint('256 ' + os.environ['TEST_PIN'])")
        self.stub(
            "ssh",
            """import os, sys, subprocess
script = sys.stdin.read()
if 'REMOTE_OUTPUT' in os.environ:
    print(os.environ['REMOTE_OUTPUT'], end='')
    sys.exit(int(os.environ.get('SSH_RC', '0')))
script = script.replace('REPO="/opt/secretary"', 'REPO="' + os.environ['TEST_ROOT'] + '"')
result = subprocess.run(['bash', '-s', '--', sys.argv[-1]], input=script, text=True)
sys.exit(result.returncode)
""",
        )
        self.stub(
            "docker",
            """import os, sys
args = sys.argv[1:]
if 'config' in args:
    sys.exit(1 if os.environ.get('OUTER_FAIL') else 0)
elif 'ps' in args: print('mock-container')
elif 'inspect' in args: print('healthy' if 'Health' in args[2] else 'true')
elif 'exec' in args and 'db' in args:
    # Docker's stdin forwarding must never eat the remainder of bash -s.
    if sys.stdin.read(): sys.exit(9)
    print(os.environ.get('REVISION', '0046'))
elif 'exec' in args and 'api' in args:
    sys.stdin.read()
    print(os.environ['CHILD_OUTPUT'], end='')
else: sys.exit(99)
""",
        )

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/env python3\n" + body + "\n")
        path.chmod(0o755)

    def run_bridge(self, **env):
        return subprocess.run(
            ["bash", str(OPS / "manual_mtproto_structural_probe.sh")],
            env=dict(self.env, **env),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_full_terminal_and_stdin_isolation(self):
        result = self.run_bridge()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for line in (
            "ALEMBIC_CHECK_STARTED=true",
            "ALEMBIC_0046_PASS=true",
            "CHILD_STARTED=true",
            "CHILD_TERMINAL_RESULT=valid",
            "MANUAL_M4AN2_REMOTE_TERMINAL=structural",
            "MANUAL_M4AN2_END=true",
        ):
            self.assertIn(line, result.stdout)

    def test_eof_after_every_remote_line(self):
        full = self.run_bridge()
        lines = full.stdout.splitlines(keepends=True)[3:-1]
        for count in range(len(lines)):
            with self.subTest(count=count):
                result = self.run_bridge(REMOTE_OUTPUT="".join(lines[:count]))
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("MANUAL_M4AN2_END=true", result.stdout)
                self.assertIn("MANUAL_M4AN2_BLOCKED=remote_incomplete", result.stdout)

    def test_truncated_terminal(self):
        full = self.run_bridge()
        output = full.stdout.split("TARGET_PIN_PASS=true\n")[1]
        output = output.replace("MANUAL_M4AN2_END=true\n", "").rstrip("\n")
        result = self.run_bridge(REMOTE_OUTPUT=output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MANUAL_M4AN2_BLOCKED=remote_incomplete", result.stdout)
        self.assertNotIn("MANUAL_M4AN2_END=true", result.stdout)

    def test_explicit_outer_failure(self):
        for env, cause in (
            ({"OUTER_FAIL": "1"}, "COMPOSE_CONFIG"),
            ({"REVISION": "0045"}, "ALEMBIC"),
        ):
            with self.subTest(cause=cause):
                result = self.run_bridge(**env)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn("M4AM_GENERIC_DB_STAGE_CAUSE=" + cause, result.stdout)
                self.assertIn("MANUAL_M4AN2_REMOTE_TERMINAL=blocked", result.stdout)
                self.assertIn("MANUAL_M4AN2_END=true", result.stdout)
                self.assertNotIn("CHILD_STARTED", result.stdout)

    def test_structural_child_failures(self):
        for _, stage in protocol.CHECKS:
            with self.subTest(stage=stage):
                result = self.run_bridge(CHILD_OUTPUT=child_output(stage))
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn("M4AM_GENERIC_DB_STAGE_CAUSE=" + stage, result.stdout)
                self.assertIn("MANUAL_M4AN2_END=true", result.stdout)

    def test_unsafe_unknown_incomplete_child_is_closed(self):
        for output in (
            "",
            "secret@example.com\n",
            child_output() + "UNKNOWN=secret\n",
            child_output().replace(
                "RAW_EXCEPTION_CLASS=NONE", "RAW_EXCEPTION_CLASS=SecretIdentifier"
            ),
            child_output().replace("M4AN2_CHILD_TERMINAL=complete\n", ""),
            child_output() + "unsafe_unterminated",
        ):
            with self.subTest(output=output):
                result = self.run_bridge(CHILD_OUTPUT=output)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn("CHILD_TERMINAL_RESULT=invalid", result.stdout)
                self.assertIn(
                    "M4AM_GENERIC_DB_STAGE_CAUSE=CHILD_PROTOCOL", result.stdout
                )
                self.assertNotIn("STRUCTURAL_READY", result.stdout)
                for unsafe in ("secret", "SecretIdentifier", "unsafe_unterminated"):
                    self.assertNotIn(unsafe, result.stdout + result.stderr)

    def test_forged_or_unsafe_remote_is_closed(self):
        for output in (
            "MANUAL_M4AN2_REMOTE_TERMINAL=structural\n",
            "secret@example.com\n",
            self.run_bridge()
            .stdout.split("TARGET_PIN_PASS=true\n")[1]
            .replace("MANUAL_M4AN2_END=true\n", "UNKNOWN=secret\n"),
        ):
            result = self.run_bridge(REMOTE_OUTPUT=output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("MANUAL_M4AN2_BLOCKED=remote_protocol", result.stdout)
            self.assertNotIn("MANUAL_M4AN2_END=true", result.stdout)
            self.assertNotIn("secret", result.stdout + result.stderr)

    def test_transport_failure_after_terminal(self):
        output = self.run_bridge().stdout.split("TARGET_PIN_PASS=true\n")[1]
        result = self.run_bridge(
            REMOTE_OUTPUT=output.replace("MANUAL_M4AN2_END=true\n", ""), SSH_RC="255"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MANUAL_M4AN2_BLOCKED=ssh_failed", result.stdout)
        self.assertNotIn("MANUAL_M4AN2_END=true", result.stdout)

    def test_child_has_no_provider_or_write_calls(self):
        script = (OPS / "manual_mtproto_structural_probe.sh").read_text()
        source = script.split("<<'PY'\n")[-1].split("\nPY\n")[0]
        tree = ast.parse(source)
        calls = {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        self.assertEqual(
            calls,
            {
                "print",
                "type",
                "emit",
                "SystemExit",
                "fail",
                "SessionLocal",
                "list",
                "select",
                "scalars",
                "where",
                "is_",
                "str",
                "len",
                "lower",
                "RuntimeError",
                "bool",
                "CredentialEncryption",
                "decrypt",
                "ValueError",
                "StringSession",
                "_input_peer_from_reference",
                "validate_provider_peer_reference",
                "safe_class",
            },
        )
        self.assertIn("StrictHostKeyChecking=yes", script)
        for option in (
            "PasswordAuthentication=no",
            "KbdInteractiveAuthentication=no",
            "PreferredAuthentications=publickey",
        ):
            self.assertIn(option, script)


if __name__ == "__main__":
    unittest.main()
