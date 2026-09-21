"""Closed, zero-provider protocol for the M4AT1 human-shell visibility probe."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RELEASE = "b7fbdc71584cfde042a998fbfefb06015175a205"
TERMINAL = "M4AT1_TERMINAL"
FAILURE_STAGES = {
    "STAGE_0_REPO",
    "STAGE_0_RELEASE_REF",
    "STAGE_0_PRODUCTION_REF",
    "STAGE_0_WORKTREE",
    "STAGE_0_COMPOSE",
    "STAGE_0_DB_RUNNING",
    "STAGE_0_API_RUNNING",
    "STAGE_0_WORKER_RUNNING",
    "STAGE_0_DB_HEALTH",
    "STAGE_0_ALEMBIC",
    "STAGE_1_IMPORTS",
    "STAGE_1_DB_SESSION",
    "STAGE_1_ACCOUNT_CARDINALITY",
    "STAGE_1_SELECTION_CARDINALITY",
    "STAGE_1_VISIBILITY_QUERY",
    "STAGE_1_OUTPUT",
    "STAGE_1_PROTOCOL",
}
EXCEPTION_CLASSES = {
    "RuntimeError",
    "ValueError",
    "TypeError",
    "ImportError",
    "ModuleNotFoundError",
    "OperationalError",
    "ProgrammingError",
    "AttributeError",
    "OSError",
    "OTHER",
}
GUARDS = (
    ("REMOTE_REPO_PASS", "STAGE_0_REPO"),
    ("REMOTE_HEAD_PASS", "STAGE_0_RELEASE_REF"),
    ("REMOTE_PRODUCTION_REF_PASS", "STAGE_0_PRODUCTION_REF"),
    ("REMOTE_WORKTREE_CLEAN", "STAGE_0_WORKTREE"),
    ("COMPOSE_CONFIG_PASS", "STAGE_0_COMPOSE"),
    ("DB_RUNNING_PASS", "STAGE_0_DB_RUNNING"),
    ("API_RUNNING_PASS", "STAGE_0_API_RUNNING"),
    ("WORKER_RUNNING_PASS", "STAGE_0_WORKER_RUNNING"),
    ("DB_HEALTH_PASS", "STAGE_0_DB_HEALTH"),
    ("ALEMBIC_0046_PASS", "STAGE_0_ALEMBIC"),
)
BOOLEANS = (
    "ACCOUNT_EXACTLY_ONE",
    "MANUAL_SELECTED_EXACTLY_ONE",
    "MANUAL_SELECTED",
    "SCOPE_ACTIVE",
    "HISTORY_COMPLETE",
    "BACKFILL_CURSOR_PRESENT",
)


class Incomplete(ValueError):
    pass


class Reader:
    def __init__(self, text: str):
        self.lines = text.splitlines(keepends=True)
        self.pos = 0

    def take(self, key: str, values):
        if self.pos == len(self.lines):
            raise Incomplete()
        line = self.lines[self.pos]
        if not line.endswith("\n"):
            raise Incomplete()
        options = {f"{key}={value}\n": value for value in values}
        if line not in options:
            raise ValueError()
        self.pos += 1
        return options[line]

    def boolean(self, key: str) -> bool:
        return self.take(key, ("true", "false")) == "true"

    def count(self, key: str) -> int:
        return int(self.take(key, range(1_000_001)))


def parse_output(text: str) -> str:
    reader = Reader(text)
    for key, stage in GUARDS:
        if not reader.boolean(key):
            reader.take("FAILURE_STAGE", (stage,))
            reader.take("RAW_EXCEPTION_CLASS", EXCEPTION_CLASSES)
            reader.take("TELEGRAM_NETWORK_CALLS", ("0",))
            result = reader.take(TERMINAL, ("failure", "blocked"))
            if reader.pos != len(reader.lines):
                raise ValueError()
            return result
    if reader.pos < len(reader.lines) and reader.lines[reader.pos].startswith(
        "FAILURE_STAGE="
    ):
        stage = reader.take("FAILURE_STAGE", FAILURE_STAGES)
        reader.take("RAW_EXCEPTION_CLASS", EXCEPTION_CLASSES)
        reader.take("TELEGRAM_NETWORK_CALLS", ("0",))
        result = reader.take(TERMINAL, ("failure", "blocked"))
        if reader.pos != len(reader.lines):
            raise ValueError()
        return result
    for key in BOOLEANS:
        if reader.pos < len(reader.lines) and reader.lines[reader.pos].startswith(
            "FAILURE_STAGE="
        ):
            reader.take("FAILURE_STAGE", FAILURE_STAGES)
            reader.take("RAW_EXCEPTION_CLASS", EXCEPTION_CLASSES)
            reader.take("TELEGRAM_NETWORK_CALLS", ("0",))
            result = reader.take(TERMINAL, ("failure", "blocked"))
            if reader.pos != len(reader.lines):
                raise ValueError()
            return result
        reader.boolean(key)
    imported = reader.count("IMPORTED_OBJECT_COUNT")
    active = reader.count("ACTIVE_VISIBLE_OBJECT_COUNT")
    if active > imported:
        raise ValueError()
    reader.take("TELEGRAM_NETWORK_CALLS", ("0",))
    result = reader.take(TERMINAL, ("success",))
    if reader.pos != len(reader.lines):
        raise ValueError()
    return result


class Report:
    def __init__(self, stream):
        self.stream = stream

    def emit(self, key: str, value):
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{key}={value}", file=self.stream, flush=True)

    def failure(self, stage: str, exc: BaseException):
        name = type(exc).__name__
        self.emit("FAILURE_STAGE", stage)
        self.emit("RAW_EXCEPTION_CLASS", name if name in EXCEPTION_CLASSES else "OTHER")
        self.emit("TELEGRAM_NETWORK_CALLS", 0)
        self.emit(TERMINAL, "failure")


def alembic_command(compose: list[str]) -> list[str]:
    return compose + [
        "exec",
        "-T",
        "db",
        "sh",
        "-lc",
        (
            'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 '
            '-U "${POSTGRES_USER:-secretary}" -d "${POSTGRES_DB:-secretary}" '
            '-At -c "SELECT version_num FROM alembic_version"'
        ),
    ]


def child_source() -> str:
    return r"""from sqlalchemy import func, select
