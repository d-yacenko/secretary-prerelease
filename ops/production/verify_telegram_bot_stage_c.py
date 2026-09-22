#!/usr/bin/env python3
"""Read-only Stage C acceptance verifier; no provider or mutation capability."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET_FILE = HERE / "target.json"
CANONICAL_ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"
RELEASE = "bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4"
ALEMBIC = "0046"
BOT_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_USERNAME", "TELEGRAM_WEBHOOK_SECRET", "TELEGRAM_WEBHOOK_URL")
MT_KEYS = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH")
PROTECTED_KEYS = ("SECRETARY_CREDENTIAL_KEY", "POSTGRES_PASSWORD")
LEGACY_READ_CANDIDATE_LIMIT = 1000
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
SUCCESS_FIELDS = (
    "M4BR1_BEGIN", "REMOTE_HEAD_PASS", "REMOTE_PRODUCTION_REF_PASS", "REMOTE_WORKTREE_CLEAN",
    "DB_RUNNING_PASS", "API_RUNNING_PASS", "WORKER_RUNNING_PASS", "DB_HEALTH_PASS", "APP_HEALTH_PASS",
    "ALEMBIC_0046_PASS", "LEGACY_BOT_ROUTES_ABSENT_PASS", "MTPROTO_ROUTE_PRESENT_PASS",
    "BOT_SETTINGS_MODEL_ABSENT_PASS", "BOT_CONTAINER_ENV_ABSENT_PASS", "MTPROTO_CREDENTIALS_PRESERVED_PASS",
    "TELEGRAM_MTPROTO_AI_DISABLED_PASS", "MTPROTO_ACCOUNT_COUNT", "ACTIVE_SCOPE_COUNT",
    "LEGACY_BOT_OBJECT_COUNT", "LEGACY_BOT_INBOX_READABLE", "TELEGRAM_NETWORK_CALLS", "DB_WRITES",
    "ENV_WRITES", "SERVICE_RECREATIONS", "M4BR1_TERMINAL", "M4BR1_END",
)
class VerifyError(RuntimeError):
    def __init__(self, stage: str, cause: BaseException):
        super().__init__(stage)
        self.stage, self.cause = stage, cause


def _safe_class(exc: BaseException) -> str:
    return type(exc).__name__[:64] or "RuntimeError"


def load_target(path: Path = TARGET_FILE) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"ssh_target", "ssh_port", "host_key_sha256", "repository_path", "origin_url", "health_url", "compose_files"}
    if not required.issubset(data) or not str(data["ssh_target"]).strip():
        raise ValueError("invalid target")
    if not isinstance(data["ssh_port"], int) or not 1 <= data["ssh_port"] <= 65535:
        raise ValueError("invalid port")
    if not FINGERPRINT_RE.fullmatch(str(data["host_key_sha256"])):
        raise ValueError("invalid pin")
    if data["repository_path"] != "/opt/secretary" or data["origin_url"] != CANONICAL_ORIGIN:
        raise ValueError("invalid repository contract")
    if data["health_url"] != "http://127.0.0.1:18080/health" or data["compose_files"] != ["infra/compose.yaml", "infra/compose.deploy.yaml"]:
        raise ValueError("invalid runtime contract")
    return data


def _run(command: list[str]) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("command failed")
    return result.stdout.strip()


def _compose() -> list[str]:
    return ["docker", "compose", "--env-file", ".env", "-f", "infra/compose.yaml", "-f", "infra/compose.deploy.yaml"]


def _env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if line and not line.startswith("#") and re.fullmatch(r"[A-Z][A-Z0-9_]*=.*", line):
            key, value = line.split("=", 1)
            if key in values:
                raise ValueError("duplicate environment key")
            values[key] = value
    return values


def _service_env(config: dict, service: str) -> dict[str, str]:
    raw = config["services"][service].get("environment")
    if isinstance(raw, dict):
        return {str(k): "" if v is None else str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        result = {}
        for item in raw:
            if not isinstance(item, str) or "=" not in item:
                raise ValueError("invalid service environment")
            key, value = item.split("=", 1)
            result[key] = value
        return result
    raise ValueError("invalid service environment")


def _container_state(container: str, healthy: bool = False) -> None:
    state = json.loads(_run(["docker", "inspect", "-f", "{{json .State}}", container]))
    if not isinstance(state, dict) or state.get("Status") != "running":
        raise RuntimeError("container not running")
    if healthy and (not isinstance(state.get("Health"), dict) or state["Health"].get("Status") != "healthy"):
        raise RuntimeError("database not healthy")


def _container_env(container: str) -> dict[str, str]:
    raw = json.loads(_run(["docker", "inspect", "-f", "{{json .Config.Env}}", container]))
    if not isinstance(raw, list):
        raise TypeError("invalid container environment")
    result = {}
    for item in raw:
        if not isinstance(item, str) or "=" not in item:
            raise ValueError("invalid container environment")
        key, value = item.split("=", 1)
        result[key] = value
    return result


def _health(url: str, *, attempts: int = 30, delay: float = 2.0, request=None, sleeper=time.sleep) -> None:
    request = request or urllib.request.urlopen
    for attempt in range(attempts):
        try:
            with request(url, timeout=5) as response:
                if 200 <= response.status < 300:
                    return
        except (OSError, urllib.error.URLError, ValueError):
            pass
        if attempt + 1 < attempts:
            sleeper(delay)
    raise RuntimeError("health check exhausted")


def _require_alembic(compose: list[str]) -> None:
    lines = _run([*compose, "exec", "-T", "api", "alembic", "current"]).splitlines()
    if lines != [f"{ALEMBIC} (head)"]:
        raise RuntimeError("unexpected Alembic revision")


def _require_empty(values: dict[str, str], keys: tuple[str, ...]) -> None:
    if any(values.get(key, "") != "" for key in keys):
        raise ValueError("Bot setting is nonempty")


def _has_eligible_candidate(candidates, is_eligible) -> bool:
    """Return whether any bounded legacy candidate passes the canonical read check."""
    return any(is_eligible(candidate) for candidate in candidates)


CHILD = r"""
from sqlalchemy import func, or_, select
from app.core.config import Settings
from app.db.models import Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection
from app.db.session import SessionLocal
from app.main import app
from app.services.recent_source_service import RecentSourceService

