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
RELEASE = "bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b"
ALEMBIC = "0046"
BOT_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_USERNAME", "TELEGRAM_WEBHOOK_SECRET", "TELEGRAM_WEBHOOK_URL")
MT_KEYS = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH")
PROTECTED_KEYS = ("SECRETARY_CREDENTIAL_KEY", "POSTGRES_PASSWORD")
LEGACY_READ_CANDIDATE_LIMIT = 1000
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
PASS_FIELDS = (
    "REMOTE_HEAD_PASS", "REMOTE_PRODUCTION_REF_PASS", "REMOTE_WORKTREE_CLEAN",
    "DB_RUNNING_PASS", "API_RUNNING_PASS", "WORKER_RUNNING_PASS", "DB_HEALTH_PASS",
    "ALEMBIC_0046_PASS", "APP_HEALTH_PASS", "BOT_CONTAINER_ENV_ABSENT_PASS",
    "MTPROTO_CREDENTIALS_PRESERVED_PASS", "TELEGRAM_MTPROTO_AI_DISABLED_PASS",
    "LEGACY_BOT_ROUTES_ABSENT_PASS", "MTPROTO_ROUTE_PRESENT_PASS", "BOT_SETTINGS_MODEL_ABSENT_PASS",
)
SUCCESS_FIELDS = (
    "M4BR1_BEGIN", *PASS_FIELDS, "MTPROTO_ACCOUNT_COUNT", "ACTIVE_SCOPE_COUNT",
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


def authoritative_branch(branch: str, origin_url: str) -> str:
    """Return one exact branch SHA from the canonical URL without mutating refs."""
    if origin_url != CANONICAL_ORIGIN:
        raise ValueError("invalid origin")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or branch.startswith("/") or ".." in branch:
        raise ValueError("invalid branch")
    output = _run(["git", "ls-remote", origin_url, f"refs/heads/{branch}"])
    lines = output.splitlines()
    if len(lines) != 1:
        raise ValueError("unexpected ls-remote output")
    match = re.fullmatch(rf"([0-9a-f]{{40}})\trefs/heads/{re.escape(branch)}", lines[0])
    if match is None:
        raise ValueError("malformed ls-remote output")
    return match.group(1)


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


def _legacy_bot_lines_absent_or_empty(values: dict[str, str]) -> None:
    """Production .env may omit the four legacy Bot keys or keep them empty."""
    if any(values.get(key, "") != "" for key in BOT_KEYS):
        raise ValueError("Bot setting is nonempty")


def _bot_keys_absent(values: dict[str, str]) -> None:
    """Compose and container environments must not define the Bot keys at all."""
    if any(key in values for key in BOT_KEYS):
        raise ValueError("Bot setting is present")


def _has_eligible_candidate(candidates, is_eligible) -> bool:
    """Return whether any bounded legacy candidate passes the canonical read check."""
    return any(is_eligible(candidate) for candidate in candidates)


OPENAPI_URL = "http://127.0.0.1:18080/openapi.json"
LEGACY_ROUTE_PATHS = ("/telegram/link", "/integrations/telegram/webhook")
MTPROTO_ROUTE_PATH = "/telegram/mtproto/status"
BOT_SETTING_FIELDS = ("telegram_bot_token", "telegram_bot_username", "telegram_webhook_secret", "telegram_webhook_url")
SETTINGS_FAIL_STAGES = frozenset({
    "STAGE_2_SETTINGS_IMPORT",
    "STAGE_2_SETTINGS_EXECUTION",
    "STAGE_2_BOT_SETTINGS",
})
CHILD_FAIL_STAGES = frozenset({
    "STAGE_2_SQLALCHEMY",
    "STAGE_2_MODELS",
    "STAGE_2_DB_SESSION",
    "STAGE_2_RECENT_SOURCE",
    "STAGE_2_ACCOUNT",
    "STAGE_2_SCOPE",
    "STAGE_2_LEGACY_AGGREGATE",
    "STAGE_2_LEGACY_CANDIDATES",
    "STAGE_2_INBOX_READ",
    "STAGE_2_CANDIDATE_BOUND",
})
SETTINGS_CHILD = r"""
def _run():
    try:
        from app.core.config import Settings
    except Exception:
        return "STAGE_2_SETTINGS_IMPORT"
    try:
        fields = set(Settings.model_fields)
    except Exception:
        return "STAGE_2_SETTINGS_EXECUTION"
    if {"telegram_bot_token", "telegram_bot_username", "telegram_webhook_secret", "telegram_webhook_url"} & fields:
        return "STAGE_2_BOT_SETTINGS"
    print("CHILD_STATUS=ok")
    return ""

_stage = _run()
if _stage:
    print("CHILD_STATUS=fail")
    print("CHILD_STAGE=" + _stage)
"""
DB_CHILD = r"""
def _run():
    try:
        from sqlalchemy import func, or_, select
    except Exception:
        return "STAGE_2_SQLALCHEMY"
    try:
        from app.db.models import Object, TelegramMtprotoAccount, TelegramMtprotoChatSelection
    except Exception:
        return "STAGE_2_MODELS"
    try:
        from app.db.session import SessionLocal
    except Exception:
        return "STAGE_2_DB_SESSION"
    try:
        from app.services.recent_source_service import RecentSourceService
    except Exception:
        return "STAGE_2_RECENT_SOURCE"
    session = None
    try:
        session = SessionLocal()
    except Exception:
        return "STAGE_2_DB_SESSION"
    try:
        try:
            account_count = int(session.scalar(select(func.count()).select_from(TelegramMtprotoAccount)) or 0)
        except Exception:
            return "STAGE_2_ACCOUNT"
        if account_count != 1:
            return "STAGE_2_ACCOUNT"
        try:
            scope_count = int(session.scalar(select(func.count()).select_from(TelegramMtprotoChatSelection).where(TelegramMtprotoChatSelection.scope_active.is_(True))) or 0)
        except Exception:
            return "STAGE_2_SCOPE"
        if scope_count != 28:
            return "STAGE_2_SCOPE"
        legacy_filter = (Object.provider == "telegram", Object.kind == "chat_message", or_(Object.metadata_["transport"].as_string().is_(None), Object.metadata_["transport"].as_string() != "mtproto"))
        try:
            legacy_count = int(session.scalar(select(func.count()).select_from(Object).where(*legacy_filter)) or 0)
        except Exception:
            return "STAGE_2_LEGACY_AGGREGATE"
        if legacy_count < 1:
            return "STAGE_2_LEGACY_AGGREGATE"
        try:
            candidates = session.scalars(select(Object).where(*legacy_filter).order_by(Object.created_at.asc(), Object.id.asc()).limit(1000))
            candidate_rows = list(candidates)
        except Exception:
            return "STAGE_2_LEGACY_CANDIDATES"
        try:
            readable = any(RecentSourceService(session, candidate.user_id).get_inbox_eligible(candidate.id) is not None for candidate in candidate_rows)
        except Exception:
            return "STAGE_2_INBOX_READ"
        if not readable and legacy_count > 1000:
            return "STAGE_2_CANDIDATE_BOUND"
        if not readable:
            return "STAGE_2_INBOX_READ"
        print("CHILD_STATUS=ok")
        print(f"MTPROTO_ACCOUNT_COUNT={account_count}")
        print(f"ACTIVE_SCOPE_COUNT={scope_count}")
        print(f"LEGACY_BOT_OBJECT_COUNT={legacy_count}")
        print("LEGACY_BOT_INBOX_READABLE=true")
        return ""
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

_stage = _run()
if _stage:
    print("CHILD_STATUS=fail")
    print("CHILD_STAGE=" + _stage)
"""
_CHILD_COUNT_KEYS = ("MTPROTO_ACCOUNT_COUNT", "ACTIVE_SCOPE_COUNT", "LEGACY_BOT_OBJECT_COUNT")


def _openapi_paths(*, request=None, sleeper=time.sleep, attempts: int = 30, delay: float = 2.0) -> dict:
    """Read running API paths. Do not import app.main and do not print the schema."""
    request = request or urllib.request.urlopen
    for attempt in range(attempts):
        try:
            with request(OPENAPI_URL, timeout=5) as response:
                status = getattr(response, "status", 0)
                body = response.read()
        except (OSError, urllib.error.URLError, TimeoutError):
            if attempt + 1 < attempts:
                sleeper(delay)
                continue
            raise VerifyError("STAGE_2_OPENAPI_FETCH", RuntimeError()) from None
        if not isinstance(status, int) or not 200 <= status < 300:
            if attempt + 1 < attempts:
                sleeper(delay)
                continue
            raise VerifyError("STAGE_2_OPENAPI_FETCH", RuntimeError())
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise VerifyError("STAGE_2_OPENAPI_PROTOCOL", ValueError()) from None
        paths = payload.get("paths") if isinstance(payload, dict) else None
        if not isinstance(paths, dict):
            raise VerifyError("STAGE_2_OPENAPI_PROTOCOL", ValueError())
        return paths
    raise VerifyError("STAGE_2_OPENAPI_FETCH", RuntimeError())


def _parse_status_child(output: str, fail_stages: frozenset[str], protocol_stage: str) -> None:
    lines = output.splitlines()
    if lines == ["CHILD_STATUS=ok"]:
        return
    if len(lines) == 2 and lines[0] == "CHILD_STATUS=fail" and lines[1].startswith("CHILD_STAGE="):
        stage = lines[1].split("=", 1)[1]
        if stage in fail_stages:
            raise VerifyError(stage, RuntimeError())
    raise VerifyError(protocol_stage, ValueError())


def _settings_child(compose: list[str]) -> None:
    try:
        output = _run([*compose, "exec", "-T", "api", "python", "-c", SETTINGS_CHILD])
    except Exception as exc:
        raise VerifyError("STAGE_2_SETTINGS_EXECUTION", RuntimeError()) from exc
    _parse_status_child(output, SETTINGS_FAIL_STAGES, "STAGE_2_SETTINGS_PROTOCOL")


def _parse_child(output: str) -> dict[str, str]:
    lines = output.splitlines()
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in lines:
        key, sep, value = line.partition("=")
        if not sep or not key or not value or key in seen:
            raise VerifyError("STAGE_2_CHILD_PROTOCOL", ValueError())
        seen.add(key)
        pairs.append((key, value))
    keys = [key for key, _value in pairs]
    values = dict(pairs)
    if keys == ["CHILD_STATUS", "CHILD_STAGE"] and values["CHILD_STATUS"] == "fail":
        stage = values["CHILD_STAGE"]
        if stage in CHILD_FAIL_STAGES:
            raise VerifyError(stage, RuntimeError())
        raise VerifyError("STAGE_2_CHILD_PROTOCOL", ValueError())
    if keys != ["CHILD_STATUS", *_CHILD_COUNT_KEYS, "LEGACY_BOT_INBOX_READABLE"] or values["CHILD_STATUS"] != "ok":
        raise VerifyError("STAGE_2_CHILD_PROTOCOL", ValueError())
    if any(re.fullmatch(r"[0-9]+", values[key]) is None for key in _CHILD_COUNT_KEYS):
        raise VerifyError("STAGE_2_CHILD_PROTOCOL", ValueError())
    if values["LEGACY_BOT_INBOX_READABLE"] not in {"true", "false"}:
        raise VerifyError("STAGE_2_CHILD_PROTOCOL", ValueError())
    if values["MTPROTO_ACCOUNT_COUNT"] != "1":
        raise VerifyError("STAGE_2_ACCOUNT", RuntimeError())
    if values["ACTIVE_SCOPE_COUNT"] != "28":
        raise VerifyError("STAGE_2_SCOPE", RuntimeError())
    if int(values["LEGACY_BOT_OBJECT_COUNT"]) < 1:
        raise VerifyError("STAGE_2_LEGACY_AGGREGATE", RuntimeError())
    if values["LEGACY_BOT_INBOX_READABLE"] != "true":
        raise VerifyError("STAGE_2_INBOX_READ", RuntimeError())
    return {key: values[key] for key in (*_CHILD_COUNT_KEYS, "LEGACY_BOT_INBOX_READABLE")}


def _child(compose: list[str]) -> dict[str, str]:
    try:
        output = _run([*compose, "exec", "-T", "api", "python", "-c", DB_CHILD])
    except Exception as exc:
        raise VerifyError("STAGE_2_CHILD_EXECUTION", RuntimeError()) from exc
    return _parse_child(output)

def remote_main() -> int:
    try:
        emit("M4BR1_BEGIN", "true")
        origin = _run(["git", "remote", "get-url", "origin"])
        if origin != CANONICAL_ORIGIN:
            raise VerifyError("STAGE_0_CANONICAL_REPO", ValueError())
        try:
            if _run(["git", "rev-parse", "HEAD"]) != RELEASE:
                raise ValueError("head")
        except Exception as exc:
            raise VerifyError("STAGE_0_REMOTE_HEAD", exc) from exc
        emit("REMOTE_HEAD_PASS", "true")
        try:
            if authoritative_branch("production", origin) != RELEASE:
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
            _legacy_bot_lines_absent_or_empty(env_values)
            if int(env_values.get("TELEGRAM_API_ID", "0")) <= 0 or not env_values.get("TELEGRAM_API_HASH"):
                raise ValueError("MTProto credentials unavailable")
            if any(not env_values.get(key) for key in PROTECTED_KEYS):
                raise ValueError("protected credential unavailable")
            if env_values.get("TELEGRAM_MTPROTO_AI_ENABLED", "false").lower() != "false":
                raise ValueError("AI flag enabled")
            for service in ("api", "worker"):
                values = _service_env(config, service)
                _bot_keys_absent(values)
                for key in MT_KEYS + PROTECTED_KEYS:
                    if values.get(key) != env_values.get(key):
                        raise ValueError("protected service environment mismatch")
                if values.get("TELEGRAM_MTPROTO_AI_ENABLED", "false").lower() != "false":
                    raise ValueError("AI flag enabled")
                values = _container_env(ids[service])
                _bot_keys_absent(values)
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
            paths = _openapi_paths()
        except VerifyError:
            raise
        except Exception as exc:
            raise VerifyError("STAGE_2_OPENAPI_FETCH", exc) from exc
        if any(path in paths for path in LEGACY_ROUTE_PATHS):
            raise VerifyError("STAGE_2_LEGACY_ROUTES", RuntimeError())
        emit("LEGACY_BOT_ROUTES_ABSENT_PASS", "true")
        if MTPROTO_ROUTE_PATH not in paths:
            raise VerifyError("STAGE_2_MTPROTO_ROUTE", RuntimeError())
        emit("MTPROTO_ROUTE_PRESENT_PASS", "true")
        try:
            _settings_child(compose)
        except VerifyError:
            raise
        except Exception as exc:
            raise VerifyError("STAGE_2_SETTINGS_PROTOCOL", exc) from exc
        emit("BOT_SETTINGS_MODEL_ABSENT_PASS", "true")
        try:
            values = _child(compose)
        except VerifyError:
            raise
        except Exception as exc:
            raise VerifyError("STAGE_2_CHILD_PROTOCOL", exc) from exc
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
        if values["M4BR1_TERMINAL"] != "success" or any(values[key] != "true" for key in PASS_FIELDS):
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
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("bundle", "remote", "validate", "target", "release", "authoritative")); parser.add_argument("path", nargs="?"); parser.add_argument("origin", nargs="?")
    args = parser.parse_args()
    if args.command == "bundle": print(Path(__file__).read_text(encoding="utf-8"), end=""); return 0
    if args.command == "remote": return remote_main()
    if args.command == "release": print(RELEASE); return 0
    if args.command == "authoritative":
        try:
            print(authoritative_branch(args.path or "", args.origin or ""))
            return 0
        except (OSError, ValueError, RuntimeError):
            return 2
    if args.command == "target":
        target = load_target(Path(args.path) if args.path else TARGET_FILE)
        for key in ("ssh_target", "ssh_port", "host_key_sha256", "repository_path", "origin_url"): print(target[key])
        return 0
    try:
        print(parse_output(Path(args.path).read_text(encoding="utf-8")))
        return 0
    except (OSError, ValueError):
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
