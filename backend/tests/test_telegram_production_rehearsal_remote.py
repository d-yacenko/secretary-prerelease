"""Local checks for the streamed production rehearsal wrapper. No SSH."""

import base64
import importlib.util
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
    assert "TELEGRAM_MTPROTO_AI_ENABLED=true" in command
    assert program.index('git("rev-parse", "HEAD")') < program.index('service_flag("api")')
    assert program.index('service_flag("api")') < program.index("subprocess.run(ONESHOT")
    assert wrapper.PRODUCTION_RELEASE in program
    assert "docker.sock" not in program
    assert "--force-recreate" not in program
    encoded = program.split("HELPER_B64 = ", 1)[1].split("\n", 1)[0].strip().strip("'")
    assert "One-shot Telegram synthetic ML rehearsal" in base64.b64decode(encoded).decode("utf-8")
    assert "/opt/secretary/telegram_production_rehearsal.py" not in program
