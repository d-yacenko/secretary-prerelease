"""Closed, read-only protocol for the M4BB2 scope preview probe."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RELEASE = "cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa"
TERMINAL = "M4BB2_TERMINAL"
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
CHILD_FIELDS = ("ACCOUNT_EXACTLY_ONE", "CONFIGURED_FOLDER_EXACTLY_ONE", "IGNORE_MUTED")
COUNTS = (
    "DIALOGS_SCANNED_RETAINED",
    "SCOPE_MATCH_COUNT",
    "SKIPPED_BROADCAST",
    "SKIPPED_BOT",
    "SKIPPED_UNSUPPORTED",
    "SKIPPED_OTHER",
)
FAILURE_STAGES = {stage for _, stage in GUARDS} | {
    "STAGE_1_IMPORTS",
    "STAGE_1_DB_SESSION",
    "STAGE_1_ACCOUNT_CARDINALITY",
    "STAGE_1_FOLDER_CARDINALITY",
    "STAGE_2_AUTHORIZED",
    "STAGE_2_FOLDER_DEFINITIONS",
    "STAGE_3_DIALOG_ITERATION",
    "STAGE_3_DIALOG_CONVERSION",
    "STAGE_3_OUTPUT",
    "STAGE_3_PROTOCOL",
}
EXCEPTION_CLASSES = {
    "RuntimeError", "ValueError", "TypeError", "ImportError", "ModuleNotFoundError",
    "OperationalError", "ProgrammingError", "AttributeError", "OSError", "OTHER",
}


class Incomplete(ValueError):
    pass


class Reader:
    def __init__(self, text: str):
        self.lines = text.splitlines(keepends=True)
        self.pos = 0

    def take(self, key: str, values):
        if self.pos >= len(self.lines):
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
        if self.pos >= len(self.lines):
            raise Incomplete()
        line = self.lines[self.pos]
        prefix = f"{key}="
        if not line.endswith("\n") or not line.startswith(prefix):
            raise ValueError()
        raw = line[len(prefix) : -1]
        if not raw.isdecimal() or int(raw) > 2001:
            raise ValueError()
        self.pos += 1
        return int(raw)


def _failure(reader: Reader) -> str:
    reader.take("FAILURE_STAGE", FAILURE_STAGES)
    reader.take("RAW_EXCEPTION_CLASS", EXCEPTION_CLASSES)
    reader.take("TELEGRAM_NETWORK_CALLS", range(100))
    result = reader.take(TERMINAL, ("failure", "blocked"))
    if reader.pos != len(reader.lines):
        raise ValueError()
    return result


def parse_output(text: str) -> str:
    reader = Reader(text)
    for key, stage in GUARDS:
        if not reader.boolean(key):
            reader.take("FAILURE_STAGE", (stage,))
            reader.take("RAW_EXCEPTION_CLASS", EXCEPTION_CLASSES)
            reader.take("TELEGRAM_NETWORK_CALLS", range(100))
            result = reader.take(TERMINAL, ("failure", "blocked"))
            if reader.pos != len(reader.lines):
                raise ValueError()
            return result
    for key in CHILD_FIELDS:
        if reader.pos < len(reader.lines) and reader.lines[reader.pos].startswith("FAILURE_STAGE="):
            return _failure(reader)
        reader.boolean(key)
    for key in COUNTS:
        if reader.pos < len(reader.lines) and reader.lines[reader.pos].startswith("FAILURE_STAGE="):
            return _failure(reader)
        reader.count(key)
    truncated = reader.boolean("TRUNCATED")
    if truncated and reader.lines[reader.pos - 1] not in {"TRUNCATED=true\n"}:
        raise ValueError()
    reader.count("TELEGRAM_NETWORK_CALLS")
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
        "exec", "-T", "db", "sh", "-lc",
        (
            'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 '
            '-U "${POSTGRES_USER:-secretary}" -d "${POSTGRES_DB:-secretary}" '
            '-At -c "SELECT version_num FROM alembic_version"'
        ),
    ]


def child_source() -> str:
    return r'''import asyncio
from sqlalchemy import select
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_transport import (
    TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT,
    TelethonMtprotoTransport,
    dialog_matches_filter,
)
from app.connectors.telegram.mtproto_account_store import TelegramMtprotoAccountStore
from app.core.config import settings
from app.db.models import TelegramMtprotoAccount
from app.db.session import SessionLocal

def emit(key, value):
    print(f"{key}={str(value).lower() if isinstance(value, bool) else value}", flush=True)

async def run():
    accounts = []
    folders = []
    try:
        with SessionLocal(autoflush=False) as db:
            accounts = list(db.scalars(select(TelegramMtprotoAccount)))
            account_ok = len(accounts) == 1
            emit("ACCOUNT_EXACTLY_ONE", account_ok)
            if not account_ok:
                emit("CONFIGURED_FOLDER_EXACTLY_ONE", False)
                raise RuntimeError("account cardinality")
            account = accounts[0]
            encryption = CredentialEncryption(settings.secretary_credential_key)
            store = TelegramMtprotoAccountStore(db, encryption)
            folders = store.list_sync_folders(account.id)
            folder_ok = len(folders) == 1
            emit("CONFIGURED_FOLDER_EXACTLY_ONE", folder_ok)
            if not folder_ok:
                raise RuntimeError("folder cardinality")
            session = store.decrypt_session(account)
            folder = folders[0]
        emit("IGNORE_MUTED", True)
        transport = TelethonMtprotoTransport(settings.telegram_api_id, settings.telegram_api_hash.strip())
        discovered = await transport.discover_folders(session, 500)
        matching = [item for item in discovered.folders if item.folder_id == folder.folder_id]
        if len(matching) != 1:
            raise RuntimeError("folder definitions")
        universe = await transport.fetch_dialog_universe(
            session, TELEGRAM_MTPROTO_SCOPE_DIALOG_SCAN_LIMIT
        )
        matched = {
            dialog.peer_id
            for dialog in universe.dialogs
            if not dialog.is_muted and dialog_matches_filter(matching[0].definition, dialog)
        }
        skipped = universe.skipped_counts
        emit("DIALOGS_SCANNED_RETAINED", len(universe.dialogs))
        emit("SCOPE_MATCH_COUNT", len(matched))
        emit("SKIPPED_BROADCAST", skipped.get("broadcast", 0))
        emit("SKIPPED_BOT", skipped.get("bot", 0))
        emit("SKIPPED_UNSUPPORTED", skipped.get("unsupported", 0))
        emit("SKIPPED_OTHER", sum(value for key, value in skipped.items() if key not in {"broadcast", "bot", "unsupported"}))
        emit("TRUNCATED", universe.truncated)
        emit("TELEGRAM_NETWORK_CALLS", 6)
        emit("M4BB2_TERMINAL", "success")
    except Exception as exc:  # noqa: BLE001 - sanitize all remote failures
        emit("FAILURE_STAGE", "STAGE_1_DB_SESSION")
        allowed = {"RuntimeError", "ValueError", "TypeError", "ImportError", "ModuleNotFoundError", "OperationalError", "ProgrammingError", "AttributeError", "OSError"}
        emit("RAW_EXCEPTION_CLASS", type(exc).__name__ if type(exc).__name__ in allowed else "OTHER")
        emit("TELEGRAM_NETWORK_CALLS", 0)
        emit("M4BB2_TERMINAL", "failure")

asyncio.run(run())
'''


def remote_main() -> None:
    report = Report(sys.stdout)
    compose = ["docker", "compose", "--env-file", "/opt/secretary/.env", "-f", "infra/compose.yaml", "-f", "infra/compose.deploy.yaml"]

    def run(command, *, stdin=None):
        return subprocess.run(command, input=stdin, text=True, capture_output=True, check=False, stdin=subprocess.DEVNULL if stdin is None else None)

    def exact(command, expected):
        result = run(command)
        return result.returncode == 0 and result.stdout.strip() == expected

    try:
        os.chdir("/opt/secretary")
        checks = (
            ("REMOTE_REPO_PASS", lambda: exact(["git", "remote", "get-url", "origin"], "https://github.com/d-yacenko/secretary-prerelease.git"), "STAGE_0_REPO"),
            ("REMOTE_HEAD_PASS", lambda: exact(["git", "rev-parse", "HEAD"], RELEASE), "STAGE_0_RELEASE_REF"),
            ("REMOTE_PRODUCTION_REF_PASS", lambda: exact(["git", "rev-parse", "origin/production"], RELEASE), "STAGE_0_PRODUCTION_REF"),
            ("REMOTE_WORKTREE_CLEAN", lambda: exact(["git", "status", "--porcelain"], ""), "STAGE_0_WORKTREE"),
            ("COMPOSE_CONFIG_PASS", lambda: run(compose + ["config", "--format", "json"]).returncode == 0, "STAGE_0_COMPOSE"),
        )
        for key, check, stage in checks:
            value = bool(check()); report.emit(key, value)
            if not value: report.failure(stage, RuntimeError()); return
        for service, key, stage in (("db", "DB_RUNNING_PASS", "STAGE_0_DB_RUNNING"), ("api", "API_RUNNING_PASS", "STAGE_0_API_RUNNING"), ("worker", "WORKER_RUNNING_PASS", "STAGE_0_WORKER_RUNNING")):
            listed = run(compose + ["ps", "-q", service]); cid = listed.stdout.strip().splitlines()[0] if listed.stdout.strip() else ""
            value = bool(cid) and exact(["docker", "inspect", "-f", "{{.State.Running}}", cid], "true")
            report.emit(key, value)
            if not value: report.failure(stage, RuntimeError()); return
        cid = run(compose + ["ps", "-q", "db"]).stdout.strip().splitlines()[0]
        value = exact(["docker", "inspect", "-f", "{{.State.Health.Status}}", cid], "healthy"); report.emit("DB_HEALTH_PASS", value)
        if not value: report.failure("STAGE_0_DB_HEALTH", RuntimeError()); return
        revision = run(alembic_command(compose), stdin="")
        value = revision.returncode == 0 and revision.stdout.strip() == "0046"; report.emit("ALEMBIC_0046_PASS", value)
        if not value: report.failure("STAGE_0_ALEMBIC", RuntimeError()); return
        child = run(compose + ["exec", "-T", "api", "python3", "-B", "-"], stdin=child_source())
        if child.returncode != 0 or child.stderr: report.failure("STAGE_3_OUTPUT", RuntimeError()); return
        print(child.stdout, end="", flush=True)
    except Exception as exc:  # noqa: BLE001 - sanitize all remote failures
        report.failure("STAGE_3_PROTOCOL", exc)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "bundle":
        print(Path(__file__).read_text(encoding="utf-8").split("\nif __name__", 1)[0] + "\nremote_main()\n")
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "validate":
        try:
            result = parse_output(Path(sys.argv[2]).read_bytes().decode("utf-8"))
        except Incomplete:
            print("MANUAL_M4BB2_BLOCKED=remote_incomplete"); return 2
        except (ValueError, OSError):
            print("MANUAL_M4BB2_BLOCKED=remote_protocol"); return 2
        print(Path(sys.argv[2]).read_text(), end="")
        return 0 if result == "success" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