routes = {route.path for route in app.routes}
if "/telegram/link" in routes or "/integrations/telegram/webhook" in routes:
    raise RuntimeError("legacy route present")
if "/telegram/mtproto/status" not in routes:
    raise RuntimeError("MTProto route absent")
if {"telegram_bot_token", "telegram_bot_username", "telegram_webhook_secret", "telegram_webhook_url"} & set(Settings.model_fields):
    raise RuntimeError("Bot setting present")
session = SessionLocal()
try:
    account_count = int(session.scalar(select(func.count()).select_from(TelegramMtprotoAccount)) or 0)
    scope_count = int(session.scalar(select(func.count()).select_from(TelegramMtprotoChatSelection).where(TelegramMtprotoChatSelection.scope_active.is_(True))) or 0)
    legacy_filter = (Object.provider == "telegram", Object.kind == "chat_message", or_(Object.metadata_["transport"].as_string().is_(None), Object.metadata_["transport"].as_string() != "mtproto"))
    legacy_count = int(session.scalar(select(func.count()).select_from(Object).where(*legacy_filter)) or 0)
    candidates = session.scalars(
        select(Object)
        .where(*legacy_filter)
        .order_by(Object.created_at.asc(), Object.id.asc())
        .limit(1000)
    )
    candidate_rows = list(candidates)
    readable = any(
        RecentSourceService(session, candidate.user_id).get_inbox_eligible(candidate.id) is not None
        for candidate in candidate_rows
    )
    if not readable and legacy_count > 1000:
        raise RuntimeError("legacy read candidate bound exhausted")
    print(f"MTPROTO_ACCOUNT_COUNT={account_count}")
    print(f"ACTIVE_SCOPE_COUNT={scope_count}")
    print(f"LEGACY_BOT_OBJECT_COUNT={legacy_count}")
    print(f"LEGACY_BOT_INBOX_READABLE={'true' if readable else 'false'}")
finally:
    session.close()
