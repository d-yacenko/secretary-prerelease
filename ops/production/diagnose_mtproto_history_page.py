"""Deterministic, read-only first-page MTProto conversion probe."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ops.production import diagnose_mtproto_auth_readonly as auth_diagnostic
from ops.production import diagnose_mtproto_history_stage as history_stage_diagnostic

EXPECTED_RELEASE = auth_diagnostic.EXPECTED_RELEASE
EXPECTED_TARGET = auth_diagnostic.EXPECTED_TARGET
EXPECTED_PORT = auth_diagnostic.EXPECTED_PORT
EXPECTED_PIN = auth_diagnostic.EXPECTED_PIN
MAX_ATTEMPTS = auth_diagnostic.MAX_ATTEMPTS
PAGE_SIZE = 100
REMOTE_BEGIN = "HISTORY_PAGE_REMOTE_BEGIN"
REMOTE_END = "HISTORY_PAGE_REMOTE_END"

PAGE_KEYS = {
    *history_stage_diagnostic.ALLOWED_KEYS,
    "FIRST_PAGE_PASS",
    "MESSAGES_SEEN",
    "ENTRIES_CONVERTED",
    "ENTRIES_NONE",
    "MESSAGE_ORDINAL",
}
PAGE_BOOLEAN_KEYS = {
    *history_stage_diagnostic.BOOLEAN_KEYS,
    "FIRST_PAGE_PASS",
}
PAGE_COUNT_LIMITS = {
    **history_stage_diagnostic.COUNT_LIMITS,
    "MESSAGE_ORDINAL": PAGE_SIZE,
    "MESSAGES_SEEN": PAGE_SIZE,
    "ENTRIES_CONVERTED": PAGE_SIZE,
    "ENTRIES_NONE": PAGE_SIZE,
}
PAGE_FAILURE_STAGES = {
    *history_stage_diagnostic.FAILURE_STAGES,
    "STAGE_1_IMPORTS",
    "STAGE_1_DB_SESSION",
    "STAGE_3_ITERATION",
    "STAGE_3_CONVERSION",
}


class HistoryPageError(RuntimeError):
    """A sanitized local harness failure."""


def parse_page_output(stdout: str, stderr: str, returncode: int) -> dict[str, str]:
    """Validate the child protocol and return only allowlisted fields."""
    if stderr or returncode != 0:
        raise HistoryPageError("child execution failed")
    parsed: dict[str, str] = {}
    for line in stdout.splitlines():
        if line in {f"{REMOTE_BEGIN}=true", f"{REMOTE_END}=true"}:
            continue
        if line.count("=") != 1:
            raise HistoryPageError("invalid child output")
        key, value = line.split("=", 1)
        if key not in PAGE_KEYS or key in parsed:
            raise HistoryPageError("invalid child output")
        if key in PAGE_BOOLEAN_KEYS and value not in {"true", "false"}:
            raise HistoryPageError("invalid child output")
        if key == "FAILURE_STAGE" and value not in PAGE_FAILURE_STAGES:
            raise HistoryPageError("invalid child output")
        if key == "RAW_EXCEPTION_CLASS" and history_stage_diagnostic.EXCEPTION_CLASS.fullmatch(value) is None:
            raise HistoryPageError("invalid child output")
        if key in PAGE_COUNT_LIMITS and (
            re.fullmatch(r"[0-9]+", value) is None or int(value) > PAGE_COUNT_LIMITS[key]
        ):
            raise HistoryPageError("invalid child output")
        parsed[key] = value
    if "FAILURE_STAGE" in parsed:
        if "RAW_EXCEPTION_CLASS" not in parsed or "MESSAGE_ORDINAL" not in parsed:
            raise HistoryPageError("failure missing ordinal/class")
        if "FIRST_PAGE_PASS" in parsed:
            raise HistoryPageError("failed page cannot pass")
    if parsed.get("FIRST_PAGE_PASS") == "true":
        required = {"ENTRIES_NONE", "MESSAGES_SEEN", "ENTRIES_CONVERTED"}
        if not required.issubset(parsed) or "FAILURE_STAGE" in parsed:
            raise HistoryPageError("incomplete success")
        if parsed["ENTRIES_NONE"] != "0":
            raise HistoryPageError("successful page contains empty entries")
        if parsed["MESSAGES_SEEN"] != parsed["ENTRIES_CONVERTED"]:
            raise HistoryPageError("success counts diverge")
    return parsed


def _run_once() -> int:
    target = auth_diagnostic.deploy._load_target()
    if (
        target["ssh_target"] != EXPECTED_TARGET
        or target["ssh_port"] != EXPECTED_PORT
        or target["host_key_sha256"] != EXPECTED_PIN
    ):
        raise HistoryPageError("canonical SSH contract mismatch")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            entry = auth_diagnostic._verified_entry(EXPECTED_TARGET, EXPECTED_PORT, EXPECTED_PIN)
        except (auth_diagnostic.DiagnosticError, auth_diagnostic.deploy.DeployError, OSError):
            print(f"ATTEMPT={attempt} PIN_VERIFIED=no HOST_KEY=not-run AUTH=not-run REMOTE=not-run")
            if attempt == MAX_ATTEMPTS:
                raise HistoryPageError("pin verification failed") from None
            continue
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as known_hosts:
            known_hosts.write(entry)
            known_hosts.flush()
            argv = auth_diagnostic.build_ssh_argv(
                EXPECTED_TARGET, EXPECTED_PORT, known_hosts.name
            )
            result = subprocess.run(
                argv,
                input=REMOTE_HELPER,
                text=True,
                capture_output=True,
                check=False,
                timeout=240,
            )
        remote_started = REMOTE_BEGIN in result.stdout
        if remote_started:
            if f"{REMOTE_END}=true" not in result.stdout:
                print(f"ATTEMPT={attempt} PIN_VERIFIED=yes HOST_KEY=pass AUTH=pass REMOTE=failed")
                print("FAILURE_STAGE=OUTPUT_ALLOWLIST")
                print("MESSAGE_ORDINAL=0")
                print("TELEGRAM_NETWORK_CALLS=0")
                return 2
            try:
                parsed = parse_page_output(result.stdout, result.stderr, result.returncode)
            except HistoryPageError:
                print(f"ATTEMPT={attempt} PIN_VERIFIED=yes HOST_KEY=pass AUTH=pass REMOTE=failed")
                print("FAILURE_STAGE=OUTPUT_ALLOWLIST")
                print("MESSAGE_ORDINAL=0")
                print("TELEGRAM_NETWORK_CALLS=0")
                return 2
            print(f"ATTEMPT={attempt} PIN_VERIFIED=yes HOST_KEY=pass AUTH=pass REMOTE=pass")
            for key, value in parsed.items():
                print(f"{key}={value}")
            return 0
        failure = auth_diagnostic._failure_class(result.stderr)
        if failure == "authentication":
            print(f"ATTEMPT={attempt} PIN_VERIFIED=yes HOST_KEY=pass AUTH=failed REMOTE=not-run")
            raise HistoryPageError("SSH authentication failed") from None
        if failure == "transport":
            print(f"ATTEMPT={attempt} PIN_VERIFIED=yes HOST_KEY=failed AUTH=not-run REMOTE=not-run")
            if attempt == MAX_ATTEMPTS:
                raise HistoryPageError("SSH transport failed") from None
            continue
        print(f"ATTEMPT={attempt} PIN_VERIFIED=yes HOST_KEY=unknown AUTH=unknown REMOTE=not-run")
        raise HistoryPageError("SSH failed before remote execution") from None
    raise HistoryPageError("attempts exhausted")


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        auth_diagnostic._require_clean_canonical_checkout()
        return _run_once()
    except (HistoryPageError, auth_diagnostic.deploy.DeployError, OSError, subprocess.SubprocessError) as exc:
        print(f"HISTORY_PAGE_BLOCKED={type(exc).__name__}", file=sys.stderr)
        return 2


REMOTE_HELPER = r'''#!/usr/bin/env python3
import json
import os
import subprocess
import sys

REPO = "/opt/secretary"
COMPOSE = ["docker", "compose", "--env-file", "/opt/secretary/.env",
           "-f", "infra/compose.yaml", "-f", "infra/compose.deploy.yaml"]
EXPECTED_RELEASE = "8091736337689b68b4510126e74d9e409397f696"
PAGE_SIZE = 100

def emit(key, value):
    print(f"{key}={value}", flush=True)

def run(argv, **kwargs):
    return subprocess.run(argv, text=True, capture_output=True, check=False, **kwargs)

def compose(*args, **kwargs):
    return run(COMPOSE + list(args), **kwargs)

def stop(stage, exc):
    emit("FAILURE_STAGE", stage)
    emit("RAW_EXCEPTION_CLASS", type(exc).__name__)
    emit("MESSAGE_ORDINAL", "0")
    emit("TELEGRAM_NETWORK_CALLS", "0")
    emit("HISTORY_PAGE_REMOTE_END", "true")
    raise SystemExit(0)

try:
    emit("HISTORY_PAGE_REMOTE_BEGIN", "true")
    os.chdir(REPO)
    head = run(["git", "rev-parse", "HEAD"])
    production = run(["git", "rev-parse", "origin/production"])
    clean = run(["git", "status", "--porcelain"])
    if head.returncode != 0 or head.stdout.strip() != EXPECTED_RELEASE:
        stop("STAGE_0_RELEASE_REF", RuntimeError())
    if production.returncode != 0 or production.stdout.strip() != EXPECTED_RELEASE:
        stop("STAGE_0_PRODUCTION_REF", RuntimeError())
    if clean.returncode != 0 or clean.stdout.strip():
        stop("STAGE_0_WORKTREE", RuntimeError())

    config = compose("config", "--format", "json")
    if config.returncode != 0:
        stop("STAGE_0_CONFIG", RuntimeError())
    services = json.loads(config.stdout).get("services", {})
    api_env = services.get("api", {}).get("environment", {})
    if isinstance(api_env, list):
        api_env = dict(item.split("=", 1) for item in api_env if "=" in item)
    db_user = str(api_env.get("POSTGRES_USER", "secretary"))
    db_name = str(api_env.get("POSTGRES_DB", "secretary"))
    password = str(api_env.get("POSTGRES_PASSWORD", ""))
    child = os.environ.copy()
    child["PGPASSWORD"] = password
    db_listing = compose("ps", "-q", "db")
    if db_listing.returncode != 0 or not db_listing.stdout.strip():
        stop("STAGE_0_CONTAINERS", RuntimeError())
    db = db_listing.stdout.splitlines()[0].strip()
    for service in ("db", "api", "worker"):
        listing = compose("ps", "-q", service)
        cid = listing.stdout.splitlines()[0].strip() if listing.returncode == 0 and listing.stdout.strip() else ""
        state = run(["docker", "inspect", "-f", "{{.State.Running}}", cid]) if cid else None
        if state is None or state.returncode != 0 or state.stdout.strip() != "true":
            stop("STAGE_0_CONTAINERS", RuntimeError())
    health = run(["docker", "inspect", "-f", "{{.State.Health.Status}}", db])
    if health.returncode != 0 or health.stdout.strip() != "healthy":
        stop("STAGE_0_CONTAINERS", RuntimeError())
    revision = run(["docker", "exec", "-e", "PGPASSWORD", "-i", db, "psql", "-h", "127.0.0.1", "-U", db_user, "-d", db_name, "-At", "-c", "SELECT version_num FROM alembic_version"], env=child)
    if revision.returncode != 0 or revision.stdout.strip() != "0046":
        stop("STAGE_0_ALEMBIC", RuntimeError())

    probe = r"""import asyncio

