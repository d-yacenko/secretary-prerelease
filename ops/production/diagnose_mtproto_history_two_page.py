"""Read-only, bounded reproduction of the production MTProto history sequence.

This diagnostic is intentionally review-only.  It never materializes entries or
uses the application history service; the remote child calls the exact message
conversion helper and reports only bounded, sanitized aggregates.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.production import deploy

EXPECTED_RELEASE = "23fa07df213d5a70a6dc1d3c8b32af39228107eb"
EXPECTED_TARGET = "root@web-itx.duckdns.org"
EXPECTED_PORT = 22
EXPECTED_PIN = "SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs"
PAGE_SIZE = 100
MAX_MESSAGES = 200
MAX_ATTEMPTS = 3
REMOTE_BEGIN = "HISTORY_TWO_PAGE_REMOTE_BEGIN"
REMOTE_END = "HISTORY_TWO_PAGE_REMOTE_END"
EXCEPTION_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")

FAILURE_STAGES = {
    "STAGE_1_IMPORTS",
    "STAGE_1_DB_SESSION",
    "STAGE_1_SESSION_DECRYPT",
    "STAGE_1_REFERENCE_DECRYPT",
    "STAGE_1_REFERENCE_PARSE",
    "STAGE_1_REFERENCE_PEER_MATCH",
    "STAGE_2_PAGE1_CONNECT",
    "STAGE_2_PAGE1_AUTHORIZED",
    "STAGE_3_PAGE1_ITERATION",
    "STAGE_3_PAGE1_CONVERSION",
    "STAGE_4_PAGE2_CONNECT",
    "STAGE_4_PAGE2_AUTHORIZED",
    "STAGE_5_PAGE2_ITERATION",
    "STAGE_5_PAGE2_CONVERSION",
}

BOOLEAN_KEYS = {
    "STAGE_0_ACCOUNT_EXACTLY_ONE",
    "STAGE_0_MANUAL_SELECTED_GROUP_EXACTLY_ONE",
    "INITIAL_STATE",
    "HISTORY_COMPLETE_BEFORE",
    "BACKFILL_CURSOR_PRESENT_BEFORE",
    "PAGE2_REQUIRED",
    "SESSION_DECRYPT_PASS",
    "STRING_SESSION_PARSE_PASS",
    "REFERENCE_DECRYPT_PASS",
    "REFERENCE_PARSE_PASS",
    "REFERENCE_PEER_MATCH_PASS",
    "PAGE1_PASS",
    "PAGE2_PASS",
}
COUNT_LIMITS = {
    "PAGE1_MESSAGES_SEEN": PAGE_SIZE,
    "PAGE1_ENTRIES_CONVERTED": PAGE_SIZE,
    "PAGE1_ENTRIES_NONE": PAGE_SIZE,
    "PAGE2_MESSAGES_SEEN": PAGE_SIZE,
    "PAGE2_ENTRIES_CONVERTED": PAGE_SIZE,
    "PAGE2_ENTRIES_NONE": PAGE_SIZE,
    "MESSAGE_ORDINAL": PAGE_SIZE,
    "CONNECT_CALL_COUNT": 2,
    "IS_USER_AUTHORIZED_CALL_COUNT": 2,
    "ITER_MESSAGES_CALL_COUNT": 2,
    "MESSAGES_SEEN_TOTAL": MAX_MESSAGES,
    "ENTRIES_CONVERTED_TOTAL": MAX_MESSAGES,
    "TELEGRAM_NETWORK_CALLS": 6,
}
ALLOWED_KEYS = {
    REMOTE_BEGIN,
    REMOTE_END,
    "PAGE1_REQUIRED",
    "PAGE1_PASS",
    "PAGE2_REQUIRED",
    "PAGE2_PASS",
    "FAILURE_STAGE",
    "RAW_EXCEPTION_CLASS",
    "MESSAGE_ORDINAL",
    "STAGE_0_ACCOUNT_EXACTLY_ONE",
    "STAGE_0_MANUAL_SELECTED_GROUP_EXACTLY_ONE",
    "INITIAL_STATE",
    "HISTORY_COMPLETE_BEFORE",
    "BACKFILL_CURSOR_PRESENT_BEFORE",
    "SESSION_DECRYPT_PASS",
    "STRING_SESSION_PARSE_PASS",
    "REFERENCE_DECRYPT_PASS",
    "REFERENCE_PARSE_PASS",
    "REFERENCE_PEER_MATCH_PASS",
    *COUNT_LIMITS,
}


class HistoryProbeError(RuntimeError):
    """Sanitized local diagnostic failure."""


def page2_required_before(*, latest: int | None, history_complete: bool, cursor: int | None) -> bool:
    """Mirror the production pre-page-2 condition for an established state."""
    return latest is not None and not history_complete and cursor is not None


def initial_page2_state(entries: list[object], *, has_more: bool, cutoff: object) -> tuple[int | None, bool]:
    """Call the exact production backfill helper without exposing its values."""
    from app.connectors.telegram.mtproto_transport import TelegramMtprotoHistoryPage
    from app.services.telegram_mtproto_history_service import _next_backfill_state

    page = TelegramMtprotoHistoryPage(entries=tuple(entries), has_more=has_more)
    return _next_backfill_state(page, cutoff)


def parse_output(stdout: str, stderr: str, returncode: int) -> dict[str, str]:
    """Strictly validate the parent/child protocol without echoing raw output."""
    if returncode != 0 or stderr:
        raise HistoryProbeError("child execution failed")
    parsed: dict[str, str] = {}
    for line in stdout.splitlines():
        if line in {f"{REMOTE_BEGIN}=true", f"{REMOTE_END}=true"}:
            continue
        if line.count("=") != 1:
            raise HistoryProbeError("malformed child output")
        key, value = line.split("=", 1)
        if key not in ALLOWED_KEYS or key in parsed:
            raise HistoryProbeError("unknown or duplicate child key")
        if key in BOOLEAN_KEYS and value not in {"true", "false"}:
            raise HistoryProbeError("invalid boolean")
        if key in COUNT_LIMITS and (
            re.fullmatch(r"[0-9]+", value) is None or int(value) > COUNT_LIMITS[key]
        ):
            raise HistoryProbeError("invalid bounded count")
        if key == "FAILURE_STAGE" and value not in FAILURE_STAGES:
            raise HistoryProbeError("invalid failure stage")
        if key == "RAW_EXCEPTION_CLASS" and EXCEPTION_CLASS.fullmatch(value) is None:
            raise HistoryProbeError("invalid exception class")
        parsed[key] = value
    if "FAILURE_STAGE" in parsed:
        required = {"RAW_EXCEPTION_CLASS", "MESSAGE_ORDINAL"}
        if not required.issubset(parsed):
            raise HistoryProbeError("failure fields incomplete")
        failure_stage = parsed["FAILURE_STAGE"]
        page1_failure = failure_stage in {
            "STAGE_2_PAGE1_CONNECT",
            "STAGE_2_PAGE1_AUTHORIZED",
            "STAGE_3_PAGE1_ITERATION",
            "STAGE_3_PAGE1_CONVERSION",
        }
        page2_failure = failure_stage in {
            "STAGE_4_PAGE2_CONNECT",
            "STAGE_4_PAGE2_AUTHORIZED",
            "STAGE_5_PAGE2_ITERATION",
            "STAGE_5_PAGE2_CONVERSION",
        }
        if page1_failure and (
            parsed.get("PAGE1_PASS") == "true"
            or "PAGE2_PASS" in parsed
            or "MESSAGES_SEEN_TOTAL" in parsed
            or "ENTRIES_CONVERTED_TOTAL" in parsed
        ):
            raise HistoryProbeError("page1 failure has incompatible success fields")
        if page2_failure and (
            parsed.get("PAGE1_PASS") != "true"
            or parsed.get("PAGE2_REQUIRED") != "true"
            or "PAGE2_PASS" in parsed
            or "MESSAGES_SEEN_TOTAL" in parsed
            or "ENTRIES_CONVERTED_TOTAL" in parsed
        ):
            raise HistoryProbeError("page2 failure has incompatible fields")
        if not page1_failure and not page2_failure:
            raise HistoryProbeError("failure stage is not page-specific")
        return parsed
    for prefix in ("PAGE1", "PAGE2"):
        if parsed.get(f"{prefix}_PASS") == "true":
            seen = int(parsed.get(f"{prefix}_MESSAGES_SEEN", "-1"))
            converted = int(parsed.get(f"{prefix}_ENTRIES_CONVERTED", "-1"))
            none = parsed.get(f"{prefix}_ENTRIES_NONE")
            if seen != converted or none != "0":
                raise HistoryProbeError("inconsistent page success counts")
    if parsed.get("PAGE1_PASS") != "true":
        raise HistoryProbeError("successful output missing page1")
    if parsed.get("PAGE2_REQUIRED") not in {"true", "false"}:
        raise HistoryProbeError("successful output missing page2 decision")
    if parsed.get("PAGE2_REQUIRED") == "true":
        if parsed.get("PAGE2_PASS") != "true":
            raise HistoryProbeError("required page2 missing")
    elif "PAGE2_PASS" in parsed:
        raise HistoryProbeError("page2 result emitted when not required")
    page_counts = {
        "PAGE1_MESSAGES_SEEN": int(parsed.get("PAGE1_MESSAGES_SEEN", "-1")),
        "PAGE1_ENTRIES_CONVERTED": int(parsed.get("PAGE1_ENTRIES_CONVERTED", "-1")),
    }
    if parsed.get("PAGE2_PASS") == "true":
        page_counts.update(
            PAGE2_MESSAGES_SEEN=int(parsed.get("PAGE2_MESSAGES_SEEN", "-1")),
            PAGE2_ENTRIES_CONVERTED=int(parsed.get("PAGE2_ENTRIES_CONVERTED", "-1")),
        )
    total_seen = int(parsed.get("MESSAGES_SEEN_TOTAL", "-1"))
    total_converted = int(parsed.get("ENTRIES_CONVERTED_TOTAL", "-1"))
    if total_seen != page_counts["PAGE1_MESSAGES_SEEN"] + page_counts.get("PAGE2_MESSAGES_SEEN", 0):
        raise HistoryProbeError("total seen does not equal page sums")
    if total_converted != page_counts["PAGE1_ENTRIES_CONVERTED"] + page_counts.get("PAGE2_ENTRIES_CONVERTED", 0):
        raise HistoryProbeError("total converted does not equal page sums")
    if total_seen != total_converted or total_seen > MAX_MESSAGES:
        raise HistoryProbeError("inconsistent total counts")
    return parsed


def _failure_class(stderr: str) -> str:
    text = stderr.lower()
    if any(token in text for token in ("permission denied", "authentication failed", "too many authentication")):
        return "authentication"
    if any(token in text for token in ("host key", "timed out", "connection reset", "no route", "connection refused")):
        return "transport"
    return "unknown"


def build_ssh_argv(known_hosts: str) -> list[str]:
    return [
        "ssh",
        "-p",
        str(EXPECTED_PORT),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "HostKeyAlgorithms=ssh-ed25519",
        "-o",
        "ConnectTimeout=5",
        EXPECTED_TARGET,
        "python3",
        "-",
    ]


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        target = deploy._load_target()
        if (
            target["ssh_target"],
            target["ssh_port"],
            target["host_key_sha256"],
        ) != (EXPECTED_TARGET, EXPECTED_PORT, EXPECTED_PIN):
            raise HistoryProbeError("canonical target mismatch")
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                known = deploy._verified_known_hosts(EXPECTED_TARGET, EXPECTED_PORT, EXPECTED_PIN)
            except (deploy.DeployError, OSError):
                if attempt == MAX_ATTEMPTS:
                    raise HistoryProbeError("host-key verification failed") from None
                continue
            with tempfile.NamedTemporaryFile("w", encoding="utf-8") as hosts:
                hosts.write(known)
                hosts.flush()
                proc = subprocess.run(
                    build_ssh_argv(hosts.name),
                    input=REMOTE_HELPER,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=300,
                )
            if REMOTE_BEGIN in proc.stdout:
                if f"{REMOTE_END}=true" not in proc.stdout:
                    raise HistoryProbeError("remote end marker missing")
                parsed = parse_output(proc.stdout, proc.stderr, proc.returncode)
                for key, value in parsed.items():
                    print(f"{key}={value}")
                return 0
            failure = _failure_class(proc.stderr)
            if failure == "transport" and attempt < MAX_ATTEMPTS:
                continue
            raise HistoryProbeError("SSH failed before remote execution") from None
        raise HistoryProbeError("attempts exhausted")
    except (HistoryProbeError, deploy.DeployError, OSError, subprocess.SubprocessError) as exc:
        print(f"HISTORY_TWO_PAGE_BLOCKED={type(exc).__name__}", file=sys.stderr)
        return 2


REMOTE_HELPER = r'''#!/usr/bin/env python3
import asyncio
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta

REPO = "/opt/secretary"
COMPOSE = ["docker", "compose", "--env-file", "/opt/secretary/.env",
           "-f", "infra/compose.yaml", "-f", "infra/compose.deploy.yaml"]
EXPECTED_RELEASE = "23fa07df213d5a70a6dc1d3c8b32af39228107eb"
PAGE_SIZE = 100
MAX_MESSAGES = 200

def emit(key, value):
    print(f"{key}={value}", flush=True)

def cls(exc):
    value = type(exc).__name__
    return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value) else "OTHER"

def fail(stage, exc, ordinal=0):
    emit("FAILURE_STAGE", stage)
    emit("RAW_EXCEPTION_CLASS", cls(exc))
    emit("MESSAGE_ORDINAL", str(max(0, min(ordinal, PAGE_SIZE))))
    emit("TELEGRAM_NETWORK_CALLS", str(network_calls))
    emit("HISTORY_TWO_PAGE_REMOTE_END", "true")
    raise SystemExit(0)

def run(argv, **kwargs):
    return subprocess.run(argv, text=True, capture_output=True, check=False, **kwargs)

def compose(*args, **kwargs):
    return run(COMPOSE + list(args), **kwargs)

network_calls = 0
connect_calls = 0
authorized_calls = 0
iterator_calls = 0
try:
    emit("HISTORY_TWO_PAGE_REMOTE_BEGIN", "true")
    os.chdir(REPO)
    head = run(["git", "rev-parse", "HEAD"])
    prod = run(["git", "rev-parse", "origin/production"])
    clean = run(["git", "status", "--porcelain"])
    if head.returncode != 0 or head.stdout.strip() != EXPECTED_RELEASE:
        fail("STAGE_0_RELEASE_REF", RuntimeError())
    if prod.returncode != 0 or prod.stdout.strip() != EXPECTED_RELEASE:
        fail("STAGE_0_PRODUCTION_REF", RuntimeError())
    if clean.returncode != 0 or clean.stdout.strip():
        fail("STAGE_0_WORKTREE", RuntimeError())
    config = compose("config", "--format", "json")
    if config.returncode != 0:
        fail("STAGE_1_DB_SESSION", RuntimeError())
    services = json.loads(config.stdout).get("services", {})
    api_env = services.get("api", {}).get("environment", {})
    if isinstance(api_env, list):
        api_env = dict(item.split("=", 1) for item in api_env if "=" in item)
    child_env = os.environ.copy()
    child_env["PGPASSWORD"] = str(api_env.get("POSTGRES_PASSWORD", ""))
    user = str(api_env.get("POSTGRES_USER", "secretary"))
    database = str(api_env.get("POSTGRES_DB", "secretary"))
    for service in ("db", "api", "worker"):
        listing = compose("ps", "-q", service)
        cid = listing.stdout.splitlines()[0].strip() if listing.returncode == 0 and listing.stdout.strip() else ""
        state = run(["docker", "inspect", "-f", "{{.State.Running}}", cid]) if cid else None
        if state is None or state.returncode != 0 or state.stdout.strip() != "true":
            fail("STAGE_1_DB_SESSION", RuntimeError())
    db = compose("ps", "-q", "db").stdout.splitlines()[0].strip()
    health = run(["docker", "inspect", "-f", "{{.State.Health.Status}}", db])
    if health.returncode != 0 or health.stdout.strip() != "healthy":
        fail("STAGE_1_DB_SESSION", RuntimeError())
    revision = run(["docker", "exec", "-e", "PGPASSWORD", "-i", db, "psql", "-h", "127.0.0.1", "-U", user, "-d", database, "-At", "-c", "SELECT version_num FROM alembic_version"], env=child_env)
    if revision.returncode != 0 or revision.stdout.strip() != "0046":
        fail("STAGE_1_DB_SESSION", RuntimeError())

    child = r"""import asyncio
