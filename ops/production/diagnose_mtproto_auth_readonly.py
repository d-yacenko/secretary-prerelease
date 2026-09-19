"""Deterministic, read-only production MTProto diagnosis over one SSH session."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ops.production import deploy

EXPECTED_RELEASE = "8091736337689b68b4510126e74d9e409397f696"
EXPECTED_ALEMBIC = "0046"
EXPECTED_TARGET = "root@web-itx.duckdns.org"
EXPECTED_PORT = 22
EXPECTED_PIN = "SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs"
MAX_ATTEMPTS = 3
REMOTE_BEGIN = "REMOTE_DIAGNOSTIC_BEGIN"
REMOTE_END = "REMOTE_DIAGNOSTIC_END"


class DiagnosticError(RuntimeError):
    """A local fail-closed diagnostic error."""


def _verified_entry(target: str, port: int, pin: str) -> str:
    entry = deploy._verified_known_hosts(target, port, pin)
    if not entry.strip():
        raise DiagnosticError("empty verified known_hosts entry")
    fingerprints = {
        deploy._fingerprint_for_line(line)
        for line in entry.splitlines()
        if line and not line.startswith("#")
    }
    if pin not in fingerprints:
        raise DiagnosticError("verified known_hosts entry does not match pin")
    return entry


def build_ssh_argv(target: str, port: int, known_hosts_path: str) -> list[str]:
    """Build the complete direct argv; no shell or inherited known_hosts is used."""
    return [
        "ssh",
        "-p",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts_path}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "HostKeyAlgorithms=ssh-ed25519",
        "-o",
        "ConnectTimeout=5",
        target,
        "python3",
        "-",
    ]


def _failure_class(stderr: str) -> str:
    text = stderr.lower()
    if any(token in text for token in ("permission denied", "authentication", "too many authentication")):
        return "authentication"
    if any(
        token in text
        for token in (
            "host key verification failed",
            "no matching host key",
            "connection timed out",
            "connection refused",
            "connection reset",
            "could not resolve hostname",
            "no route to host",
            "kex_exchange_identification",
        )
    ):
        return "transport"
    return "unknown"


def _attempt_result(number: int, pin: bool, host_key: str, auth: str, remote: str) -> None:
    print(
        f"ATTEMPT={number} PIN_VERIFIED={'yes' if pin else 'no'} "
        f"HOST_KEY={host_key} AUTH={auth} REMOTE_EXECUTION={remote}"
    )


def _require_clean_canonical_checkout() -> None:
    root = deploy._run_local(["git", "-C", str(deploy.REPOSITORY_ROOT), "rev-parse", "--show-toplevel"])
    if Path(root).resolve() != deploy.REPOSITORY_ROOT.resolve():
        raise DiagnosticError("diagnostic is not running from the canonical repository root")
    origin = deploy._run_local(["git", "-C", str(deploy.REPOSITORY_ROOT), "remote", "get-url", "origin"])
    if origin != deploy.CANONICAL_ORIGIN:
        raise DiagnosticError("diagnostic checkout has the wrong Git origin")
    status = deploy._run_local(["git", "-C", str(deploy.REPOSITORY_ROOT), "status", "--porcelain"])
    if status:
        raise DiagnosticError("diagnostic checkout is not clean")


def run_diagnostic() -> int:
    target_data = deploy._load_target()
    if target_data["ssh_target"] != EXPECTED_TARGET or target_data["ssh_port"] != EXPECTED_PORT:
        raise DiagnosticError("canonical target mismatch")
    if target_data["host_key_sha256"] != EXPECTED_PIN:
        raise DiagnosticError("canonical host-key pin mismatch")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            entry = _verified_entry(EXPECTED_TARGET, EXPECTED_PORT, EXPECTED_PIN)
        except (DiagnosticError, deploy.DeployError, OSError) as exc:
            _attempt_result(attempt, False, "not-run", "not-run", "not-run")
            if attempt == MAX_ATTEMPTS:
                raise DiagnosticError("pin verification failed") from exc
            continue

        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as known_hosts:
            known_hosts.write(entry)
            known_hosts.flush()
            argv = build_ssh_argv(EXPECTED_TARGET, EXPECTED_PORT, known_hosts.name)
            result = subprocess.run(
                argv,
                input=REMOTE_HELPER,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )

        remote_started = REMOTE_BEGIN in result.stdout
        if result.returncode == 0 and REMOTE_END in result.stdout:
            _attempt_result(attempt, True, "pass", "pass", "pass")
            print(result.stdout, end="")
            return 0

        failure = _failure_class(result.stderr)
        if remote_started:
            _attempt_result(attempt, True, "pass", "pass", "failed")
            print(result.stdout, end="")
            raise DiagnosticError("remote diagnostic failed")
        if failure == "authentication":
            _attempt_result(attempt, True, "pass", "failed", "not-run")
            raise DiagnosticError("SSH authentication failed")
        if failure == "transport":
            _attempt_result(attempt, True, "failed", "not-run", "not-run")
            if attempt == MAX_ATTEMPTS:
                raise DiagnosticError("all SSH transport attempts failed")
            continue
        _attempt_result(attempt, True, "unknown", "unknown", "not-run")
        raise DiagnosticError("SSH failed before remote execution")

    raise DiagnosticError("diagnostic attempts exhausted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        _require_clean_canonical_checkout()
        return run_diagnostic()
    except (DiagnosticError, deploy.DeployError, OSError, subprocess.SubprocessError) as exc:
        print(f"DIAGNOSTIC_BLOCKED={type(exc).__name__}", file=sys.stderr)
        return 2


REMOTE_HELPER = r'''#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys

REPO = "/opt/secretary"
COMPOSE = ["docker", "compose", "--env-file", "/opt/secretary/.env",
           "-f", "infra/compose.yaml", "-f", "infra/compose.deploy.yaml"]
EXPECTED_RELEASE = "8091736337689b68b4510126e74d9e409397f696"
EXPECTED_ALEMBIC = "0046"

def emit(key, value):
    print(f"{key}={value}", flush=True)

def run(argv, env=None, timeout=30):
    return subprocess.run(argv, text=True, capture_output=True, check=False,
                          env=env, timeout=timeout)

def compose(*args):
    return run(COMPOSE + list(args))

def env_map(value):
    if isinstance(value, list):
        return dict(item.split("=", 1) for item in value if "=" in item)
    return {str(key): str(item) for key, item in value.items()}

def fail(stage):
    emit("REMOTE_DIAGNOSTIC", "FAILED")
    emit("FAILURE_STAGE", stage)
    raise SystemExit(0)

def query(db, env, sql):
    child = os.environ.copy()
    child["PGPASSWORD"] = env["POSTGRES_PASSWORD"]
    argv = ["docker", "exec", "-e", "PGPASSWORD", "-i", db, "psql",
            "-h", "127.0.0.1", "-U", env.get("POSTGRES_USER", "secretary"),
            "-d", env.get("POSTGRES_DB", "secretary"), "-At", "-c", sql]
    result = run(argv, env=child)
    if result.returncode != 0:
        fail("database-query")
    return result.stdout.strip()

def classify_error(value):
    text = value.lower()
    if re.search(r"auth|authkey|session|unauthor", text):
        return "authorization-invalid"
    if re.search(r"unavailable|flood|server|timeout|network|transient", text):
        return "provider-unavailable"
    if not text:
        return "none"
    return "other-sanitized"

def main():
    emit("REMOTE_DIAGNOSTIC_BEGIN", "true")
    try:
        os.chdir(REPO)
        head = run(["git", "rev-parse", "HEAD"])
        production = run(["git", "rev-parse", "origin/production"])
        clean = run(["git", "status", "--porcelain"])
        if head.returncode or production.returncode or clean.returncode:
            fail("git")
        emit("RUNTIME_RELEASE_MATCH", "true" if head.stdout.strip() == EXPECTED_RELEASE else "false")
        emit("PRODUCTION_REF_MATCH", "true" if production.stdout.strip() == EXPECTED_RELEASE else "false")
        emit("PRODUCTION_WORKTREE_CLEAN", "true" if not clean.stdout.strip() else "false")

        health = run(["curl", "--fail", "--silent", "--max-time", "5", "http://127.0.0.1:18080/health"])
        health_ok = False
        if health.returncode == 0:
            try:
                health_ok = json.loads(health.stdout).get("status") == "ok"
            except (TypeError, ValueError):
                health_ok = False
        emit("HEALTH", "PASS" if health_ok else "FAIL")

        config = compose("config", "--format", "json")
        if config.returncode != 0:
            fail("compose-config")
        services = json.loads(config.stdout).get("services", {})
        api_env = env_map(services["api"]["environment"])
        db_env_raw = env_map(services["db"]["environment"])
        password = db_env_raw.get("POSTGRES_PASSWORD") or api_env.get("POSTGRES_PASSWORD")
        db_env = {"POSTGRES_PASSWORD": str(password),
                   "POSTGRES_USER": db_env_raw.get("POSTGRES_USER", "secretary"),
                   "POSTGRES_DB": db_env_raw.get("POSTGRES_DB", "secretary")}
        if not password:
            fail("compose-credentials")
        ids = {}
        for service in ("db", "api", "worker"):
            listed = compose("ps", "-q", service)
            if listed.returncode != 0 or not listed.stdout.strip():
                fail("container-lookup")
            ids[service] = listed.stdout.splitlines()[0].strip()
            running = run(["docker", "inspect", "-f", "{{.State.Running}}", ids[service]])
            emit(service.upper() + "_RUNNING", "true" if running.returncode == 0 and running.stdout.strip() == "true" else "false")
        db_health = run(["docker", "inspect", "-f", "{{.State.Health.Status}}", ids["db"]])
        emit("DB_HEALTHY", "true" if db_health.returncode == 0 and db_health.stdout.strip() == "healthy" else "false")

        if query(ids["db"], db_env, "SELECT 1") != "1":
            fail("db-auth")
        emit("DB_TCP_AUTH", "PASS")
        emit("ALEMBIC_0046", "true" if query(ids["db"], db_env, "SELECT version_num FROM alembic_version") == EXPECTED_ALEMBIC else "false")
        emit("MTPROTO_ACCOUNT_EXACTLY_ONE", "true" if query(ids["db"], db_env, "SELECT count(*) FROM telegram_mtproto_accounts") == "1" else "false")
        emit("SESSION_ENCRYPTED_NONEMPTY", query(ids["db"], db_env, "SELECT CASE WHEN count(*)=1 AND bool_and(length(session_encrypted)>0) THEN 'true' ELSE 'false' END FROM telegram_mtproto_accounts"))
        emit("ACCOUNT_FRESHNESS", "unknown")
        emit("ACTIVE_AUTH_CHALLENGE_COUNT", query(ids["db"], db_env, "SELECT count(*) FROM telegram_mtproto_auth_challenges WHERE expires_at > now()"))
        emit("MANUAL_SELECTED_GROUP_COUNT", query(ids["db"], db_env, "SELECT count(*) FROM telegram_mtproto_chat_selections WHERE manual_selected IS TRUE"))
        emit("CONFIGURED_SYNC_FOLDER_COUNT", query(ids["db"], db_env, "SELECT count(*) FROM telegram_mtproto_sync_folders"))
        active = query(ids["db"], db_env, "SELECT count(*) FROM telegram_mtproto_chat_selections WHERE scope_active IS TRUE")
        emit("ACTIVE_SCOPE_COUNT", active)
        emit("RECONCILE_SCOPE_PROVIDER_CALLS_POSSIBLE", "true" if active != "0" else "false")

        job_rows = query(ids["db"], db_env, "SELECT status || '|' || count(*) FROM jobs WHERE type='sync_telegram_mtproto' GROUP BY status ORDER BY status")
        emit("TELEGRAM_JOB_EXISTS", "true" if job_rows else "false")
        for row in job_rows.splitlines():
            status, count = row.split("|", 1)
            if status in {"pending", "running", "failed", "done"}:
                emit("TELEGRAM_JOB_" + status.upper(), count)
        recent = query(ids["db"], db_env, "SELECT CASE WHEN count(*)>0 THEN 'true' ELSE 'false' END FROM jobs WHERE type='sync_telegram_mtproto' AND updated_at >= now() - interval '24 hours'")
        emit("TELEGRAM_JOB_RECENT_24H", recent)
        categories = query(ids["db"], db_env, "SELECT count(*) || '|' || CASE WHEN lower(coalesce(last_error,'')) ~ '(auth|authkey|session|unauthor)' THEN 'authorization-invalid' WHEN lower(coalesce(last_error,'')) ~ '(unavailable|flood|server|timeout|network|transient)' THEN 'provider-unavailable' WHEN last_error IS NULL THEN 'none' ELSE 'other-sanitized' END FROM jobs WHERE type='sync_telegram_mtproto' AND status='failed' GROUP BY 2 ORDER BY 2")
        for row in categories.splitlines():
            count, category = row.split("|", 1)
            emit("TELEGRAM_JOB_FAILURE_CATEGORY", category + ":" + count)
        emit("WORKER_MANUAL_SYNC_OVERLAP_POSSIBLE", "unknown")

        evidence = {name: False for name in ("AUTH_KEY_DUPLICATED", "AuthKeyDuplicatedError", "AUTH_KEY_UNREGISTERED", "AuthKeyUnregisteredError", "SESSION_REVOKED", "SessionRevokedError", "UnauthorizedError", "AuthKeyNotFound")}
        routes = set()
        statuses = set()
        worker_auth = False
        worker_unavailable = False
        manual_auth = False
        manual_409 = False
        classes = set()
        for service in ("api", "worker"):
            logs = run(["docker", "logs", "--since", "24h", ids[service]])
            text = logs.stdout if logs.returncode == 0 else ""
            for line in text.splitlines():
                low = line.lower()
                for name in evidence:
                    if name.lower() in low:
                        evidence[name] = True
                if re.search(r"authorization|authkey|sessionrevoked|unauthorized", low):
                    classes.add("authorization-invalid")
                if re.search(r"provider.*unavailable|floodwait|servererror|network", low):
                    classes.add("provider-unavailable")
                if service == "worker" and re.search(r"authorization|authkey|sessionrevoked|unauthorized", low):
                    worker_auth = True
                if service == "worker" and re.search(r"provider.*unavailable|floodwait|servererror|network", low):
                    worker_unavailable = True
                if "telegram/mtproto" in low:
                    path = re.search(r"/telegram/mtproto/[a-z0-9_/{}/-]+", low)
                    if path:
                        routes.add(re.sub(r"/\d+", "/<peer>", path.group(0).split("?")[0]))
                    for code in re.findall(r"\b(?:2|4|5)\d\d\b", low):
                        statuses.add(code)
                if "sync-scope" in low and ("409" in low or "conflict" in low):
                    manual_409 = True
                if "sync-scope" in low and re.search(r"authorization.*(invalid|no longer valid)", low):
                    manual_auth = True
        emit("MTPROTO_ROUTES", ",".join(sorted(routes)) if routes else "none")
        emit("MTPROTO_HTTP_STATUSES", ",".join(sorted(statuses)) if statuses else "none")
        emit("MANUAL_GROUP_SYNC_AUTH_INVALID_OR_409", "true" if manual_auth or manual_409 else "unknown")
        emit("WORKER_AUTHORIZATION_INVALID", "true" if worker_auth else "false")
        emit("WORKER_PROVIDER_UNAVAILABLE", "true" if worker_unavailable else "false")
        emit("NORMALIZED_ERROR_CLASSES", ",".join(sorted(classes)) if classes else "none")
        for name, found in evidence.items():
            emit("EVIDENCE_" + name, "true" if found else "false")
        emit("NO_TELEGRAM_PROVIDER_CALLS", "true")
        emit("NO_SESSION_DECRYPTION", "true")
        emit("REMOTE_DIAGNOSTIC", "PASS")
        emit("REMOTE_DIAGNOSTIC_END", "true")
    except SystemExit:
        return 0
    except Exception:
        fail("sanitized-helper-error")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


if __name__ == "__main__":
    raise SystemExit(main())
