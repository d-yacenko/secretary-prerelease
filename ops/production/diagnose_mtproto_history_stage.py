"""Deterministic one-shot MTProto history-stage probe.

This module is intentionally separate from the production application path.  It
is a read-only diagnostic harness and is not a deployment or sync entrypoint.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ops.production import diagnose_mtproto_auth_readonly as auth_diagnostic

EXPECTED_RELEASE = auth_diagnostic.EXPECTED_RELEASE
EXPECTED_TARGET = auth_diagnostic.EXPECTED_TARGET
EXPECTED_PORT = auth_diagnostic.EXPECTED_PORT
EXPECTED_PIN = auth_diagnostic.EXPECTED_PIN
MAX_ATTEMPTS = auth_diagnostic.MAX_ATTEMPTS
REMOTE_BEGIN = "HISTORY_STAGE_REMOTE_BEGIN"
REMOTE_END = "HISTORY_STAGE_REMOTE_END"


class HistoryStageError(RuntimeError):
    """A sanitized local harness failure."""


def _run_once() -> int:
    target = auth_diagnostic.deploy._load_target()
    if (
        target["ssh_target"] != EXPECTED_TARGET
        or target["ssh_port"] != EXPECTED_PORT
        or target["host_key_sha256"] != EXPECTED_PIN
    ):
        raise HistoryStageError("canonical SSH contract mismatch")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            entry = auth_diagnostic._verified_entry(EXPECTED_TARGET, EXPECTED_PORT, EXPECTED_PIN)
        except (auth_diagnostic.DiagnosticError, auth_diagnostic.deploy.DeployError, OSError):
            print(f"ATTEMPT={attempt} PIN_VERIFIED=no HOST_KEY=not-run AUTH=not-run REMOTE=not-run")
            if attempt == MAX_ATTEMPTS:
                raise HistoryStageError("pin verification failed") from None
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
                timeout=180,
            )

        remote_started = REMOTE_BEGIN in result.stdout
        if result.returncode == 0 and REMOTE_END in result.stdout:
            print(f"ATTEMPT={attempt} PIN_VERIFIED=yes HOST_KEY=pass AUTH=pass REMOTE=pass")
            print(result.stdout, end="")
            return 0
        if remote_started:
            print(f"ATTEMPT={attempt} PIN_VERIFIED=yes HOST_KEY=pass AUTH=pass REMOTE=failed")
            print(result.stdout, end="")
            raise HistoryStageError("remote history stage failed") from None

        failure = auth_diagnostic._failure_class(result.stderr)
        if failure == "authentication":
            print(f"ATTEMPT={attempt} PIN_VERIFIED=yes HOST_KEY=pass AUTH=failed REMOTE=not-run")
            raise HistoryStageError("SSH authentication failed") from None
        if failure == "transport":
            print(f"ATTEMPT={attempt} PIN_VERIFIED=yes HOST_KEY=failed AUTH=not-run REMOTE=not-run")
            if attempt == MAX_ATTEMPTS:
                raise HistoryStageError("SSH transport failed") from None
            continue
        print(f"ATTEMPT={attempt} PIN_VERIFIED=yes HOST_KEY=unknown AUTH=unknown REMOTE=not-run")
        raise HistoryStageError("SSH failed before remote execution") from None

    raise HistoryStageError("history stage attempts exhausted")


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        auth_diagnostic._require_clean_canonical_checkout()
        return _run_once()
    except (HistoryStageError, auth_diagnostic.deploy.DeployError, OSError, subprocess.SubprocessError) as exc:
        print(f"HISTORY_STAGE_BLOCKED={type(exc).__name__}", file=sys.stderr)
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

def emit(key, value):
    print(f"{key}={value}", flush=True)

def run(argv, **kwargs):
    return subprocess.run(argv, text=True, capture_output=True, check=False, **kwargs)

def compose(*args, **kwargs):
    return run(COMPOSE + list(args), **kwargs)

def stop(stage, exc):
    emit("FAILURE_STAGE", stage)
    emit("RAW_EXCEPTION_CLASS", type(exc).__name__)
    raise SystemExit(0)

try:
    emit("HISTORY_STAGE_REMOTE_BEGIN", "true")
    os.chdir(REPO)

    head = run(["git", "rev-parse", "HEAD"])
    production = run(["git", "rev-parse", "origin/production"])
    clean = run(["git", "status", "--porcelain"])
    emit("RELEASE_REF_MATCH", "true" if head.returncode == 0 and head.stdout.strip() == EXPECTED_RELEASE else "false")
    emit("PRODUCTION_REF_MATCH", "true" if production.returncode == 0 and production.stdout.strip() == EXPECTED_RELEASE else "false")
    emit("PRODUCTION_WORKTREE_CLEAN", "true" if clean.returncode == 0 and not clean.stdout.strip() else "false")

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

    db_query = ["docker", "exec", "-e", "PGPASSWORD", "-i", "", "psql"]
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

    revision = run(["docker", "exec", "-e", "PGPASSWORD", "-i", db, "psql", "-h", "127.0.0.1",
                    "-U", db_user, "-d", db_name, "-At", "-c", "SELECT version_num FROM alembic_version"], env=child)
    if revision.returncode != 0 or revision.stdout.strip() != "0046":
        stop("STAGE_0_ALEMBIC", RuntimeError())

    probe = r"""from sqlalchemy import select
