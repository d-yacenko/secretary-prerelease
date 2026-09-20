"""No production imports, sockets, SSH or provider clients: fakes only."""

import ast
import asyncio
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

OPS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "probe", OPS / "manual_mtproto_history_two_page.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
# Exercise the exact production cutoff helper, without importing application services.
release_source = subprocess.run(
    [
        "git",
        "show",
        probe.RELEASE + ":backend/app/services/telegram_mtproto_history_service.py",
    ],
    cwd=OPS,
    capture_output=True,
    text=True,
    check=True,
).stdout
node = next(
    n
    for n in ast.parse(release_source).body
    if isinstance(n, ast.FunctionDef) and n.name == "_next_backfill_state"
)
namespace = {}
exec(  # noqa: S102 - exact committed pure production helper
    "from __future__ import annotations\n"
    + ast.get_source_segment(release_source, node),
    namespace,
)
NEXT = namespace["_next_backfill_state"]


class FakeDB:
    def __init__(self, deps):
        self.deps = deps
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def scalars(self, _query):
        self.reads += 1
        return [self.deps.account] if self.reads == 1 else [self.deps.selection]


class FakeDeps:
    def __init__(self, size=100, failure=None, cutoff=None, none=False):
        self.size, self.failure, self.none = size, failure, none
        self.clients = []
        self.iterations = []
        self.pulled = 0
        self.events = []
        self.settings = SimpleNamespace(
            telegram_api_id=1,
            telegram_api_hash="secret-api",
            secretary_credential_key="secret-key",
        )
        self.account = SimpleNamespace(session_encrypted="secret-session")
        self.selection = SimpleNamespace(
            history_latest_message_id=None,
            history_complete=False,
            history_backfill_before_message_id=None,
            history_cutoff_at=cutoff,
            provider_peer_reference_encrypted="secret-reference",
            peer_id=555,
        )
        self.TelegramMtprotoAccount = object()
        self.TelegramMtprotoChatSelection = SimpleNamespace(
            manual_selected=SimpleNamespace(is_=lambda _: True)
        )
        self.TELEGRAM_MTPROTO_HISTORY_DAYS = 30
        self.TelegramMtprotoHistoryPage = SimpleNamespace
        self._next_backfill_state = NEXT

    def SessionLocal(self, *, autoflush):
        assert autoflush is False
        return FakeDB(self)

    def select(self, _model):
        return SimpleNamespace(where=lambda _: None)

    def CredentialEncryption(self, _key):
        return SimpleNamespace(decrypt=lambda value: value)

    def StringSession(self, value):
        return value

    def _input_peer_from_reference(self, _reference):
        return object()

    def validate_provider_peer_reference(self, _reference, *, expected_peer_id):
        assert expected_peer_id == 555
        return object()

    def _history_entry_from_message(self, message):
        if self.failure == (len(self.clients), "conversion"):
            if self.none:
                return None
            raise TypeError("secret-message-text")
        return message

    def TelegramClient(self, *args, **kwargs):
        assert kwargs == {
            "request_retries": 0,
            "connection_retries": 0,
            "auto_reconnect": False,
            "flood_sleep_threshold": 0,
            "receive_updates": False,
        }
        number = len(self.clients) + 1
        if self.failure == (number, "construct"):
            raise ValueError("secret-constructor")
        deps = self

        class Client:
            async def connect(self):
                deps.events.append((number, "connect"))
                if deps.failure == (number, "connect"):
                    raise ConnectionError("secret-host")

            async def is_user_authorized(self):
                deps.events.append((number, "auth"))
                if deps.failure == (number, "auth"):
                    raise RuntimeError("secret-auth")
                return deps.failure != (number, "auth_false")

            def iter_messages(self, peer, **options):
                deps.iterations.append(options)
                if deps.failure == (number, "iterator_create"):
                    raise ValueError("secret-iterator")

                async def iterator():
                    for i in range(deps.size if number == 1 else 100):
                        if deps.failure == (number, "iteration") and i == 3:
                            raise RuntimeError("secret-provider")
                        deps.pulled += 1
                        yield SimpleNamespace(
                            message_id=1000 - (number - 1) * 100 - i,
                            occurred_at=datetime.now(UTC),
                        )

                return iterator()

            async def disconnect(self):
                deps.events.append((number, "disconnect"))

        client = Client()
        self.clients.append(client)
        return client