from datetime import UTC, datetime, timedelta

PAGE_SIZE = 100
MAX_MESSAGES = 200

def emit(key, value):
    print(f"{key}={value}", flush=True)

def fail(stage, exc, ordinal=0):
    emit("FAILURE_STAGE", stage)
    name = type(exc).__name__
    emit("RAW_EXCEPTION_CLASS", name if name.isidentifier() else "OTHER")
    emit("MESSAGE_ORDINAL", str(max(0, min(ordinal, PAGE_SIZE))))
    emit("TELEGRAM_NETWORK_CALLS", str(network_calls))
    raise SystemExit(0)

class InvalidHistoryEntry(RuntimeError):
    pass

network_calls = 0
connect_calls = 0
authorized_calls = 0
iterator_calls = 0

try:
    from sqlalchemy import select
    from app.connectors.google.encryption import CredentialEncryption
    from app.connectors.telegram.mtproto_transport import (
        _history_entry_from_message, _input_peer_from_reference,
        validate_provider_peer_reference, TelegramMtprotoHistoryEntry,
        TelegramMtprotoHistoryPage,
    )
    from app.services.telegram_mtproto_history_service import (
        TELEGRAM_MTPROTO_HISTORY_DAYS, _next_backfill_state,
    )
    from app.core.config import settings
    from app.db.models import TelegramMtprotoAccount, TelegramMtprotoChatSelection
    from app.db.session import SessionLocal
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except Exception as exc:
    emit("STAGE_0_ACCOUNT_EXACTLY_ONE", "false")
    emit("STAGE_0_MANUAL_SELECTED_GROUP_EXACTLY_ONE", "false")
    fail("STAGE_1_IMPORTS", exc)