"""

def _child(compose: list[str]) -> dict[str, str]:
    lines = _run([*compose, "exec", "-T", "api", "python", "-c", CHILD]).splitlines()
    allowed = {"MTPROTO_ACCOUNT_COUNT", "ACTIVE_SCOPE_COUNT", "LEGACY_BOT_OBJECT_COUNT", "LEGACY_BOT_INBOX_READABLE"}
    values = {}
    for line in lines:
        key, sep, value = line.partition("=")
        if not sep or key not in allowed or key in values or not value:
            raise ValueError("unsafe child output")
        values[key] = value
    if set(values) != allowed:
        raise ValueError("incomplete child output")
    return values

def remote_main() -> int:
    try:
        emit("M4BR1_BEGIN", "true")
        if _run(["git", "remote", "get-url", "origin"]) != CANONICAL_ORIGIN:
            raise VerifyError("STAGE_0_CANONICAL_REPO", ValueError())
        try:
            _run(["git", "fetch", "--prune", "origin", "production"])
            if _run(["git", "rev-parse", "HEAD"]) != RELEASE:
                raise ValueError("head")
        except Exception as exc:
            raise VerifyError("STAGE_0_REMOTE_HEAD", exc) from exc
        emit("REMOTE_HEAD_PASS", "true")
        try:
            if _run(["git", "rev-parse", "origin/production"]) != RELEASE:
                raise ValueError("production ref")
        except Exception as exc:
            raise VerifyError("STAGE_0_PRODUCTION_REF", exc) from exc
        emit("REMOTE_PRODUCTION_REF_PASS", "true")
        try:
            if _run(["git", "status", "--porcelain"]):
                raise ValueError("dirty")
        except Exception as exc:
            raise VerifyError("STAGE_0_WORKTREE", exc) from exc
        emit("REMOTE_WORKTREE_CLEAN", "true")
        compose = _compose()
        try:
            config = json.loads(_run([*compose, "config", "--format", "json"]))
            env_values = _env(Path(".env").read_text(encoding="utf-8"))
            ids = {service: _run([*compose, "ps", "-q", service]) for service in ("db", "api", "worker")}
            if not all(ids.values()) or not isinstance(config.get("services"), dict):
                raise RuntimeError("runtime unavailable")
        except Exception as exc:
            raise VerifyError("STAGE_0_RUNTIME", exc) from exc
        for service, healthy in (("db", True), ("api", False), ("worker", False)):
            try:
                _container_state(ids[service], healthy=healthy)
            except Exception as exc:
                stage = "STAGE_0_DB_HEALTH" if service == "db" else f"STAGE_0_{service.upper()}_RUNNING"
                raise VerifyError(stage, exc) from exc
            emit(f"{service.upper()}_RUNNING_PASS", "true")
        emit("DB_HEALTH_PASS", "true")
        try:
            _require_alembic(compose)
        except Exception as exc:
            raise VerifyError("STAGE_0_ALEMBIC", exc) from exc
        emit("ALEMBIC_0046_PASS", "true")
        try:
            _health("http://127.0.0.1:18080/health")
        except Exception as exc:
            raise VerifyError("STAGE_0_APP_HEALTH", exc) from exc
        emit("APP_HEALTH_PASS", "true")
        try:
            _require_empty(env_values, BOT_KEYS)
            if int(env_values.get("TELEGRAM_API_ID", "0")) <= 0 or not env_values.get("TELEGRAM_API_HASH"):
                raise ValueError("MTProto credentials unavailable")
            if any(not env_values.get(key) for key in PROTECTED_KEYS):
                raise ValueError("protected credential unavailable")
            if env_values.get("TELEGRAM_MTPROTO_AI_ENABLED", "false").lower() != "false":
                raise ValueError("AI flag enabled")
            for service in ("api", "worker"):
                values = _service_env(config, service)
                _require_empty(values, BOT_KEYS)
                for key in MT_KEYS + PROTECTED_KEYS:
                    if values.get(key) != env_values.get(key):
                        raise ValueError("protected service environment mismatch")
                if values.get("TELEGRAM_MTPROTO_AI_ENABLED", "false").lower() != "false":
                    raise ValueError("AI flag enabled")
                values = _container_env(ids[service])
                _require_empty(values, BOT_KEYS)
                for key in MT_KEYS + PROTECTED_KEYS:
                    if values.get(key) != env_values.get(key):
                        raise ValueError("protected container environment mismatch")
                if values.get("TELEGRAM_MTPROTO_AI_ENABLED", "false").lower() != "false":
                    raise ValueError("AI flag enabled")
        except Exception as exc:
            raise VerifyError("STAGE_1_ENVIRONMENT", exc) from exc
        emit("BOT_CONTAINER_ENV_ABSENT_PASS", "true")
        emit("MTPROTO_CREDENTIALS_PRESERVED_PASS", "true")
        emit("TELEGRAM_MTPROTO_AI_DISABLED_PASS", "true")
        try:
            values = _child(compose)
            if values["MTPROTO_ACCOUNT_COUNT"] != "1" or values["ACTIVE_SCOPE_COUNT"] != "28":
                raise ValueError("unexpected MTProto state")
            if values["LEGACY_BOT_INBOX_READABLE"] != "true" or int(values["LEGACY_BOT_OBJECT_COUNT"]) < 1:
                raise ValueError("legacy object is not readable")
        except Exception as exc:
            raise VerifyError("STAGE_2_READ_ONLY_STATE", exc) from exc
        emit("LEGACY_BOT_ROUTES_ABSENT_PASS", "true")
        emit("MTPROTO_ROUTE_PRESENT_PASS", "true")
        emit("BOT_SETTINGS_MODEL_ABSENT_PASS", "true")
        for key in ("MTPROTO_ACCOUNT_COUNT", "ACTIVE_SCOPE_COUNT", "LEGACY_BOT_OBJECT_COUNT"):
            emit(key, values[key])
        emit("LEGACY_BOT_INBOX_READABLE", values["LEGACY_BOT_INBOX_READABLE"])
        for key in ("TELEGRAM_NETWORK_CALLS", "DB_WRITES", "ENV_WRITES", "SERVICE_RECREATIONS"):
            emit(key, "0")
        emit("M4BR1_TERMINAL", "success")
        emit("M4BR1_END", "true")
        return 0
    except VerifyError as exc:
        emit_failure(exc.stage, exc.cause)
    except Exception as exc:  # noqa: BLE001
        emit_failure("STAGE_UNKNOWN", exc)
    return 2


def emit(key: str, value: str) -> None:
    print(f"{key}={value}", flush=True)


def emit_failure(stage: str, cause: BaseException) -> None:
    emit("FAILURE_STAGE", stage); emit("RAW_EXCEPTION_CLASS", _safe_class(cause))
    emit("TELEGRAM_NETWORK_CALLS", "0"); emit("DB_WRITES", "0"); emit("ENV_WRITES", "0"); emit("SERVICE_RECREATIONS", "0")
    emit("M4BR1_TERMINAL", "failure")


def parse_output(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0] != "M4BR1_BEGIN=true":
        raise ValueError("invalid protocol")
    pairs = [line.split("=", 1) for line in lines if "=" in line]
    if any(len(pair) != 2 or not pair[0] or not pair[1] for pair in pairs) or len(pairs) != len(lines):
        raise ValueError("malformed protocol")
    keys = [pair[0] for pair in pairs]
    if lines[-1] == "M4BR1_END=true":
        if keys != list(SUCCESS_FIELDS):
            raise ValueError("invalid success protocol")
        values = dict(pairs)
        if values["M4BR1_TERMINAL"] != "success" or any(values[key] != "true" for key in SUCCESS_FIELDS[1:16]):
            raise ValueError("invalid success values")
        if values["LEGACY_BOT_INBOX_READABLE"] != "true" or any(values[key] != "0" for key in ("TELEGRAM_NETWORK_CALLS", "DB_WRITES", "ENV_WRITES", "SERVICE_RECREATIONS")):
            raise ValueError("invalid success counters")
        return "success"
    tail = ("FAILURE_STAGE", "RAW_EXCEPTION_CLASS", "TELEGRAM_NETWORK_CALLS", "DB_WRITES", "ENV_WRITES", "SERVICE_RECREATIONS", "M4BR1_TERMINAL")
    if len(keys) < 1 + len(tail) or tuple(keys[-len(tail):]) != tail or keys[0] != "M4BR1_BEGIN":
        raise ValueError("invalid failure protocol")
    values = dict(pairs)
    prefix = keys[:-len(tail)]
    if prefix != list(SUCCESS_FIELDS[:len(prefix)]) or not prefix:
        raise ValueError("unknown failure prefix")
    if any(values[key] != "true" for key in prefix[1:]):
        raise ValueError("invalid failure prefix")
    if not re.fullmatch(r"STAGE_[A-Z0-9_]+", values["FAILURE_STAGE"]) or not re.fullmatch(r"[A-Za-z0-9_]+", values["RAW_EXCEPTION_CLASS"]):
        raise ValueError("unsafe failure fields")
    if any(values[key] != "0" for key in tail[2:-1]) or values["M4BR1_TERMINAL"] != "failure":
        raise ValueError("invalid failure values")
    return "failure"


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("bundle", "remote", "validate", "target", "release")); parser.add_argument("path", nargs="?")
    args = parser.parse_args()
    if args.command == "bundle": print(Path(__file__).read_text(encoding="utf-8"), end=""); return 0
    if args.command == "remote": return remote_main()
    if args.command == "release": print(RELEASE); return 0
    if args.command == "target":
        target = load_target(Path(args.path) if args.path else TARGET_FILE)
        for key in ("ssh_target", "ssh_port", "host_key_sha256", "repository_path", "origin_url"): print(target[key])
        return 0
    try: return 0 if parse_output(Path(args.path).read_text(encoding="utf-8")) else 2
    except (OSError, ValueError): return 2

if __name__ == "__main__":
    raise SystemExit(main())