from app.db.models import Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection
from app.db.session import SessionLocal
from app.domain.telegram_mtproto_visibility import telegram_mtproto_active_object_predicate

def emit(key, value):
    print(f"{key}={str(value).lower() if isinstance(value, bool) else value}", flush=True)

try:
    with SessionLocal(autoflush=False) as db:
        accounts = list(db.scalars(select(TelegramMtprotoAccount)))
        selections = list(db.scalars(select(TelegramMtprotoChatSelection).where(
            TelegramMtprotoChatSelection.manual_selected.is_(True))))
        account_ok = len(accounts) == 1
        selection_ok = len(selections) == 1
        emit("ACCOUNT_EXACTLY_ONE", account_ok)
        emit("MANUAL_SELECTED_EXACTLY_ONE", selection_ok)
        if not account_ok:
            raise RuntimeError("account cardinality")
        if not selection_ok:
            raise RuntimeError("selection cardinality")
        account = accounts[0]
        selection = selections[0]
        emit("MANUAL_SELECTED", bool(selection.manual_selected))
        emit("SCOPE_ACTIVE", bool(selection.scope_active))
        emit("HISTORY_COMPLETE", bool(selection.history_complete))
        emit("BACKFILL_CURSOR_PRESENT", selection.history_backfill_before_message_id is not None)
        exact = (
            Object.user_id == account.user_id,
            Object.provider == "telegram",
            Object.kind == "chat_message",
            Object.metadata_["transport"].as_string() == "mtproto",
            Object.metadata_["account_id"].as_string() == str(account.id),
            Object.metadata_["peer_id"].as_string() == str(selection.peer_id),
        )
        imported = int(db.scalar(select(func.count()).select_from(Object).where(*exact)) or 0)
        active = int(db.scalar(select(func.count()).select_from(Object).where(
            *exact, telegram_mtproto_active_object_predicate())) or 0)
        emit("IMPORTED_OBJECT_COUNT", imported)
        emit("ACTIVE_VISIBLE_OBJECT_COUNT", active)
        emit("TELEGRAM_NETWORK_CALLS", 0)
        emit("M4AT1_TERMINAL", "success")
except Exception as exc:
    emit("FAILURE_STAGE", "STAGE_1_DB_SESSION")
    allowed = {"RuntimeError", "ValueError", "TypeError", "ImportError", "ModuleNotFoundError",
               "OperationalError", "ProgrammingError", "AttributeError", "OSError"}
    emit("RAW_EXCEPTION_CLASS", type(exc).__name__ if type(exc).__name__ in allowed else "OTHER")
    emit("TELEGRAM_NETWORK_CALLS", 0)
    emit("M4AT1_TERMINAL", "failure")
