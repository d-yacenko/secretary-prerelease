"""Human-only M4AO1 probe, streamed in memory; local modes never contact production.

Logical provider counters include connect/authorization/iteration attempts, not
transport packets or disconnect cleanup. No application sync or persistence runs.
"""

import asyncio
import contextlib
import io
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

RELEASE = "23fa07df213d5a70a6dc1d3c8b32af39228107eb"
TERMINAL = "M4AO1_TERMINAL"
CLASSES = {
    "RuntimeError",
    "ValueError",
    "TypeError",
    "AttributeError",
    "ImportError",
    "ModuleNotFoundError",
    "OperationalError",
    "ProgrammingError",
    "InvalidToken",
    "TelegramMtprotoProviderReferenceInvalidError",
    "InvalidHistoryEntry",
    "AuthKeyError",
    "AuthKeyNotFound",
    "AuthKeyUnregisteredError",
    "SessionRevokedError",
    "UnauthorizedError",
    "UserDeactivatedBanError",
    "UserDeactivatedError",
    "ChannelInvalidError",
    "ChannelPrivateError",
    "ChatIdInvalidError",
    "PeerIdInvalidError",
    "FloodWaitError",
    "TimeoutError",
    "ConnectionError",
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
STRUCTURE = (
    ("IMPORTS_PASS", "STAGE_1_IMPORTS", True),
    ("DB_QUERY_PASS", "STAGE_1_DB_SESSION", True),
    ("ACCOUNT_EXACTLY_ONE", "STAGE_1_DB_SESSION", True),
    ("MANUAL_SELECTED_EXACTLY_ONE", "STAGE_1_DB_SESSION", True),
    ("INITIAL_STATE", "STAGE_1_STATE", True),
    ("HISTORY_COMPLETE_BEFORE", "STAGE_1_STATE", False),
    ("BACKFILL_CURSOR_PRESENT_BEFORE", "STAGE_1_STATE", False),
    ("CUTOFF_READ_PASS", "STAGE_1_STATE", True),
    ("SESSION_DECRYPT_PASS", "STAGE_1_SESSION_DECRYPT", True),
    ("STRING_SESSION_PARSE_PASS", "STAGE_1_SESSION_PARSE", True),
    ("REFERENCE_DECRYPT_PASS", "STAGE_1_REFERENCE_DECRYPT", True),
    ("REFERENCE_PARSE_PASS", "STAGE_1_REFERENCE_PARSE", True),
    ("REFERENCE_PEER_MATCH_PASS", "STAGE_1_REFERENCE_PEER_MATCH", True),
)
COUNTERS = (
    "CONNECT_CALL_COUNT",
    "IS_USER_AUTHORIZED_CALL_COUNT",
    "ITER_MESSAGES_CALL_COUNT",
    "MESSAGES_SEEN_TOTAL",
    "ENTRIES_CONVERTED_TOTAL",
    "TELEGRAM_NETWORK_CALLS",
)


class ProbeFailure(Exception):
    def __init__(self, stage, exc, ordinal=0):
        self.stage = stage
        self.kind = type(exc).__name__ if type(exc).__name__ in CLASSES else "OTHER"
        self.ordinal = ordinal


class InvalidHistoryEntry(RuntimeError):
    pass


class Incomplete(ValueError):
    pass


class Reader:
    def __init__(self, text):
        self.lines = text.splitlines(keepends=True)
        self.pos = 0

    def take(self, key, values):
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

    def boolean(self, key):
        return self.take(key, ("true", "false")) == "true"

    def count(self, key, bound):
        return self.take(key, range(bound + 1))


def parse_output(text, *, child=False):
    """Validate exact order, terminal outcome, stage-specific counters and sums."""
    r = Reader(text)
    calls = [0, 0, 0]
    seen_total = converted_total = 0

    def finish(stage=None, ordinal=0):
        if stage:
            r.take("FAILURE_STAGE", (stage,))
            r.take("RAW_EXCEPTION_CLASS", CLASSES)
            r.take("MESSAGE_ORDINAL", (ordinal,))
        values = (*calls, seen_total, converted_total, sum(calls))
        for key, value in zip(COUNTERS, values, strict=True):
            r.take(key, (value,))
        result = r.take(TERMINAL, ("failure" if stage else "success",))
        if r.pos != len(r.lines):
            raise ValueError()
        return result

    if not child:
        for key, stage in GUARDS:
            if not r.boolean(key):
                return finish(stage)
        r.take("CHILD_STARTED", ("true",))
        if r.pos < len(r.lines) and r.lines[r.pos].startswith("REMOTE_BLOCKED="):
            r.take("REMOTE_BLOCKED", ("child_protocol", "child_execution"))
            r.take(TERMINAL, ("blocked",))
            if r.pos != len(r.lines):
                raise ValueError()
            return "blocked"
    for key, stage, expected in STRUCTURE:
        if r.boolean(key) != expected:
            return finish(stage)
    for number in (1, 2):
        passed = r.boolean(f"PAGE{number}_PASS")
        seen = r.count(f"PAGE{number}_MESSAGES_SEEN", 100)
        converted = r.count(f"PAGE{number}_ENTRIES_CONVERTED", 100)
        none = r.count(f"PAGE{number}_ENTRIES_NONE", 1)
        seen_total += seen
        converted_total += converted
        if not passed:
            connect, auth, iteration, conversion = page_stages(number)
            construct = connect.replace("_CONNECT", "_CLIENT")
            stage = r.take(
                "FAILURE_STAGE", (construct, connect, auth, iteration, conversion)
            )
            # Rewind: finish consumes the same allowlisted failure line.
            r.pos -= 1
            calls[:] = [
                number - (stage == construct),
                number - (stage in (construct, connect)),
                number - (stage in (construct, connect, auth)),
            ]
            if stage in (construct, connect, auth):
                if (seen, converted, none) != (0, 0, 0):
                    raise ValueError()
                ordinal = 0
            elif stage == iteration:
                if seen != converted or none or seen >= 100:
                    raise ValueError()
                ordinal = seen + 1
            else:
                if seen < 1 or converted != seen - 1:
                    raise ValueError()
                ordinal = seen
            return finish(stage, ordinal)
        if seen != converted or none:
            raise ValueError()
        calls[:] = [number] * 3
        if number == 1:
            # Derivation can fail after page1, before a page2 decision.
            if r.pos < len(r.lines) and r.lines[r.pos].startswith("FAILURE_STAGE="):
                return finish("STAGE_3_PAGE2_STATE")
            required = r.boolean("PAGE2_REQUIRED")
            if not required:
                break
            if seen != 100:
                raise ValueError()
    return finish()


class Report:
    def __init__(self, output):
        self.output = output
        self.calls = [0, 0, 0]
        self.seen = self.converted = 0

    def emit(self, key, value):
        if isinstance(value, bool):
            value = str(value).lower()
        print(f"{key}={value}", file=self.output, flush=True)

    def check(self, key, stage, operation, expected=True):
        try:
            result = operation()
        except Exception as exc:  # noqa: BLE001 - sanitize all dependency/provider failures
            self.emit(key, not expected)
            raise ProbeFailure(stage, exc) from None
        self.emit(key, bool(result))
        if bool(result) != expected:
            raise ProbeFailure(stage, RuntimeError())
        return result

    def finish(self, failure=None):
        if failure:
            self.emit("FAILURE_STAGE", failure.stage)
            self.emit("RAW_EXCEPTION_CLASS", failure.kind)
            self.emit("MESSAGE_ORDINAL", failure.ordinal)
        for key, value in zip(
            COUNTERS,
            (*self.calls, self.seen, self.converted, sum(self.calls)),
            strict=True,
        ):
            self.emit(key, value)
        self.emit(TERMINAL, "failure" if failure else "success")


def page_stages(number):
    first, second = (2, 3) if number == 1 else (4, 5)
    return (
        f"STAGE_{first}_PAGE{number}_CONNECT",
        f"STAGE_{first}_PAGE{number}_AUTHORIZED",
        f"STAGE_{second}_PAGE{number}_ITERATION",
        f"STAGE_{second}_PAGE{number}_CONVERSION",
    )


async def probe_page(report, deps, session, peer, number, *, max_id=None):
    connect, auth, iteration, conversion = page_stages(number)
    stage = connect.replace("_CONNECT", "_CLIENT")
    ordinal = seen = none = 0
    entries = []
    client = None
    failure = None
    try:
        # Fresh in-memory session per page; no reconnect/retry/sleep retry.
        client = deps.TelegramClient(
            deps.StringSession(session),
            deps.settings.telegram_api_id,
            deps.settings.telegram_api_hash,
            request_retries=0,
            connection_retries=0,
            auto_reconnect=False,
            flood_sleep_threshold=0,
            receive_updates=False,
        )
        stage = connect
        report.calls[0] += 1
        await client.connect()
        stage = auth
        report.calls[1] += 1
        if not await client.is_user_authorized():
            raise RuntimeError()
        stage = iteration
        ordinal = 1
        report.calls[2] += 1
        iterator = client.iter_messages(
            peer, limit=100, min_id=None, max_id=max_id, reverse=False
        )
        iterator = iterator.__aiter__()
        # Never request a 101st item, even from a nonconforming iterator.
        for ordinal in range(1, 101):
            stage = iteration
            try:
                message = await iterator.__anext__()
            except StopAsyncIteration:
                break
            seen += 1
            report.seen += 1
            stage = conversion
            entry = deps._history_entry_from_message(message)
            if entry is None:
                none += 1
                raise InvalidHistoryEntry()
            entries.append(entry)
            report.converted += 1
    except Exception as exc:  # noqa: BLE001 - sanitize all dependency/provider failures
        failure = ProbeFailure(stage, exc, ordinal)
    finally:
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001, S110 - cleanup must not leak raw errors
                pass
    report.emit(f"PAGE{number}_PASS", failure is None)
    report.emit(f"PAGE{number}_MESSAGES_SEEN", seen)
    report.emit(f"PAGE{number}_ENTRIES_CONVERTED", len(entries))
    report.emit(f"PAGE{number}_ENTRIES_NONE", none)
    if failure:
        raise failure
    return entries


def dependencies():
    from types import SimpleNamespace

    from app.connectors.google.encryption import CredentialEncryption
    from app.connectors.telegram.mtproto_transport import (
        TelegramMtprotoHistoryPage,
        _history_entry_from_message,
        _input_peer_from_reference,
        validate_provider_peer_reference,
    )
    from app.core.config import settings
    from app.db.models import TelegramMtprotoAccount, TelegramMtprotoChatSelection
    from app.db.session import SessionLocal
    from app.services.telegram_mtproto_history_service import (
        TELEGRAM_MTPROTO_HISTORY_DAYS,
        _next_backfill_state,
    )
    from sqlalchemy import select
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    return SimpleNamespace(
        select=select,
        TelegramClient=TelegramClient,
        StringSession=StringSession,
        CredentialEncryption=CredentialEncryption,
        TelegramMtprotoHistoryPage=TelegramMtprotoHistoryPage,
        _history_entry_from_message=_history_entry_from_message,
        _input_peer_from_reference=_input_peer_from_reference,
        validate_provider_peer_reference=validate_provider_peer_reference,
        settings=settings,
        TelegramMtprotoAccount=TelegramMtprotoAccount,
        TelegramMtprotoChatSelection=TelegramMtprotoChatSelection,
        SessionLocal=SessionLocal,
        TELEGRAM_MTPROTO_HISTORY_DAYS=TELEGRAM_MTPROTO_HISTORY_DAYS,
        _next_backfill_state=_next_backfill_state,
    )


async def child_probe(report, deps):
    def read_state():
        with deps.SessionLocal(autoflush=False) as db:
            accounts = list(db.scalars(deps.select(deps.TelegramMtprotoAccount)))
            selections = list(
                db.scalars(
                    deps.select(deps.TelegramMtprotoChatSelection).where(
                        deps.TelegramMtprotoChatSelection.manual_selected.is_(True)
                    )
                )
            )
        return accounts, selections

    accounts, selections = report.check(
        "DB_QUERY_PASS", "STAGE_1_DB_SESSION", read_state
    )
    report.check(
        "ACCOUNT_EXACTLY_ONE", "STAGE_1_DB_SESSION", lambda: len(accounts) == 1
    )
    report.check(
        "MANUAL_SELECTED_EXACTLY_ONE",
        "STAGE_1_DB_SESSION",
        lambda: len(selections) == 1,
    )
    account, selection = accounts[0], selections[0]
    report.check(
        "INITIAL_STATE",
        "STAGE_1_STATE",
        lambda: selection.history_latest_message_id is None,
    )
    report.check(
        "HISTORY_COMPLETE_BEFORE",
        "STAGE_1_STATE",
        lambda: selection.history_complete,
        False,
    )
    report.check(
        "BACKFILL_CURSOR_PRESENT_BEFORE",
        "STAGE_1_STATE",
        lambda: selection.history_backfill_before_message_id is not None,
        False,
    )
    # Snapshot cutoff before page1, matching production _sync_selection.
    cutoff = report.check(
        "CUTOFF_READ_PASS",
        "STAGE_1_STATE",
        lambda: (
            selection.history_cutoff_at
            or datetime.now(UTC) - timedelta(days=deps.TELEGRAM_MTPROTO_HISTORY_DAYS)
        ),
    )
    encryption = None

    def decrypt_session():
        nonlocal encryption
        encryption = deps.CredentialEncryption(deps.settings.secretary_credential_key)
        return encryption.decrypt(account.session_encrypted)

    session = report.check(
        "SESSION_DECRYPT_PASS", "STAGE_1_SESSION_DECRYPT", decrypt_session
    )
    report.check(
        "STRING_SESSION_PARSE_PASS",
        "STAGE_1_SESSION_PARSE",
        lambda: deps.StringSession(session),
    )
    reference = report.check(
        "REFERENCE_DECRYPT_PASS",
        "STAGE_1_REFERENCE_DECRYPT",
        lambda: encryption.decrypt(selection.provider_peer_reference_encrypted),
    )
    report.check(
        "REFERENCE_PARSE_PASS",
        "STAGE_1_REFERENCE_PARSE",
        lambda: deps._input_peer_from_reference(reference),
    )
    peer = report.check(
        "REFERENCE_PEER_MATCH_PASS",
        "STAGE_1_REFERENCE_PEER_MATCH",
        lambda: deps.validate_provider_peer_reference(
            reference, expected_peer_id=selection.peer_id
        ),
    )
    first = await probe_page(report, deps, session, peer, 1)
    try:
        cursor, complete = deps._next_backfill_state(
            deps.TelegramMtprotoHistoryPage(
                entries=tuple(first), has_more=len(first) >= 100
            ),
            cutoff,
        )
        required = not complete and cursor is not None
        if required and (type(cursor) is not int or cursor <= 0 or len(first) != 100):
            raise ValueError()
    except Exception as exc:  # noqa: BLE001 - sanitize all dependency/provider failures
        raise ProbeFailure("STAGE_3_PAGE2_STATE", exc) from None
    report.emit("PAGE2_REQUIRED", required)
    if required:
        await probe_page(report, deps, session, peer, 2, max_id=cursor)


def child_main():
    report = Report(sys.stdout)
    logging.disable(logging.CRITICAL)
    # Dependency/library stdout and stderr never enter the protocol.
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        try:
            deps = report.check("IMPORTS_PASS", "STAGE_1_IMPORTS", dependencies)
            asyncio.run(child_probe(report, deps))
        except ProbeFailure as exc:
            report.finish(exc)
        else:
            report.finish()


def remote_main(source):
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

    def run(argv, payload=None):
        return subprocess.run(
            argv,
            input=payload,
            stdin=subprocess.DEVNULL if payload is None else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )

    def matches(argv, expected):
        result = run(argv)
        return result.returncode == 0 and result.stdout.strip() == expected

    def repo():
        os.chdir("/opt/secretary")
        return matches(
            ["git", "remote", "get-url", "origin"],
            "https://github.com/d-yacenko/secretary-prerelease.git",
        )

    def service(name, health=False):
        result = run(compose + ["ps", "-q", name])
        ids = result.stdout.splitlines()
        if result.returncode or len(ids) != 1:
            return False
        field = "{{.State.Health.Status}}" if health else "{{.State.Running}}"
        return matches(
            ["docker", "inspect", "-f", field, ids[0]], "healthy" if health else "true"
        )

    operations = (
        repo,
        lambda: matches(["git", "rev-parse", "HEAD"], RELEASE),
        lambda: matches(["git", "rev-parse", "origin/production"], RELEASE),
        lambda: matches(["git", "status", "--porcelain"], ""),
        lambda: run(compose + ["config", "--format", "json"]).returncode == 0,
        lambda: service("db"),
        lambda: service("api"),
        lambda: service("worker"),
        lambda: service("db", True),
        lambda: matches(
            compose
            + [
                "exec",
                "-T",
                "db",
                "sh",
                "-lc",
                (
                    'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "${POSTGRES_USER:-secretary}" '
                    '-d "${POSTGRES_DB:-secretary}" -At -c "SELECT version_num FROM alembic_version"'
                ),
            ],
            "0046",
        ),
    )
    try:
        for (key, stage), operation in zip(GUARDS, operations, strict=True):
            report.check(key, stage, operation)
    except ProbeFailure as exc:
        report.finish(exc)
        return
    report.emit("CHILD_STARTED", True)
    try:
        result = run(
            compose + ["exec", "-T", "api", "python3", "-B", "-"],
            source + "\nchild_main()\n",
        )
        parse_output(result.stdout, child=True)
        if result.returncode or result.stderr:
            report.emit("REMOTE_BLOCKED", "child_execution")
            report.emit(TERMINAL, "blocked")
            return  # No invented zero-call result after an uncertain child execution.
    except (ValueError, OSError, subprocess.SubprocessError):
        report.emit("REMOTE_BLOCKED", "child_protocol")
        report.emit(TERMINAL, "blocked")
        return
    print(result.stdout, end="", flush=True)


def main():
    if len(sys.argv) < 2:
        return 0
    if sys.argv[1] == "bundle":
        source = Path(__file__).read_text().split("\nif __name__ ==", 1)[0]
        print(source + "\nremote_main(" + repr(source) + ")\n")
        return 0
    if sys.argv[1] == "validate":
        try:
            text = Path(sys.argv[2]).read_bytes().decode("utf-8")
            result = parse_output(text)
        except Incomplete:
            print("MANUAL_M4AO1_BLOCKED=remote_incomplete")
            return 2
        except (ValueError, OSError):
            print("MANUAL_M4AO1_BLOCKED=remote_protocol")
            return 2
        print(text, end="")
        return {"success": 0, "failure": 3, "blocked": 2}[result]
    return 0


if __name__ == "__main__":
    sys.exit(main())