async def run_probe():
    try:
        with SessionLocal() as db:
            accounts = list(db.scalars(select(TelegramMtprotoAccount)))
            selections = list(db.scalars(select(TelegramMtprotoChatSelection).where(TelegramMtprotoChatSelection.manual_selected.is_(True))))
    except Exception as exc:
        emit("STAGE_0_ACCOUNT_EXACTLY_ONE", "false")
        emit("STAGE_0_MANUAL_SELECTED_GROUP_EXACTLY_ONE", "false")
        fail("STAGE_1_DB_SESSION", exc)
    emit("STAGE_0_ACCOUNT_EXACTLY_ONE", str(len(accounts) == 1).lower())
    emit("STAGE_0_MANUAL_SELECTED_GROUP_EXACTLY_ONE", str(len(selections) == 1).lower())
    if len(accounts) != 1:
        fail("STAGE_1_DB_SESSION", RuntimeError())
    if len(selections) != 1:
        fail("STAGE_1_DB_SESSION", RuntimeError())
    account, selection = accounts[0], selections[0]
    latest = selection.history_latest_message_id
    cursor = selection.history_backfill_before_message_id
    complete = bool(selection.history_complete)
    initial = latest is None
    emit("INITIAL_STATE", str(initial).lower())
    emit("HISTORY_COMPLETE_BEFORE", str(complete).lower())
    emit("BACKFILL_CURSOR_PRESENT_BEFORE", str(cursor is not None).lower())
    page2_before = latest is not None and not complete and cursor is not None
    if not initial:
        emit("PAGE2_REQUIRED", str(page2_before).lower())
    encryption = CredentialEncryption(settings.secretary_credential_key)
    try:
        session_value = encryption.decrypt(account.session_encrypted)
        if not session_value:
            raise ValueError()
        emit("SESSION_DECRYPT_PASS", "true")
    except Exception as exc:
        emit("SESSION_DECRYPT_PASS", "false")
        fail("STAGE_1_SESSION_DECRYPT", exc)
    try:
        StringSession(session_value)
        emit("STRING_SESSION_PARSE_PASS", "true")
    except Exception as exc:
        emit("STRING_SESSION_PARSE_PASS", "false")
        fail("STAGE_1_SESSION_DECRYPT", exc)
    try:
        reference_value = encryption.decrypt(selection.provider_peer_reference_encrypted)
        if not reference_value:
            raise ValueError()
        emit("REFERENCE_DECRYPT_PASS", "true")
    except Exception as exc:
        emit("REFERENCE_DECRYPT_PASS", "false")
        fail("STAGE_1_REFERENCE_DECRYPT", exc)
    try:
        _input_peer_from_reference(reference_value)
        emit("REFERENCE_PARSE_PASS", "true")
    except Exception as exc:
        emit("REFERENCE_PARSE_PASS", "false")
        fail("STAGE_1_REFERENCE_PARSE", exc)
    try:
        input_peer = validate_provider_peer_reference(reference_value, expected_peer_id=selection.peer_id)
        emit("REFERENCE_PEER_MATCH_PASS", "true")
    except Exception as exc:
        emit("REFERENCE_PEER_MATCH_PASS", "false")
        fail("STAGE_1_REFERENCE_PEER_MATCH", exc)
    cutoff = selection.history_cutoff_at or datetime.now(UTC) - timedelta(days=TELEGRAM_MTPROTO_HISTORY_DAYS)
    page_results = []
    async def page(number, *, reverse, min_id=None, max_id=None, limit=PAGE_SIZE):
        nonlocal network_calls, connect_calls, authorized_calls, iterator_calls
        stage_connect = "STAGE_2_PAGE1_CONNECT" if number == 1 else "STAGE_4_PAGE2_CONNECT"
        stage_auth = "STAGE_2_PAGE1_AUTHORIZED" if number == 1 else "STAGE_4_PAGE2_AUTHORIZED"
        stage_iter = "STAGE_3_PAGE1_ITERATION" if number == 1 else "STAGE_5_PAGE2_ITERATION"
        stage_convert = "STAGE_3_PAGE1_CONVERSION" if number == 1 else "STAGE_5_PAGE2_CONVERSION"
        client = None
        seen = 0
        converted = []
        try:
            client = TelegramClient(StringSession(session_value), settings.telegram_api_id, settings.telegram_api_hash)
            connect_calls += 1
            network_calls += 1
            try:
                await client.connect()
            except Exception as exc:
                fail(stage_connect, exc)
                return None
            authorized_calls += 1
            network_calls += 1
            try:
                authorized = await client.is_user_authorized()
            except Exception as exc:
                fail(stage_auth, exc)
                return None
            if not authorized:
                fail(stage_auth, RuntimeError("AuthorizationFalse"))
                return None
            iterator_calls += 1
            network_calls += 1
            try:
                iterator = client.iter_messages(input_peer, limit=limit, min_id=min_id, max_id=max_id, reverse=reverse)
                async for message in iterator:
                    if seen >= PAGE_SIZE:
                        break
                    seen += 1
                    try:
                        entry = _history_entry_from_message(message)
                    except Exception as exc:
                        fail(stage_convert, exc, seen)
                        return None
                    if entry is None:
                        fail(stage_convert, InvalidHistoryEntry(), seen)
                        return None
                    converted.append(entry)
            except Exception as exc:
                fail(stage_iter, exc, min(seen + 1, PAGE_SIZE))
                return None
            emit(f"PAGE{number}_PASS", "true")
            emit(f"PAGE{number}_MESSAGES_SEEN", str(seen))
            emit(f"PAGE{number}_ENTRIES_CONVERTED", str(len(converted)))
            emit(f"PAGE{number}_ENTRIES_NONE", "0")
            return converted
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    first = await page(1, reverse=False if initial else True, min_id=None if initial else latest)
    if first is None:
        return
    total_seen = len(first)
    total_converted = len(first)
    page2_cursor = cursor
    page2_required = page2_before
    if initial:
        page_obj = TelegramMtprotoHistoryPage(entries=tuple(first), has_more=len(first) >= PAGE_SIZE)
        page2_cursor, derived_complete = _next_backfill_state(page_obj, cutoff)
        page2_required = not derived_complete and page2_cursor is not None
        emit("PAGE2_REQUIRED", str(page2_required).lower())
    if page2_required:
        remaining = MAX_MESSAGES - total_seen
        if remaining <= 0 or page2_cursor is None:
            page2_required = False
            emit("PAGE2_REQUIRED", "false")
        else:
            second = await page(2, reverse=False, max_id=page2_cursor, limit=min(PAGE_SIZE, remaining))
            if second is None:
                return
            total_seen += len(second)
            total_converted += len(second)
    emit("MESSAGES_SEEN_TOTAL", str(total_seen))
    emit("ENTRIES_CONVERTED_TOTAL", str(total_converted))
    emit("CONNECT_CALL_COUNT", str(connect_calls))
    emit("IS_USER_AUTHORIZED_CALL_COUNT", str(authorized_calls))
    emit("ITER_MESSAGES_CALL_COUNT", str(iterator_calls))
    emit("TELEGRAM_NETWORK_CALLS", str(network_calls))

asyncio.run(run_probe())
emit("HISTORY_TWO_PAGE_REMOTE_END", "true")
"""
    result = run(COMPOSE + ["exec", "-T", "api", "python3", "-"], input=child)
    if result.returncode != 0 or result.stderr:
        fail("STAGE_1_DB_SESSION", RuntimeError())
    print(result.stdout, end="")
    emit("HISTORY_TWO_PAGE_REMOTE_END", "true")
except SystemExit:
    pass
except Exception as exc:
    fail("STAGE_1_DB_SESSION", exc)
'''


if __name__ == "__main__":
    raise SystemExit(main())
