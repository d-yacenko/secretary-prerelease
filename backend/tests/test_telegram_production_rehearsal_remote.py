"""Local checks for the streamed production rehearsal wrapper. No SSH."""

import base64
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

WRAPPER_PATH = (
    Path(__file__).resolve().parents[2]
    / "ops"
    / "production"
    / "telegram_production_rehearsal_remote.py"
)
HELPER_PATH = WRAPPER_PATH.with_name("telegram_production_rehearsal.py")
spec = importlib.util.spec_from_file_location("telegram_production_rehearsal_remote", WRAPPER_PATH)
wrapper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wrapper
spec.loader.exec_module(wrapper)

ROOT = str(wrapper.REPOSITORY_ROOT.resolve())


def _git(overrides: dict[tuple[str, ...], str] | None = None):
    answers = {
        ("rev-parse", "--show-toplevel"): ROOT,
        ("remote", "get-url", "origin"): wrapper.CANONICAL_ORIGIN,
        ("status", "--porcelain"): "",
        ("branch", "--show-current"): "main",
        ("fetch", "--prune", "origin", "main", "production"): "",
        ("rev-parse", "HEAD"): "abc",
        ("rev-parse", "origin/main"): "abc",
        ("rev-parse", "origin/production"): wrapper.PRODUCTION_RELEASE,
    }
    answers.update(overrides or {})

    def git(args: list[str]) -> str:
        return answers[tuple(args)]

    return git


def test_wrapper_refuses_wrong_origin_branch_and_dirty_tree() -> None:
    with pytest.raises(wrapper.RemoteBlocked, match="origin"):
        wrapper.require_local_checkout(
            _git({("remote", "get-url", "origin"): "https://example.invalid/other.git"})
        )
    with pytest.raises(wrapper.RemoteBlocked, match="branch"):
        wrapper.require_local_checkout(_git({("branch", "--show-current"): "topic"}))
    with pytest.raises(wrapper.RemoteBlocked, match="dirty_worktree"):
        wrapper.require_local_checkout(_git({("status", "--porcelain"): " M helper.py"}))
    wrapper.require_local_checkout(_git())


def test_wrapper_refuses_wrong_production_ref_head_and_worktree() -> None:
    with pytest.raises(wrapper.RemoteBlocked, match="production_ref"):
        wrapper.require_local_checkout(_git({("rev-parse", "origin/production"): "0" * 40}))
    assert (
        wrapper.assess_remote_state("wrong", "", "false", "false", wrapper.PRODUCTION_RELEASE)
        == "production_ref"
    )
    assert (
        wrapper.assess_remote_state(
            wrapper.PRODUCTION_RELEASE, " M x", "false", "false", wrapper.PRODUCTION_RELEASE
        )
        == "worktree"
    )
    assert (
        wrapper.assess_remote_state(
            wrapper.PRODUCTION_RELEASE, "", "true", "false", wrapper.PRODUCTION_RELEASE
        )
        == "long_running_ai"
    )
    assert (
        wrapper.assess_remote_state(
            wrapper.PRODUCTION_RELEASE, "", "false", "false", wrapper.PRODUCTION_RELEASE
        )
        is None
    )


def test_wrapper_pins_host_key_and_hides_stderr() -> None:
    with pytest.raises(wrapper.RemoteBlocked, match="host_key"):
        wrapper.select_host_keys(
            "host ssh-ed25519 AAA\n", "SHA256:missing", lambda _line: "SHA256:other"
        )
    pinned = wrapper.select_host_keys(
        "# comment\nhost ssh-ed25519 AAA\n",
        "SHA256:pinned",
        lambda _line: "SHA256:pinned",
    )
    command = wrapper.ssh_command("root@example", 22, Path("/tmp/known_hosts"))
    assert "BatchMode=yes" in command
    assert "StrictHostKeyChecking=yes" in command
    assert "UserKnownHostsFile=/tmp/known_hosts" in command
    assert "GlobalKnownHostsFile=/dev/null" in command
    assert pinned.strip() == "host ssh-ed25519 AAA"
    stdout = "INBOX_ELIGIBLE=PASS\n"
    stderr = "sk-secret traceback"
    assert wrapper.public_output(stdout, stderr) == stdout
    assert "sk-secret" not in wrapper.public_output(stdout, stderr)


def test_wrapper_streams_helper_into_isolated_oneshot() -> None:
    source = HELPER_PATH.read_text(encoding="utf-8")
    program = wrapper.build_remote_program("rehearsal1", source)
    command = wrapper.oneshot_compose_command("rehearsal1", "/tmp/telegram_production_rehearsal.py")
    joined = " ".join(command)
    assert " run " in f" {joined} "
    assert "--rm" in command
    assert "--no-deps" in command
    assert "--no-build" in command
    assert "up" not in command
    assert "restart" not in command
    assert "--force-recreate" not in command
    assert "docker.sock" not in joined
    assert "PYTHONPATH" not in command
    assert "TELEGRAM_MTPROTO_AI_ENABLED=true" in command
    assert f"{wrapper.HOST_HELPER_PATH}:{wrapper.ONESHOT_HELPER_DEST}:ro" in command
    assert wrapper.ONESHOT_HELPER_DEST == "/app/telegram_production_rehearsal.py"
    assert command[command.index("python3") :] == [
        "python3",
        wrapper.ONESHOT_HELPER_DEST,
        "--live",
        "--run-id",
        "rehearsal1",
    ]
    assert "/opt/rehearsal" not in joined
    assert program.index('git("rev-parse", "HEAD")') < program.index('service_flag("api")')
    assert program.index('service_flag("api")') < program.index("subprocess.run(ONESHOT")
    assert wrapper.PRODUCTION_RELEASE in program
    assert "docker.sock" not in program
    assert "--force-recreate" not in program
    encoded = program.split("HELPER_B64 = ", 1)[1].split("\n", 1)[0].strip().strip("'")
    assert "One-shot Telegram synthetic ML rehearsal" in base64.b64decode(encoded).decode("utf-8")
    assert "/opt/secretary/telegram_production_rehearsal.py" not in program
    assert "/opt/rehearsal" not in program
    assert "/app/telegram_production_rehearsal.py:ro" in program