PAGE_SIZE = 100

def emit(key, value):
    print(f"{key}={value}", flush=True)

def emit_failure(stage, exc):
    emit("FAILURE_STAGE", stage)
    emit("RAW_EXCEPTION_CLASS", type(exc).__name__)
    emit("MESSAGE_ORDINAL", "0")
    emit("TELEGRAM_NETWORK_CALLS", "0")

try:
    from sqlalchemy import select
    from app.connectors.telegram.mtproto_transport import _history_entry_from_message, _input_peer_from_reference, validate_provider_peer_reference
    from app.connectors.google.encryption import CredentialEncryption
    from app.core.config import settings
    from app.db.models import TelegramMtprotoAccount, TelegramMtprotoChatSelection
    from app.db.session import SessionLocal
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except Exception as exc:
    emit_failure("STAGE_1_IMPORTS", exc)
    raise SystemExit(0)

async def run_probe():
    try:
        with SessionLocal() as session:
            accounts = list(session.scalars(select(TelegramMtprotoAccount)))
            selections = list(session.scalars(select(TelegramMtprotoChatSelection).where(TelegramMtprotoChatSelection.manual_selected.is_(True))))
    except Exception as exc:
        emit_failure("STAGE_1_DB_SESSION", exc)
        return

    async def run_after_db_session():
        print("STAGE_0_ACCOUNT_EXACTLY_ONE=" + ("true" if len(accounts) == 1 else "false"))
        print("STAGE_0_MANUAL_SELECTED_GROUP_EXACTLY_ONE=" + ("true" if len(selections) == 1 else "false"))
        if len(accounts) != 1:
            print("FAILURE_STAGE=STAGE_0_ACCOUNT_CARDINALITY")
            print("RAW_EXCEPTION_CLASS=CardinalityError")
            print("MESSAGE_ORDINAL=0")
            print("TELEGRAM_NETWORK_CALLS=0")
            return
        if len(selections) != 1:
            print("FAILURE_STAGE=STAGE_0_SELECTION_CARDINALITY")
            print("RAW_EXCEPTION_CLASS=CardinalityError")
            print("MESSAGE_ORDINAL=0")
            print("TELEGRAM_NETWORK_CALLS=0")
            return
        account = accounts[0]
        selection = selections[0]
        encryption = CredentialEncryption(settings.secretary_credential_key)
        try:
            session_value = encryption.decrypt(account.session_encrypted)
            if not session_value:
                raise ValueError()
            print("SESSION_DECRYPT_PASS=true")
        except Exception as exc:
            print("SESSION_DECRYPT_PASS=false")
            print("FAILURE_STAGE=STAGE_1_SESSION_DECRYPT")
            print("RAW_EXCEPTION_CLASS=" + type(exc).__name__)
            print("MESSAGE_ORDINAL=0")
            return
        try:
            StringSession(session_value)
            print("STRING_SESSION_PARSE_PASS=true")
        except Exception as exc:
            print("STRING_SESSION_PARSE_PASS=false")
            print("FAILURE_STAGE=STAGE_1_STRING_SESSION_PARSE")
            print("RAW_EXCEPTION_CLASS=" + type(exc).__name__)
            print("MESSAGE_ORDINAL=0")
            return
        try:
            reference_value = encryption.decrypt(selection.provider_peer_reference_encrypted)
            if not reference_value:
                raise ValueError()
            print("REFERENCE_DECRYPT_PASS=true")
        except Exception as exc:
            print("REFERENCE_DECRYPT_PASS=false")
            print("FAILURE_STAGE=STAGE_1_REFERENCE_DECRYPT")
            print("RAW_EXCEPTION_CLASS=" + type(exc).__name__)
            print("MESSAGE_ORDINAL=0")
            return
        try:
            _input_peer_from_reference(reference_value)
            print("REFERENCE_PARSE_PASS=true")
        except Exception as exc:
            print("REFERENCE_PARSE_PASS=false")
            print("FAILURE_STAGE=STAGE_1_REFERENCE_PARSE")
            print("RAW_EXCEPTION_CLASS=" + type(exc).__name__)
            print("MESSAGE_ORDINAL=0")
            return
        try:
            input_peer = validate_provider_peer_reference(reference_value, expected_peer_id=selection.peer_id)
            print("REFERENCE_PEER_MATCH_PASS=true")
        except Exception as exc:
            print("REFERENCE_PEER_MATCH_PASS=false")
            print("FAILURE_STAGE=STAGE_1_REFERENCE_PEER_MATCH")
            print("RAW_EXCEPTION_CLASS=" + type(exc).__name__)
            print("MESSAGE_ORDINAL=0")
            return
        try:
            client = TelegramClient(StringSession(session_value), settings.telegram_api_id, settings.telegram_api_hash)
            print("TELEGRAM_CLIENT_CONSTRUCT_PASS=true")
        except Exception as exc:
            print("TELEGRAM_CLIENT_CONSTRUCT_PASS=false")
            print("FAILURE_STAGE=STAGE_1_CLIENT_CONSTRUCT")
            print("RAW_EXCEPTION_CLASS=" + type(exc).__name__)
            print("MESSAGE_ORDINAL=0")
            return

        connect_calls = 0
        authorized_calls = 0
        iterator_calls = 0
        messages_seen = 0
        converted = 0
        failure_stage = None
        failure_class = None
        failure_ordinal = 0
        try:
            connect_calls = 1
            try:
                await client.connect()
            except Exception as exc:
                failure_stage = "STAGE_2_CONNECT"
                failure_class = type(exc).__name__
            else:
                print("CONNECT_PASS=true")

                authorized_calls = 1
                try:
                    authorized = await client.is_user_authorized()
                except Exception as exc:
                    failure_stage = "STAGE_2_AUTHORIZED"
                    failure_class = type(exc).__name__
                else:
                    print("IS_USER_AUTHORIZED=" + ("true" if authorized else "false"))
                    if not authorized:
                        failure_stage = "STAGE_2_AUTHORIZED"
                        failure_class = "AuthorizationFalse"
                    else:
                        iterator_calls = 1
                        print("ITER_MESSAGES_STARTED=true")
                        try:
                            async for message in client.iter_messages(
                                input_peer, limit=PAGE_SIZE, reverse=False
                            ):
                                if messages_seen >= PAGE_SIZE:
                                    break
                                messages_seen += 1
                                try:
                                    entry = _history_entry_from_message(message)
                                except Exception as exc:
                                    failure_stage = "STAGE_3_CONVERSION"
                                    failure_class = type(exc).__name__
                                    failure_ordinal = messages_seen
                                    break
                                if entry is None:
                                    failure_stage = "STAGE_3_CONVERSION"
                                    failure_class = "InvalidHistoryEntry"
                                    failure_ordinal = messages_seen
                                    break
                                converted += 1
                        except Exception as exc:
                            failure_stage = "STAGE_3_ITERATION"
                            failure_class = type(exc).__name__
                            failure_ordinal = min(messages_seen + 1, PAGE_SIZE)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        if failure_stage is not None:
            print("FAILURE_STAGE=" + failure_stage)
            print("RAW_EXCEPTION_CLASS=" + failure_class)
            print("MESSAGE_ORDINAL=" + str(failure_ordinal))
        else:
            print("ITER_MESSAGES_ONE_ITEM_OR_EMPTY_PASS=true")
            print("FIRST_PAGE_PASS=true")
            print("MESSAGES_SEEN=" + str(messages_seen))
            print("ENTRIES_CONVERTED=" + str(converted))
            print("ENTRIES_NONE=0")
        print("CONNECT_CALL_COUNT=" + str(connect_calls))
        print("IS_USER_AUTHORIZED_CALL_COUNT=" + str(authorized_calls))
        print("ITER_MESSAGES_CALL_COUNT=" + str(iterator_calls))
        print("TELEGRAM_NETWORK_CALLS=" + str(connect_calls + authorized_calls + iterator_calls))

    await run_after_db_session()

if __name__ == "__main__":
    asyncio.run(run_probe())
"""
    result = run(COMPOSE + ["exec", "-T", "api", "python3", "-"], input=probe)
    if result.returncode != 0 or result.stderr:
        stop("STAGE_1_RUNTIME", RuntimeError())
    print(result.stdout, end="")
    emit("HISTORY_PAGE_REMOTE_END", "true")
except SystemExit:
    pass
except Exception as exc:
    stop("SANITIZED_HELPER", exc)
'''


if __name__ == "__main__":
    raise SystemExit(main())
