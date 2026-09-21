"""Closed, read-only protocol for the M4BD1 post-deploy acceptance probe."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RELEASE = "c69d2353c19c4958e1fb60aac69466fcf6ac1482"
TERMINAL = "M4BD1_TERMINAL"
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
FIELDS = (
    "ACCOUNT_COUNT", "CONFIGURED_FOLDER_COUNT", "ACTIVE_SCOPE_COUNT", "MANUAL_ACTIVE_COUNT",
    "FOLDER_ONLY_ACTIVE_COUNT", "LATEST_CURSOR_PRESENT_COUNT", "HISTORY_COMPLETE_COUNT",
    "BACKFILL_CURSOR_PRESENT_COUNT", "HISTORY_CUTOFF_PRESENT_COUNT", "ACTIVE_PEERS_WITH_OBJECTS_GT_20",
    "ACTIVE_PEER_OBJECT_COUNT_MAX", "MTPROTO_OBJECT_COUNT", "MTPROTO_INBOUND_COUNT",
    "MTPROTO_OUTBOUND_COUNT", "MTPROTO_OBJECTS_WITH_EMBEDDING",
    "MTPROTO_OBJECTS_WITH_CURRENT_EMBEDDING_PROVENANCE", "MTPROTO_PENDING_RUNNING_EMBED_JOBS",
)
FAILURE_STAGES = {stage for _, stage in GUARDS} | {"STAGE_1_IMPORTS", "STAGE_1_DB_SESSION", "STAGE_1_OUTPUT", "STAGE_1_PROTOCOL"}
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

    def count(self, key: str) -> int:
        if self.pos >= len(self.lines):
            raise Incomplete()
        line = self.lines[self.pos]
        prefix = f"{key}="
        if not line.endswith("\n") or not line.startswith(prefix):
            raise ValueError()
        raw = line[len(prefix) : -1]
        if not raw.isdecimal() or int(raw) > 10_000_000:
            raise ValueError()
        self.pos += 1
        return int(raw)


def _failure(reader: Reader) -> str:
    reader.take("FAILURE_STAGE", FAILURE_STAGES)
    reader.take("RAW_EXCEPTION_CLASS", EXCEPTION_CLASSES)
    reader.take("TELEGRAM_NETWORK_CALLS", ("0",))
    reader.take("DB_WRITES", ("0",))
    result = reader.take(TERMINAL, ("failure", "blocked"))
    if reader.pos != len(reader.lines):
        raise ValueError()
    return result


def parse_output(text: str) -> str:
    reader = Reader(text)
    for key, stage in GUARDS:
        value = reader.take(key, ("true", "false"))
        if value == "false":
            reader.take("FAILURE_STAGE", (stage,))
            reader.take("RAW_EXCEPTION_CLASS", EXCEPTION_CLASSES)
            reader.take("TELEGRAM_NETWORK_CALLS", ("0",))
            reader.take("DB_WRITES", ("0",))
            result = reader.take(TERMINAL, ("failure", "blocked"))
            if reader.pos != len(reader.lines):
                raise ValueError()
            return result
    if reader.pos < len(reader.lines) and reader.lines[reader.pos].startswith("FAILURE_STAGE="):
        return _failure(reader)
    reader.take("PRODUCTION_RELEASE", (RELEASE,))
    reader.take("ALEMBIC", ("0046",))
    for key in FIELDS:
        if reader.pos < len(reader.lines) and reader.lines[reader.pos].startswith("FAILURE_STAGE="):
            return _failure(reader)
        reader.count(key)
    reader.take("TELEGRAM_NETWORK_CALLS", ("0",))
    reader.take("DB_WRITES", ("0",))
    result = reader.take(TERMINAL, ("success",))
    if reader.pos != len(reader.lines):
        raise ValueError()
    return result


class Report:
    def __init__(self, stream):
        self.stream = stream

    def emit(self, key: str, value):
        print(f"{key}={value}", file=self.stream, flush=True)

    def failure(self, stage: str, exc: BaseException):
        name = type(exc).__name__
        self.emit("FAILURE_STAGE", stage)
        self.emit("RAW_EXCEPTION_CLASS", name if name in EXCEPTION_CLASSES else "OTHER")
        self.emit("TELEGRAM_NETWORK_CALLS", 0)
        self.emit("DB_WRITES", 0)
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
    return r'''from sqlalchemy import func, select
from app.db.models import Job, Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection, TelegramMtprotoSyncFolder
from app.db.session import SessionLocal
from app.jobs.constants import JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_TYPE_EMBED_OBJECT
from app.llm.embedding_text import embedding_input_signature

def emit(key, value):
    print(f"{key}={value}", flush=True)

try:
    with SessionLocal(autoflush=False) as db:
        accounts = list(db.scalars(select(TelegramMtprotoAccount)))
        emit("ACCOUNT_COUNT", len(accounts))
        if len(accounts) != 1:
            raise RuntimeError("account cardinality")
        account = accounts[0]
        folders = list(db.scalars(select(TelegramMtprotoSyncFolder).where(
            TelegramMtprotoSyncFolder.account_id == account.id)))
        emit("CONFIGURED_FOLDER_COUNT", len(folders))
        if len(folders) != 1:
            raise RuntimeError("folder cardinality")
        selections = list(db.scalars(select(TelegramMtprotoChatSelection).where(
            TelegramMtprotoChatSelection.account_id == account.id)))
        active = [row for row in selections if row.scope_active]
        emit("ACTIVE_SCOPE_COUNT", len(active))
        emit("MANUAL_ACTIVE_COUNT", sum(row.scope_active and row.manual_selected for row in selections))
        emit("FOLDER_ONLY_ACTIVE_COUNT", sum(row.scope_active and not row.manual_selected for row in selections))
        emit("LATEST_CURSOR_PRESENT_COUNT", sum(row.scope_active and row.history_latest_message_id is not None for row in selections))
        emit("HISTORY_COMPLETE_COUNT", sum(row.scope_active and row.history_complete for row in selections))
        emit("BACKFILL_CURSOR_PRESENT_COUNT", sum(row.scope_active and row.history_backfill_before_message_id is not None for row in selections))
        emit("HISTORY_CUTOFF_PRESENT_COUNT", sum(row.scope_active and row.history_cutoff_at is not None for row in selections))
        exact = (
            Object.user_id == account.user_id,
            Object.provider == "telegram",
            Object.kind == "chat_message",
            Object.metadata_["transport"].as_string() == "mtproto",
            Object.metadata_["account_id"].as_string() == str(account.id),
        )
        peer_counts = dict(db.execute(select(
            Object.metadata_["peer_id"].as_string(), func.count()
        ).where(*exact).group_by(Object.metadata_["peer_id"].as_string())).all())
        active_ids = {str(row.peer_id) for row in active}
        active_counts = [count for peer, count in peer_counts.items() if peer in active_ids]
        emit("ACTIVE_PEERS_WITH_OBJECTS_GT_20", sum(count > 20 and peer in {str(row.peer_id) for row in active if not row.manual_selected} for peer, count in peer_counts.items()))
        emit("ACTIVE_PEER_OBJECT_COUNT_MAX", max(active_counts, default=0))
        objects = list(db.scalars(select(Object).where(*exact)))
        emit("MTPROTO_OBJECT_COUNT", len(objects))
        emit("MTPROTO_INBOUND_COUNT", sum((obj.metadata_ or {}).get("direction") != "outbound" for obj in objects))
        emit("MTPROTO_OUTBOUND_COUNT", sum((obj.metadata_ or {}).get("direction") == "outbound" for obj in objects))
        emit("MTPROTO_OBJECTS_WITH_EMBEDDING", sum(obj.embedding is not None for obj in objects))
        emit("MTPROTO_OBJECTS_WITH_CURRENT_EMBEDDING_PROVENANCE", sum(
            obj.embedding is not None and obj.embedding_signature == embedding_input_signature(obj) for obj in objects
        ))
        object_ids = {str(obj.id) for obj in objects}
        jobs = db.scalars(select(Job).where(
            Job.type == JOB_TYPE_EMBED_OBJECT,
            Job.status.in_((JOB_STATUS_PENDING, JOB_STATUS_RUNNING)),
        ))
        emit("MTPROTO_PENDING_RUNNING_EMBED_JOBS", sum(
            (job.payload or {}).get("object_id") in object_ids for job in jobs
        ))
        emit("TELEGRAM_NETWORK_CALLS", 0)
        emit("DB_WRITES", 0)
        emit("M4BD1_TERMINAL", "success")
except Exception as exc:
    emit("FAILURE_STAGE", "STAGE_1_DB_SESSION")
    allowed = {"RuntimeError", "ValueError", "TypeError", "ImportError", "ModuleNotFoundError", "OperationalError", "ProgrammingError", "AttributeError", "OSError"}
    emit("RAW_EXCEPTION_CLASS", type(exc).__name__ if type(exc).__name__ in allowed else "OTHER")
    emit("TELEGRAM_NETWORK_CALLS", 0)
    emit("DB_WRITES", 0)
    emit("M4BD1_TERMINAL", "failure")
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
            value = bool(check()); report.emit(key, str(value).lower())
            if not value: report.failure(stage, RuntimeError()); return
        for service, key, stage in (("db", "DB_RUNNING_PASS", "STAGE_0_DB_RUNNING"), ("api", "API_RUNNING_PASS", "STAGE_0_API_RUNNING"), ("worker", "WORKER_RUNNING_PASS", "STAGE_0_WORKER_RUNNING")):
            listed = run(compose + ["ps", "-q", service]); cid = listed.stdout.strip().splitlines()[0] if listed.stdout.strip() else ""
            value = bool(cid) and exact(["docker", "inspect", "-f", "{{.State.Running}}", cid], "true")
            report.emit(key, str(value).lower())
            if not value: report.failure(stage, RuntimeError()); return
        cid = run(compose + ["ps", "-q", "db"]).stdout.strip().splitlines()[0]
        value = exact(["docker", "inspect", "-f", "{{.State.Health.Status}}", cid], "healthy"); report.emit("DB_HEALTH_PASS", str(value).lower())
        if not value: report.failure("STAGE_0_DB_HEALTH", RuntimeError()); return
        revision = run(alembic_command(compose), stdin="")
        value = revision.returncode == 0 and revision.stdout.strip() == "0046"; report.emit("ALEMBIC_0046_PASS", str(value).lower())
        if not value: report.failure("STAGE_0_ALEMBIC", RuntimeError()); return
        report.emit("PRODUCTION_RELEASE", RELEASE); report.emit("ALEMBIC", "0046")
        child = run(compose + ["exec", "-T", "api", "python3", "-B", "-"], stdin=child_source())
        if child.returncode != 0 or child.stderr: report.failure("STAGE_1_OUTPUT", RuntimeError()); return
        print(child.stdout, end="", flush=True)
    except Exception as exc:  # noqa: BLE001 - sanitize remote failures
        report.failure("STAGE_1_PROTOCOL", exc)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "bundle":
        print(Path(__file__).read_text(encoding="utf-8").split("\nif __name__", 1)[0] + "\nremote_main()\n")
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "validate":
        try:
            result = parse_output(Path(sys.argv[2]).read_bytes().decode("utf-8"))
        except Incomplete:
            print("MANUAL_M4BD1_BLOCKED=remote_incomplete"); return 2
        except (ValueError, OSError):
            print("MANUAL_M4BD1_BLOCKED=remote_protocol"); return 2
        print(Path(sys.argv[2]).read_text(), end="")
        return 0 if result == "success" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