_FAKE_SUBPROCESS = """
import subprocess
import sys
from pathlib import Path

RELEASE = sys.argv[2]
ORIGIN = sys.argv[3]
MODE = sys.argv[4]


class Proc:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def fake_run(cmd, **_kwargs):
    if MODE == "raise":
        raise RuntimeError("sk-secret NameError TRUE_FLAGS")
    if cmd and cmd[0] == "git":
        answers = {
            ("rev-parse", "HEAD"): RELEASE,
            ("status", "--porcelain"): "",
            ("remote", "get-url", "origin"): ORIGIN,
        }
        return Proc(0, answers[tuple(cmd[1:])] + "\\n")
    if "exec" in cmd:
        return Proc(0, "false\\n")
    if "run" in cmd:
        if MODE == "oneshot":
            return Proc(1, "Traceback sk-secret ModuleNotFoundError: app")
        return Proc(0, "INBOX_ELIGIBLE=PASS\\n")
    raise AssertionError(cmd)


subprocess.run = fake_run
program = Path(sys.argv[1]).read_text(encoding="utf-8")
try:
    exec(compile(program, "remote_program.py", "exec"), {"__name__": "__main__"})
except SystemExit as exc:
    raise SystemExit(0 if exc.code is None else exc.code)
"""


def _run_generated(program: str, *, mode: str) -> subprocess.CompletedProcess[str]:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        script = root / "remote.py"
        runner = root / "runner.py"
        script.write_text(program, encoding="utf-8")
        runner.write_text(_FAKE_SUBPROCESS, encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(runner),
                str(script),
                wrapper.PRODUCTION_RELEASE,
                wrapper.CANONICAL_ORIGIN,
                mode,
            ],
            text=True,
            capture_output=True,
            check=False,
        )


def test_generated_remote_program_reaches_oneshot_without_nameerror() -> None:
    written = Path("/tmp/telegram_production_rehearsal.py")
    program = wrapper.build_remote_program("tgprod0922a", "synthetic-helper\n")
    try:
        result = _run_generated(program, mode="ok")
        body = written.read_text(encoding="utf-8")
    finally:
        written.unlink(missing_ok=True)
    assert result.returncode == 0
    assert result.stdout == "INBOX_ELIGIBLE=PASS\n"
    assert body == "synthetic-helper\n"
    assert "NameError" not in result.stderr
    assert "Traceback" not in result.stderr


def test_generated_remote_program_sanitizes_unexpected_exception() -> None:
    program = wrapper.build_remote_program("tgprod0922a", "synthetic-helper\n")
    result = _run_generated(program, mode="raise")
    assert result.returncode == 1
    assert result.stdout == "REHEARSAL_REMOTE_BLOCKED=remote_program\n"
    assert "sk-secret" not in result.stdout
    assert "Traceback" not in result.stdout
    assert "NameError" not in result.stdout


def test_import_failure_becomes_fixed_oneshot_marker() -> None:
    written = Path("/tmp/telegram_production_rehearsal.py")
    program = wrapper.build_remote_program("tgprod0922a", "synthetic-helper\n")
    try:
        result = _run_generated(program, mode="oneshot")
    finally:
        written.unlink(missing_ok=True)
    assert result.returncode == 1
    assert result.stdout == "REHEARSAL_REMOTE_BLOCKED=oneshot_failed\n"
    assert "sk-secret" not in result.stdout
    assert "Traceback" not in result.stdout
    assert "ModuleNotFoundError" not in result.stdout


def test_helper_under_app_layout_imports_image_package(tmp_path: Path) -> None:
    image = tmp_path / "app"
    image.mkdir()
    package = image / "app"
    package.mkdir()
    (package / "__init__.py").write_text("PACKAGE = 'image'\n", encoding="utf-8")
    script = image / wrapper.ONESHOT_HELPER_NAME
    script.write_text(
        "import sys\nfrom pathlib import Path\nimport app\n"
        "print(Path(sys.argv[0]).resolve().parent)\n"
        "print(app.PACKAGE)\n"
        "print(Path(app.__file__).resolve().parent.parent)\n",
        encoding="utf-8",
    )
    mounted = tmp_path / "opt" / "rehearsal" / wrapper.ONESHOT_HELPER_NAME
    mounted.parent.mkdir(parents=True)
    mounted.write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    good = subprocess.run(
        [sys.executable, "-S", str(script)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    bad = subprocess.run(
        [sys.executable, "-S", str(mounted)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert good.returncode == 0
    lines = good.stdout.splitlines()
    assert lines[0] == str(image.resolve())
    assert lines[1] == "image"
    assert lines[2] == str(image.resolve())
    assert bad.returncode != 0
    assert "ModuleNotFoundError" in bad.stderr