def child_result(deps):
    output = io.StringIO()
    report = probe.Report(output)
    report.emit("IMPORTS_PASS", True)
    try:
        asyncio.run(probe.child_probe(report, deps))
    except probe.ProbeFailure as exc:
        report.finish(exc)
    else:
        report.finish()
    text = output.getvalue()
    probe.parse_output(text, child=True)
    return text


def remote_text(child):
    return (
        "".join(f"{key}=true\n" for key, _ in probe.GUARDS)
        + "CHILD_STARTED=true\n"
        + child
    )


class ProbeTests(unittest.TestCase):
    def test_constructor_failure_has_no_connect_attempt(self):
        for number in (1, 2):
            text = child_result(FakeDeps(failure=(number, "construct")))
            self.assertIn(f"CONNECT_CALL_COUNT={number - 1}", text)
            self.assertIn(
                "FAILURE_STAGE="
                + probe.page_stages(number)[0].replace("_CONNECT", "_CLIENT"),
                text,
            )

    def test_child_entrypoint_suppresses_library_output(self):
        output = io.StringIO()

        def deps():
            print("secret-library-noise")
            return FakeDeps(size=2)

        with (
            patch("sys.stdout", output),
            patch.object(probe, "dependencies", side_effect=deps),
        ):
            probe.child_main()
        self.assertNotIn("secret", output.getvalue())
        self.assertEqual(probe.parse_output(output.getvalue(), child=True), "success")

    def test_real_dependency_loader_with_fake_modules(self):
        deps = FakeDeps(size=2)
        names = {
            "sqlalchemy": ("select",),
            "telethon": ("TelegramClient",),
            "telethon.sessions": ("StringSession",),
            "app.connectors.google.encryption": ("CredentialEncryption",),
            "app.connectors.telegram.mtproto_transport": (
                "TelegramMtprotoHistoryPage",
                "_history_entry_from_message",
                "_input_peer_from_reference",
                "validate_provider_peer_reference",
            ),
            "app.core.config": ("settings",),
            "app.db.models": ("TelegramMtprotoAccount", "TelegramMtprotoChatSelection"),
            "app.db.session": ("SessionLocal",),
            "app.services.telegram_mtproto_history_service": (
                "TELEGRAM_MTPROTO_HISTORY_DAYS",
                "_next_backfill_state",
            ),
        }
        modules = {}
        for name, attributes in names.items():
            module = ModuleType(name)
            for attribute in attributes:
                setattr(module, attribute, getattr(deps, attribute))
            modules[name] = module
        output = io.StringIO()
        with patch.dict("sys.modules", modules), patch("sys.stdout", output):
            probe.child_main()
        self.assertEqual(probe.parse_output(output.getvalue(), child=True), "success")
        self.assertEqual(len(deps.clients), 1)

    def test_import_failure_terminal(self):
        output = io.StringIO()
        with (
            patch.object(probe, "dependencies", side_effect=ImportError("secret")),
            patch("sys.stdout", output),
        ):
            probe.child_main()
        self.assertEqual(probe.parse_output(output.getvalue(), child=True), "failure")
        self.assertIn("FAILURE_STAGE=STAGE_1_IMPORTS", output.getvalue())
        self.assertNotIn("secret", output.getvalue())

    def test_remote_rejects_unsafe_child_without_false_counts(self):
        for stdout, stderr, rc in [
            ("secret-raw-output\n", "", 0),
            (child_result(FakeDeps(size=2)), "secret-stderr", 0),
            (child_result(FakeDeps(size=2)), "", 1),
        ]:
            responses = [
                "https://github.com/d-yacenko/secretary-prerelease.git",
                probe.RELEASE,
                probe.RELEASE,
                "",
                "{}",
                "cid",
                "true",
                "cid",
                "true",
                "cid",
                "true",
                "cid",
                "healthy",
                "0046",
            ]

            def run(
                argv, responses=responses, rc=rc, stdout=stdout, stderr=stderr, **kwargs
            ):
                if responses:
                    return SimpleNamespace(
                        returncode=0, stdout=responses.pop(0), stderr=""
                    )
                return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)

            output = io.StringIO()
            with (
                patch.object(probe.os, "chdir"),
                patch.object(probe.subprocess, "run", side_effect=run),
                patch("sys.stdout", output),
            ):
                probe.remote_main("unused mock source")
            self.assertEqual(probe.parse_output(output.getvalue()), "blocked")
            self.assertNotIn("secret", output.getvalue())
            self.assertNotIn("TELEGRAM_NETWORK_CALLS=0", output.getvalue())

    def test_one_page(self):
        deps = FakeDeps(size=7)
        text = child_result(deps)
        self.assertIn("PAGE2_REQUIRED=false", text)
        self.assertIn("TELEGRAM_NETWORK_CALLS=3", text)
        self.assertEqual(len(deps.clients), 1)
        self.assertEqual(probe.parse_output(remote_text(text)), "success")

    def test_two_pages_fresh_client_exact_cursor(self):
        deps = FakeDeps()
        text = child_result(deps)
        self.assertEqual(probe.parse_output(remote_text(text)), "success")
        self.assertEqual(len(deps.clients), 2)
        self.assertIsNot(deps.clients[0], deps.clients[1])
        self.assertEqual(
            deps.iterations,
            [
                {"limit": 100, "min_id": None, "max_id": None, "reverse": False},
                {"limit": 100, "min_id": None, "max_id": 901, "reverse": False},
            ],
        )
        self.assertEqual(
            deps.events,
            [
                (1, "connect"),
                (1, "auth"),
                (1, "disconnect"),
                (2, "connect"),
                (2, "auth"),
                (2, "disconnect"),
            ],
        )
        self.assertIn("MESSAGES_SEEN_TOTAL=200", text)
        self.assertIn("TELEGRAM_NETWORK_CALLS=6", text)

    def test_cutoff_stops_full_page(self):
        text = child_result(FakeDeps(cutoff=datetime.now(UTC) + timedelta(days=1)))
        self.assertIn("PAGE2_REQUIRED=false", text)
        self.assertNotIn("PAGE2_PASS", text)

    def test_empty_page(self):
        text = child_result(FakeDeps(size=0))
        self.assertIn("MESSAGES_SEEN_TOTAL=0", text)
        self.assertIn("PAGE2_REQUIRED=false", text)

    def test_cutoff_exact_boundary(self):
        cutoff = datetime.now(UTC)
        page = SimpleNamespace(
            entries=(SimpleNamespace(message_id=9, occurred_at=cutoff),), has_more=True
        )
        self.assertEqual(NEXT(page, cutoff), (None, True))

    def test_hard_bounds_even_for_overproducing_iterator(self):
        deps = FakeDeps(size=500)
        text = child_result(deps)
        self.assertEqual(deps.pulled, 200)
        self.assertIn("TELEGRAM_NETWORK_CALLS=6", text)

    def test_page_staged_failures(self):
        for number in (1, 2):
            for operation, index in [
                ("connect", 0),
                ("auth", 1),
                ("auth_false", 1),
                ("iterator_create", 2),
                ("iteration", 2),
                ("conversion", 3),
            ]:
                with self.subTest(page=number, operation=operation):
                    deps = FakeDeps(failure=(number, operation))
                    text = child_result(deps)
                    self.assertIn(
                        "FAILURE_STAGE=" + probe.page_stages(number)[index], text
                    )
                    self.assertEqual(probe.parse_output(remote_text(text)), "failure")
                    self.assertNotIn("secret", text)
                    self.assertEqual(len(deps.clients), number)
                    self.assertEqual(deps.events[-1], (number, "disconnect"))

    def test_none_conversion(self):
        for number in (1, 2):
            text = child_result(FakeDeps(failure=(number, "conversion"), none=True))
            self.assertIn("RAW_EXCEPTION_CLASS=InvalidHistoryEntry", text)
            self.assertIn(f"PAGE{number}_ENTRIES_NONE=1", text)

    def test_state_drift_stops_before_clients(self):
        for field, value in [
            ("history_latest_message_id", 123),
            ("history_complete", True),
            ("history_backfill_before_message_id", 123),
        ]:
            deps = FakeDeps()
            setattr(deps.selection, field, value)
            text = child_result(deps)
            self.assertIn("FAILURE_STAGE=STAGE_1_STATE", text)
            self.assertIn("TELEGRAM_NETWORK_CALLS=0", text)
            self.assertEqual(deps.clients, [])

    def test_structural_failures(self):
        for method in (
            "SessionLocal",
            "CredentialEncryption",
            "StringSession",
            "_input_peer_from_reference",
            "validate_provider_peer_reference",
        ):
            deps = FakeDeps()
            with patch.object(
                deps, method, side_effect=ValueError("secret-structural")
            ):
                text = child_result(deps)
            self.assertIn("M4AO1_TERMINAL=failure", text)
            self.assertIn("TELEGRAM_NETWORK_CALLS=0", text)
            self.assertNotIn("secret", text)

    def test_eof_every_line_and_partial_terminal(self):
        text = remote_text(child_result(FakeDeps()))
        lines = text.splitlines(keepends=True)
        for count in range(len(lines)):
            with self.subTest(count=count), self.assertRaises(probe.Incomplete):
                probe.parse_output("".join(lines[:count]))
        with self.assertRaises(probe.Incomplete):
            probe.parse_output(text[:-1])

    def test_unsafe_unknown_duplicate_reordered(self):
        text = remote_text(child_result(FakeDeps()))
        for invalid in (
            text + "secret\n",
            text + "M4AO1_TERMINAL=success\n",
            text.replace("PAGE1_PASS=true", "PAGE1_PASS=secret"),
            text.replace("PAGE2_REQUIRED=true\n", ""),
            "M4AO1_TERMINAL=success\n",
            text.replace("PAGE1_PASS=true\n", ""),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                probe.parse_output(invalid)

    def test_counter_forgery(self):
        text = remote_text(child_result(FakeDeps()))
        for key, value in [
            ("PAGE1_MESSAGES_SEEN", 101),
            ("PAGE1_ENTRIES_CONVERTED", 99),
            ("PAGE2_MESSAGES_SEEN", 101),
            ("MESSAGES_SEEN_TOTAL", 201),
            ("ENTRIES_CONVERTED_TOTAL", 199),
            ("CONNECT_CALL_COUNT", 3),
            ("IS_USER_AUTHORIZED_CALL_COUNT", 1),
            ("ITER_MESSAGES_CALL_COUNT", 3),
            ("TELEGRAM_NETWORK_CALLS", 7),
            ("TELEGRAM_NETWORK_CALLS", 5),
        ]:
            lines = [
                f"{key}={value}" if line.startswith(key + "=") else line
                for line in text.splitlines()
            ]
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                probe.parse_output("\n".join(lines) + "\n")

    def test_remote_guards_stop_and_have_zero_calls(self):
        for failed in range(len(probe.GUARDS)):
            output = io.StringIO()
            report = probe.Report(output)
            for index, (key, stage) in enumerate(probe.GUARDS[: failed + 1]):
                report.emit(key, index != failed)
            report.finish(probe.ProbeFailure(stage, RuntimeError()))
            self.assertEqual(probe.parse_output(output.getvalue()), "failure")

    def test_no_write_or_other_provider_path(self):
        tree = ast.parse((OPS / "manual_mtproto_history_two_page.py").read_text())
        calls = {
            n.func.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        forbidden = {
            "commit",
            "flush",
            "add",
            "add_all",
            "delete",
            "execute",
            "merge",
            "upsert",
            "fetch_history",
            "start",
            "sign_in",
            "send_code_request",
            "get_dialogs",
            "iter_dialogs",
            "send_message",
            "edit_message",
            "delete_messages",
            "send_read_acknowledge",
            "get_entity",
        }
        self.assertFalse(calls & forbidden)
        db_calls = {
            n.func.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "db"
        }
        self.assertEqual(db_calls, {"scalars"})
        assignments = [
            target
            for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            for target in n.targets
        ]
        self.assertFalse(
            any(
                isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Name)
                and n.value.id in {"account", "selection", "db"}
                for n in assignments
            )
        )
        page = next(
            n
            for n in tree.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "probe_page"
        )
        client_calls = {
            n.func.attr
            for n in ast.walk(page)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "client"
        }
        self.assertEqual(
            client_calls,
            {"connect", "is_user_authorized", "iter_messages", "disconnect"},
        )
        self.assertIn(
            "from app.services.telegram_mtproto_history_service import",
            ast.unparse(tree),
        )

    def test_bundle_executes_remote_entrypoint_without_writes(self):
        bundled = subprocess.run(
            ["python3", str(OPS / "manual_mtproto_history_two_page.py"), "bundle"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        scope = {"__name__": "bundle_test"}
        # Remove only final call so the fully compiled remote can use fake OS/runtime commands.
        source, call = bundled.rsplit("\nremote_main(", 1)
        exec(source, scope)  # noqa: S102 - locally generated reviewed source
        child = child_result(FakeDeps(size=3))
        results = [
            "https://github.com/d-yacenko/secretary-prerelease.git",
            probe.RELEASE,
            probe.RELEASE,
            "",
            "{}",
            "cid",
            "true",
            "cid",
            "true",
            "cid",
            "true",
            "cid",
            "healthy",
            "0046",
            child,
        ]
        invocations = []

        def run(argv, **kwargs):
            invocations.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout=results.pop(0), stderr="")

        output = io.StringIO()
        with (
            patch.object(probe.os, "chdir"),
            patch.object(probe.subprocess, "run", side_effect=run),
            patch("sys.stdout", output),
        ):
            exec("remote_main(" + call, scope)  # noqa: S102 - OS and runtime fully mocked
        self.assertEqual(probe.parse_output(output.getvalue()), "success")
        self.assertFalse(results)
        for _, kwargs in invocations[:-1]:
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIn("child_main()", invocations[-1][1]["input"])
        self.assertFalse(
            any(
                isinstance(n, ast.If)
                for n in ast.parse(invocations[-1][1]["input"]).body
            )
        )

    def test_wrapper_only_mock_ssh(self):
        valid = remote_text(child_result(FakeDeps(size=2)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def stub(name, code):
                path = root / name
                path.write_text("#!/usr/bin/env python3\n" + code)
                path.chmod(0o755)

            stub(
                "git",
                "print('https://github.com/d-yacenko/secretary-prerelease.git')\n",
            )
            stub("ssh-keyscan", "print('mock ed25519 key')\n")
            stub(
                "ssh-keygen",
                "print('256 SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs')\n",
            )
            stub(
                "ssh",
                "import os,sys\nassert all(option in sys.argv for option in ['StrictHostKeyChecking=yes','HostKeyAlgorithms=ssh-ed25519','PasswordAuthentication=no','KbdInteractiveAuthentication=no','PreferredAuthentications=publickey'])\nsys.stdin.read()\nprint(os.environ['MOCK_OUTPUT'],end='')\n",
            )
            for output, ok in [
                (valid, True),
                (valid[:-1], False),
                ("secret-output\n", False),
                (valid.split("PAGE1_PASS")[0], False),
            ]:
                env = dict(
                    os.environ,
                    PATH=str(root) + ":" + os.environ["PATH"],
                    MOCK_OUTPUT=output,
                )
                result = subprocess.run(
                    ["bash", str(OPS / "manual_mtproto_history_two_page_probe.sh")],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(
                    result.returncode == 0, ok, result.stdout + result.stderr
                )
                self.assertEqual("MANUAL_M4AO1_END=true" in result.stdout, ok)
                self.assertNotIn("secret-output", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