"""


def remote_main() -> None:
    report = Report(sys.stdout)
    compose = [
        "docker",
        "compose",
        "--env-file",
        "/opt/secretary/.env",
        "-f",
        "infra/compose.yaml",
        "-f",
        "infra/compose.deploy.yaml",
    ]

    def run(command, *, stdin=None):
        return subprocess.run(
            command,
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
            stdin=subprocess.DEVNULL if stdin is None else None,
        )

    def exact(command, expected):
        result = run(command)
        return result.returncode == 0 and result.stdout.strip() == expected

    checks = (
        (
            "REMOTE_REPO_PASS",
            lambda: exact(
                ["git", "remote", "get-url", "origin"],
                "https://github.com/d-yacenko/secretary-prerelease.git",
            ),
            "STAGE_0_REPO",
        ),
        (
            "REMOTE_HEAD_PASS",
            lambda: exact(["git", "rev-parse", "HEAD"], RELEASE),
            "STAGE_0_RELEASE_REF",
        ),
        (
            "REMOTE_PRODUCTION_REF_PASS",
            lambda: exact(["git", "rev-parse", "origin/production"], RELEASE),
            "STAGE_0_PRODUCTION_REF",
        ),
        (
            "REMOTE_WORKTREE_CLEAN",
            lambda: exact(["git", "status", "--porcelain"], ""),
            "STAGE_0_WORKTREE",
        ),
        (
            "COMPOSE_CONFIG_PASS",
            lambda: run(compose + ["config", "--format", "json"]).returncode == 0,
            "STAGE_0_COMPOSE",
        ),
    )
    try:
        os.chdir("/opt/secretary")
        for key, check, stage in checks:
            value = bool(check())
            report.emit(key, value)
            if not value:
                report.failure(stage, RuntimeError())
                return
        for service, key, stage in (
            ("db", "DB_RUNNING_PASS", "STAGE_0_DB_RUNNING"),
            ("api", "API_RUNNING_PASS", "STAGE_0_API_RUNNING"),
            ("worker", "WORKER_RUNNING_PASS", "STAGE_0_WORKER_RUNNING"),
        ):
            listed = run(compose + ["ps", "-q", service])
            cid = listed.stdout.strip().splitlines()[0] if listed.stdout.strip() else ""
            value = bool(cid) and exact(
                ["docker", "inspect", "-f", "{{.State.Running}}", cid], "true"
            )
            report.emit(key, value)
            if not value:
                report.failure(stage, RuntimeError())
                return
        cid = run(compose + ["ps", "-q", "db"]).stdout.strip().splitlines()[0]
        value = exact(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", cid], "healthy"
        )
        report.emit("DB_HEALTH_PASS", value)
        if not value:
            report.failure("STAGE_0_DB_HEALTH", RuntimeError())
            return
        revision = run(alembic_command(compose), stdin="")
        value = revision.returncode == 0 and revision.stdout.strip() == "0046"
        report.emit("ALEMBIC_0046_PASS", value)
        if not value:
            report.failure("STAGE_0_ALEMBIC", RuntimeError())
            return
        child = run(
            compose + ["exec", "-T", "api", "python3", "-B", "-"], stdin=child_source()
        )
        if child.returncode != 0 or child.stderr:
            report.failure("STAGE_1_OUTPUT", RuntimeError())
            return
        print(child.stdout, end="", flush=True)
    except Exception as exc:  # noqa: BLE001 - sanitize remote command failures
        report.failure("STAGE_1_PROTOCOL", exc)


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    if sys.argv[1] == "bundle":
        source = Path(__file__).read_text(encoding="utf-8").split("\nif __name__", 1)[0]
        print(source + "\nremote_main()\n")
        return 0
    if sys.argv[1] == "validate":
        try:
            text = Path(sys.argv[2]).read_bytes().decode("utf-8")
            result = parse_output(text)
        except Incomplete:
            print("MANUAL_M4AT1_BLOCKED=remote_incomplete")
            return 2
        except (ValueError, OSError):
            print("MANUAL_M4AT1_BLOCKED=remote_protocol")
            return 2
        print(text, end="")
        return 0 if result == "success" else 2
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "remote":
        remote_main()
    else:
        raise SystemExit(main())