from app.connectors.google.encryption import CredentialEncryption
from app.connectors.telegram.mtproto_transport import _input_peer_from_reference, validate_provider_peer_reference
from app.core.config import settings
from app.db.models import TelegramMtprotoAccount, TelegramMtprotoChatSelection
from app.db.session import SessionLocal
from telethon import TelegramClient
from telethon.sessions import StringSession

async def run_probe():
    with SessionLocal() as session:
        accounts = list(session.scalars(select(TelegramMtprotoAccount)))
        selections = list(session.scalars(select(TelegramMtprotoChatSelection).where(TelegramMtprotoChatSelection.manual_selected.is_(True))))
        print("STAGE_0_ACCOUNT_EXACTLY_ONE=" + ("true" if len(accounts) == 1 else "false"))
        print("STAGE_0_MANUAL_SELECTED_GROUP_EXACTLY_ONE=" + ("true" if len(selections) == 1 else "false"))
        if len(accounts) != 1:
            print("FAILURE_STAGE=STAGE_0_ACCOUNT_CARDINALITY")
            print("RAW_EXCEPTION_CLASS=CardinalityError")
            return
        if len(selections) != 1:
            print("FAILURE_STAGE=STAGE_0_SELECTION_CARDINALITY")
            print("RAW_EXCEPTION_CLASS=CardinalityError")
            return

        account = accounts[0]
        selection = selections[0]
        encryption = CredentialEncryption(settings.secretary_credential_key)
        session_value = None
        reference_value = None
        try:
            session_value = encryption.decrypt(account.session_encrypted)
            if not session_value:
                raise ValueError()
            print("SESSION_DECRYPT_PASS=true")
        except Exception as exc:
            print("SESSION_DECRYPT_PASS=false")
            print("FAILURE_STAGE=STAGE_1_SESSION_DECRYPT")
            print("RAW_EXCEPTION_CLASS=" + type(exc).__name__)
            return
        try:
            StringSession(session_value)
            print("STRING_SESSION_PARSE_PASS=true")
        except Exception as exc:
            print("STRING_SESSION_PARSE_PASS=false")
            print("FAILURE_STAGE=STAGE_1_STRING_SESSION_PARSE")
            print("RAW_EXCEPTION_CLASS=" + type(exc).__name__)
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
            return
        try:
            _input_peer_from_reference(reference_value)
            print("REFERENCE_PARSE_PASS=true")
        except Exception as exc:
            print("REFERENCE_PARSE_PASS=false")
            print("FAILURE_STAGE=STAGE_1_REFERENCE_PARSE")
            print("RAW_EXCEPTION_CLASS=" + type(exc).__name__)
            return
        try:
            input_peer = validate_provider_peer_reference(reference_value, expected_peer_id=selection.peer_id)
            print("REFERENCE_PEER_MATCH_PASS=true")
        except Exception as exc:
            print("REFERENCE_PEER_MATCH_PASS=false")
            print("FAILURE_STAGE=STAGE_1_REFERENCE_PEER_MATCH")
            print("RAW_EXCEPTION_CLASS=" + type(exc).__name__)
            return
        try:
            client = TelegramClient(StringSession(session_value), settings.telegram_api_id, settings.telegram_api_hash)
            print("TELEGRAM_CLIENT_CONSTRUCT_PASS=true")
        except Exception as exc:
            print("TELEGRAM_CLIENT_CONSTRUCT_PASS=false")
            print("FAILURE_STAGE=STAGE_1_CLIENT_CONSTRUCT")
            print("RAW_EXCEPTION_CLASS=" + type(exc).__name__)
            return

        connect_calls = 0
        authorized_calls = 0
        iter_calls = 0
        try:
            connect_calls += 1
            await client.connect()
            print("CONNECT_PASS=true")
            authorized_calls += 1
            authorized = await client.is_user_authorized()
            print("IS_USER_AUTHORIZED=" + ("true" if authorized else "false"))
            if not authorized:
                print("FAILURE_STAGE=STAGE_2_AUTHORIZED")
                print("RAW_EXCEPTION_CLASS=AuthorizationFalse")
                return
            iter_calls += 1
            print("ITER_MESSAGES_STARTED=true")
            async for _ in client.iter_messages(input_peer, limit=1, reverse=False):
                break
            print("ITER_MESSAGES_ONE_ITEM_OR_EMPTY_PASS=true")
        except Exception as exc:
            print("FAILURE_STAGE=" + ("STAGE_2_CONNECT" if connect_calls == 1 and authorized_calls == 0 else "STAGE_2_AUTHORIZED" if authorized_calls == 1 and iter_calls == 0 else "STAGE_3_ITER_MESSAGES"))
            print("RAW_EXCEPTION_CLASS=" + type(exc).__name__)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        print("CONNECT_CALL_COUNT=" + str(connect_calls))
        print("IS_USER_AUTHORIZED_CALL_COUNT=" + str(authorized_calls))
        print("ITER_MESSAGES_CALL_COUNT=" + str(iter_calls))
        print("TELEGRAM_NETWORK_CALLS=" + str(connect_calls + authorized_calls + iter_calls))

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_probe())
"""
    result = run(COMPOSE + ["exec", "-T", "api", "python3", "-"], input=probe)
    if result.returncode != 0:
        stop("STAGE_1_RUNTIME", RuntimeError())
    sys.stdout.write(result.stdout)
    emit("SESSION_OR_REFERENCE_PRINTED", "false")
    emit("PRODUCTION_MUTATION", "false")
    emit("HISTORY_STAGE_REMOTE_END", "true")
except SystemExit:
    pass
except Exception as exc:
    stop("SANITIZED_HELPER", exc)
'''


if __name__ == "__main__":
    raise SystemExit(main())
