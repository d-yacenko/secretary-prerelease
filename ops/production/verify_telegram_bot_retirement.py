#!/usr/bin/env python3
"""Read-only post-retirement verifier; no provider or mutation capability."""
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
RELEASE = "fe151f12f64886505253e765b82458710a949e34"
ALEMBIC = "0046"
BOT_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_USERNAME", "TELEGRAM_WEBHOOK_SECRET", "TELEGRAM_WEBHOOK_URL")
MT_KEYS = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH")
PROTECTED_KEYS = ("SECRETARY_CREDENTIAL_KEY", "POSTGRES_PASSWORD")
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
SUCCESS_FIELDS = (
    "M4BM1_BEGIN", "REMOTE_HEAD_PASS", "REMOTE_PRODUCTION_REF_PASS", "REMOTE_WORKTREE_CLEAN",
    "DB_RUNNING_PASS", "API_RUNNING_PASS", "WORKER_RUNNING_PASS", "DB_HEALTH_PASS",
    "BOT_ENV_EMPTY_PASS", "BOT_COMPOSE_ENV_EMPTY_PASS", "BOT_CONTAINER_ENV_EMPTY_PASS",
    "MTPROTO_CREDENTIALS_PRESERVED_PASS", "CREDENTIAL_KEY_PRESERVED_PASS",
    "DB_CREDENTIAL_PRESERVED_PASS", "TELEGRAM_MTPROTO_AI_DISABLED_PASS", "HEALTH_PASS",
    "ALEMBIC_0046_PASS", "TELEGRAM_NETWORK_CALLS", "DB_WRITES", "ENV_WRITES",
    "SERVICE_RECREATIONS", "M4BM1_TERMINAL", "M4BM1_END",
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


def remote_main() -> int:
    try:
        emit("M4BM1_BEGIN", "true")
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
        emit("DB_RUNNING_PASS", "true"); emit("API_RUNNING_PASS", "true"); emit("WORKER_RUNNING_PASS", "true")
        try:
            _container_state(ids["db"], healthy=True)
        except Exception as exc:
            raise VerifyError("STAGE_0_DB_HEALTH", exc) from exc
        emit("DB_HEALTH_PASS", "true")
        try:
            db_volume = _run(["docker", "inspect", "-f", "{{range .Mounts}}{{.Name}}={{.Destination}} {{end}}", ids["db"]])
            if not db_volume:
                raise RuntimeError("database volume unavailable")
            _require_alembic(compose)
        except Exception as exc:
            raise VerifyError("STAGE_0_ALEMBIC", exc) from exc
        try:
            _require_empty(env_values, BOT_KEYS)
            if int(env_values.get("TELEGRAM_API_ID", "0")) <= 0 or not env_values.get("TELEGRAM_API_HASH"):
                raise ValueError("MTProto credentials unavailable")
            if any(not env_values.get(key) for key in PROTECTED_KEYS):
                raise ValueError("protected credential unavailable")
            if env_values.get("TELEGRAM_MTPROTO_AI_ENABLED", "false").lower() != "false":
                raise ValueError("AI flag enabled")
        except Exception as exc:
            raise VerifyError("STAGE_1_ENV", exc) from exc
        emit("BOT_ENV_EMPTY_PASS", "true")
        try:
            service_envs = {service: _service_env(config, service) for service in ("api", "worker")}
            for values in service_envs.values():
                _require_empty(values, BOT_KEYS)
                for key in MT_KEYS + PROTECTED_KEYS:
                    if values.get(key) != env_values.get(key):
                        raise ValueError("protected service environment mismatch")
                if values.get("TELEGRAM_MTPROTO_AI_ENABLED", "false").lower() != "false":
                    raise ValueError("AI flag enabled")
        except Exception as exc:
            raise VerifyError("STAGE_1_COMPOSE_ENV", exc) from exc
        emit("BOT_COMPOSE_ENV_EMPTY_PASS", "true")
        try:
            for service in ("api", "worker"):
                values = _container_env(ids[service])
                _require_empty(values, BOT_KEYS)
                for key in MT_KEYS + PROTECTED_KEYS:
                    if values.get(key) != env_values.get(key):
                        raise ValueError("protected container environment mismatch")
                if values.get("TELEGRAM_MTPROTO_AI_ENABLED", "false").lower() != "false":
                    raise ValueError("AI flag enabled")
        except Exception as exc:
            raise VerifyError("STAGE_1_CONTAINER_ENV", exc) from exc
        emit("BOT_CONTAINER_ENV_EMPTY_PASS", "true")
        emit("MTPROTO_CREDENTIALS_PRESERVED_PASS", "true"); emit("CREDENTIAL_KEY_PRESERVED_PASS", "true")
        emit("DB_CREDENTIAL_PRESERVED_PASS", "true"); emit("TELEGRAM_MTPROTO_AI_DISABLED_PASS", "true")
        try:
            _health("http://127.0.0.1:18080/health")
        except Exception as exc:
            raise VerifyError("STAGE_2_APP_HEALTH", exc) from exc
        emit("HEALTH_PASS", "true")
        try:
            _require_alembic(compose)
        except Exception as exc:
            raise VerifyError("STAGE_2_ALEMBIC", exc) from exc
        emit("ALEMBIC_0046_PASS", "true")
        for key, value in (("TELEGRAM_NETWORK_CALLS", "0"), ("DB_WRITES", "0"), ("ENV_WRITES", "0"), ("SERVICE_RECREATIONS", "0")):
            emit(key, value)
        emit("M4BM1_TERMINAL", "success"); emit("M4BM1_END", "true"); return 0
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
    emit("M4BM1_TERMINAL", "failure")


def parse_output(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0] != "M4BM1_BEGIN=true":
        raise ValueError("invalid begin")
    if lines[-1] == "M4BM1_END=true":
        if len(lines) != len(SUCCESS_FIELDS) or [line.split("=", 1)[0] for line in lines] != list(SUCCESS_FIELDS):
            raise ValueError("invalid success protocol")
        if lines[-2] != "M4BM1_TERMINAL=success" or any(line.endswith("=false") for line in lines):
            raise ValueError("invalid success values")
        values = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in lines}
        if any(values[key] != "0" for key in ("TELEGRAM_NETWORK_CALLS", "DB_WRITES", "ENV_WRITES", "SERVICE_RECREATIONS")):
            raise ValueError("invalid counters")
        return "success"
    required = {"FAILURE_STAGE", "RAW_EXCEPTION_CLASS", "TELEGRAM_NETWORK_CALLS", "DB_WRITES", "ENV_WRITES", "SERVICE_RECREATIONS", "M4BM1_TERMINAL"}
    keys = [line.split("=", 1)[0] for line in lines]
    if lines[-1] != "M4BM1_TERMINAL=failure" or not required.issubset(keys) or len(keys) != len(set(keys)):
        raise ValueError("invalid failure protocol")
    if any(not re.fullmatch(r"[A-Za-z0-9_]+", line.split("=", 1)[1]) for line in lines if line.startswith("RAW_EXCEPTION_CLASS=")):
        raise ValueError("unsafe failure class")
    if any(not re.fullmatch(r"STAGE_[A-Z0-9_]+", line.split("=", 1)[1]) for line in lines if line.startswith("FAILURE_STAGE=")):
        raise ValueError("unsafe failure stage")
    for key in ("TELEGRAM_NETWORK_CALLS", "DB_WRITES", "ENV_WRITES", "SERVICE_RECREATIONS"):
        value = next(line.split("=", 1)[1] for line in lines if line.startswith(key + "="))
        if value != "0":
            raise ValueError("nonzero failure counter")
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
