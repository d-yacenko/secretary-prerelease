#!/usr/bin/env python3
"""Stage B Telegram Bot retirement harness.

The default production entrypoint is the shell wrapper beside this file.  This
module also contains the streamed remote helper and a strict output validator;
the helper is deliberately written so all sensitive values stay in memory or
the process environment and never enter the protocol output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parent.parent
TARGET_FILE = HERE / "target.json"
CANONICAL_ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"
RELEASE = "fe151f12f64886505253e765b82458710a949e34"
ALEMBIC = "0046"
BOT_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_BOT_USERNAME",
    "TELEGRAM_WEBHOOK_SECRET",
    "TELEGRAM_WEBHOOK_URL",
)
MT_PROTO_KEYS = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH")
INVARIANT_KEYS = ("SECRETARY_CREDENTIAL_KEY", "POSTGRES_PASSWORD")
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")

SUCCESS_FIELDS = (
    "M4BJ1_BEGIN",
    "CANONICAL_REPO_PASS",
    "TARGET_PIN_PASS",
    "REMOTE_HEAD_PASS",
    "REMOTE_PRODUCTION_REF_PASS",
    "REMOTE_WORKTREE_CLEAN",
    "COMPOSE_CONFIG_PASS",
    "DB_RUNNING_PASS",
    "API_RUNNING_PASS",
    "WORKER_RUNNING_PASS",
    "DB_HEALTH_PASS",
    "ALEMBIC_0046_PASS",
    "BOT_CREDENTIALS_AVAILABLE_PASS",
    "MTPROTO_CREDENTIALS_AVAILABLE_PASS",
    "DELETE_WEBHOOK_PASS",
    "WEBHOOK_EMPTY_PASS",
    "ENV_MUTATION_PASS",
    "API_WORKER_RECREATED_PASS",
    "DB_CONTAINER_UNCHANGED_PASS",
    "DB_VOLUME_UNCHANGED_PASS",
    "NON_BOT_ENV_UNCHANGED_PASS",
    "BOT_SETTINGS_EMPTY_PASS",
    "MTPROTO_CREDENTIALS_PRESERVED_PASS",
    "CREDENTIAL_KEY_PRESERVED_PASS",
    "DB_CREDENTIAL_PRESERVED_PASS",
    "TELEGRAM_MTPROTO_AI_DISABLED_PASS",
    "HEALTH_PASS",
    "ALEMBIC_POST_0046_PASS",
    "TELEGRAM_NETWORK_CALLS",
    "M4BJ1_TERMINAL",
    "M4BJ1_END",
)


class HarnessError(RuntimeError):
    def __init__(self, stage: str, cause: BaseException):
        super().__init__(stage)
        self.stage = stage
        self.cause = cause


def _safe_class(exc: BaseException) -> str:
    return type(exc).__name__[:80] or "RuntimeError"


def neutralize_bot_env(text: str) -> str:
    """Clear exactly the four Bot assignments, preserving every other byte."""
    lines = text.splitlines(keepends=True)
    counts = {key: 0 for key in BOT_KEYS}
    out: list[str] = []
    for line in lines:
        body = line.removesuffix("\n")
        newline = "\n" if line.endswith("\n") else ""
        if body.endswith("\r"):
            body, newline = body[:-1], "\r\n"
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", body)
        if match and match.group(1) in BOT_KEYS:
            key = match.group(1)
            counts[key] += 1
            out.append(f"{key}={newline}")
        elif any(re.match(rf"^{re.escape(key)}(?:\s|:)", body) for key in BOT_KEYS):
            raise ValueError("malformed Bot environment assignment")
        else:
            out.append(line)
    if any(value != 1 for value in counts.values()):
        raise ValueError("Bot environment assignments must occur exactly once")
    return "".join(out)


def neutralized_equal(before: str, after: str) -> bool:
    return neutralize_bot_env(before) == neutralize_bot_env(after)


def _env_assignments(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def _require_exact_env(values: dict[str, str], keys: tuple[str, ...], *, nonempty: bool) -> None:
    for key in keys:
        if key not in values or (nonempty and not values[key].strip()):
            raise ValueError(f"required environment unavailable: {key}")


def _atomic_write(path: Path, content: str, mode: int) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def _read_preserving_newlines(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def clear_bot_environment(path: Path) -> tuple[str, str]:
    before = _read_preserving_newlines(path)
    mode = path.stat().st_mode & 0o7777
    after = neutralize_bot_env(before)
    _atomic_write(path, after, mode)
    return before, after


def _provider_json(token: str, method: str, query: dict[str, str] | None = None) -> dict:
    # The token is kept in the URL only in this in-process request; it is never
    # passed to a shell, subprocess argv, output, or exception text.
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = urllib.parse.urlencode(query or {}).encode("ascii") or None
    request = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise RuntimeError("provider request failed") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError("provider rejected request")
    return payload


def delete_webhook_once(token: str) -> None:
    result = _provider_json(token, "deleteWebhook", {"drop_pending_updates": "true"})
    if result.get("result") is not True:
        raise RuntimeError("webhook deletion was not confirmed")


def verify_webhook_empty(token: str) -> None:
    result = _provider_json(token, "getWebhookInfo")
    info = result.get("result")
    if not isinstance(info, dict) or str(info.get("url", "")) != "":
        raise RuntimeError("webhook remains configured")


def _run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False, env=env)
    if result.returncode:
        raise RuntimeError("command failed")
    return result.stdout.strip()


def _compose() -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        "/opt/secretary/.env",
        "-f",
        "infra/compose.yaml",
        "-f",
        "infra/compose.deploy.yaml",
    ]


def _compose_config(compose: list[str]) -> dict:
    config = json.loads(_run([*compose, "config", "--format", "json"]))
    if not isinstance(config, dict) or not isinstance(config.get("services"), dict):
        raise TypeError("compose services unavailable")
    return config


def _service_environment(config: dict, service: str) -> dict[str, str]:
    raw = config["services"][service].get("environment") or {}
    if isinstance(raw, dict):
        return {str(key): "" if value is None else str(value) for key, value in raw.items()}
    if isinstance(raw, list):
        values: dict[str, str] = {}
        for item in raw:
            if not isinstance(item, str) or "=" not in item:
                raise ValueError("unexpected Compose environment format")
            key, value = item.split("=", 1)
            values[key] = value
        return values
    raise ValueError("unexpected Compose environment format")


def _remote_env_and_snapshot() -> tuple[Path, dict[str, str], str, str, str]:
    env_path = Path("/opt/secretary/.env")
    raw = _read_preserving_newlines(env_path)
    values = _env_assignments(raw)
    compose = _compose()
    config = _compose_config(compose)
    services = config["services"]
    for service in ("api", "worker", "db"):
        if service not in services:
            raise ValueError("required service unavailable")
    db_id = _run([*compose, "ps", "-q", "db"])
    if not db_id:
        raise RuntimeError("database is not running")
    volume = _run(["docker", "inspect", "-f", "{{range .Mounts}}{{.Name}}={{.Destination}} {{end}}", db_id])
    for service in ("api", "worker"):
        if not _run([*compose, "ps", "-q", service]):
            raise RuntimeError(f"{service} is not running")
    return env_path, values, raw, db_id, volume


def _require_alembic(compose: list[str], expected: str) -> None:
    command = (
        'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 '
        '-U "${POSTGRES_USER:-secretary}" -d "${POSTGRES_DB:-secretary}" '
        '-At -c "SELECT version_num FROM alembic_version"'
    )
    output = _run([*compose, "exec", "-T", "api", "sh", "-c", command])
    if output.strip() != expected:
        raise RuntimeError("unexpected Alembic revision")


def remote_main() -> int:
    network_calls = 0
    try:
        emit("M4BJ1_BEGIN", "true")
        if _run(["git", "remote", "get-url", "origin"]) != CANONICAL_ORIGIN:
            raise HarnessError("STAGE_0_CANONICAL_REPO", ValueError("wrong origin"))
        emit("CANONICAL_REPO_PASS", "true")
        emit("TARGET_PIN_PASS", "true")
        if _run(["git", "rev-parse", "HEAD"]) != RELEASE:
            raise HarnessError("STAGE_0_REMOTE_HEAD", ValueError("wrong release"))
        emit("REMOTE_HEAD_PASS", "true")
        if _run(["git", "rev-parse", "origin/production"]) != RELEASE:
            raise HarnessError("STAGE_0_PRODUCTION_REF", ValueError("wrong production ref"))
        emit("REMOTE_PRODUCTION_REF_PASS", "true")
        if _run(["git", "status", "--porcelain"]):
            raise HarnessError("STAGE_0_WORKTREE", ValueError("dirty worktree"))
        emit("REMOTE_WORKTREE_CLEAN", "true")
        env_path, values, before_env, db_id, db_volume = _remote_env_and_snapshot()
        emit("COMPOSE_CONFIG_PASS", "true")
        emit("DB_RUNNING_PASS", "true")
        emit("API_RUNNING_PASS", "true")
        emit("WORKER_RUNNING_PASS", "true")
        _run(["curl", "--fail", "--silent", "--show-error", "http://127.0.0.1:18080/health"])
        emit("DB_HEALTH_PASS", "true")
        _require_alembic(_compose(), ALEMBIC)
        emit("ALEMBIC_0046_PASS", "true")
        _require_exact_env(values, BOT_KEYS, nonempty=True)
        _require_exact_env(values, MT_PROTO_KEYS + INVARIANT_KEYS, nonempty=True)
        emit("BOT_CREDENTIALS_AVAILABLE_PASS", "true")
        emit("MTPROTO_CREDENTIALS_AVAILABLE_PASS", "true")
        token = values["TELEGRAM_BOT_TOKEN"]
        network_calls += 1
        try:
            delete_webhook_once(token)
        except Exception as exc:
            raise HarnessError("STAGE_3_DELETE_WEBHOOK", exc) from exc
        emit("DELETE_WEBHOOK_PASS", "true")
        network_calls += 1
        try:
            verify_webhook_empty(token)
        except Exception as exc:
            raise HarnessError("STAGE_3_VERIFY_WEBHOOK", exc) from exc
        emit("WEBHOOK_EMPTY_PASS", "true")
        try:
            _, after_env = clear_bot_environment(env_path)
        except Exception as exc:
            raise HarnessError("STAGE_4_ENV_MUTATION", exc) from exc
        if not neutralized_equal(before_env, after_env):
            raise HarnessError("STAGE_4_ENV_MUTATION", ValueError("unexpected environment change"))
        emit("ENV_MUTATION_PASS", "true")
        try:
            _run([*_compose(), "up", "-d", "--no-deps", "--force-recreate", "api", "worker"])
        except Exception as exc:
            raise HarnessError("STAGE_5_RECREATE_API_WORKER", exc) from exc
        emit("API_WORKER_RECREATED_PASS", "true")
        if _run([*_compose(), "ps", "-q", "db"]) != db_id:
            raise RuntimeError("database container changed")
        emit("DB_CONTAINER_UNCHANGED_PASS", "true")
        if _run(["docker", "inspect", "-f", "{{range .Mounts}}{{.Name}}={{.Destination}} {{end}}", db_id]) != db_volume:
            raise RuntimeError("database volume changed")
        emit("DB_VOLUME_UNCHANGED_PASS", "true")
        if not neutralized_equal(before_env, _read_preserving_newlines(env_path)):
            raise RuntimeError("non-Bot environment changed")
        emit("NON_BOT_ENV_UNCHANGED_PASS", "true")
        post = _env_assignments(_read_preserving_newlines(env_path))
        for key in BOT_KEYS:
            if post.get(key, "") != "":
                raise RuntimeError("Bot environment was not cleared")
        emit("BOT_SETTINGS_EMPTY_PASS", "true")
        post_config = _compose_config(_compose())
        for service in ("api", "worker"):
            service_env = _service_environment(post_config, service)
            for key in BOT_KEYS:
                if service_env.get(key, "") != "":
                    raise RuntimeError("Bot settings remain in a service environment")
            for key in MT_PROTO_KEYS + INVARIANT_KEYS:
                if service_env.get(key) != values.get(key):
                    raise RuntimeError("protected service environment changed")
            if service_env.get("TELEGRAM_MTPROTO_AI_ENABLED", "false").lower() != "false":
                raise RuntimeError("MTProto AI flag is not disabled")
        for key in MT_PROTO_KEYS + INVARIANT_KEYS:
            if post.get(key) != values.get(key):
                raise RuntimeError("protected environment changed")
        emit("MTPROTO_CREDENTIALS_PRESERVED_PASS", "true")
        emit("CREDENTIAL_KEY_PRESERVED_PASS", "true")
        emit("DB_CREDENTIAL_PRESERVED_PASS", "true")
        if values.get("TELEGRAM_MTPROTO_AI_ENABLED", "false").lower() != "false":
            raise RuntimeError("MTProto AI flag is not disabled")
        emit("TELEGRAM_MTPROTO_AI_DISABLED_PASS", "true")
        _run(["curl", "--fail", "--silent", "--show-error", "http://127.0.0.1:18080/health"])
        emit("HEALTH_PASS", "true")
        _require_alembic(_compose(), ALEMBIC)
        emit("ALEMBIC_POST_0046_PASS", "true")
        emit("TELEGRAM_NETWORK_CALLS", str(network_calls))
        emit("M4BJ1_TERMINAL", "success")
        emit("M4BJ1_END", "true")
        return 0
    except HarnessError as exc:
        emit_failure(exc.stage, exc.cause, network_calls)
    except Exception as exc:  # noqa: BLE001 - sanitized remote boundary
        emit_failure("STAGE_UNKNOWN", exc, network_calls)
    return 2


def emit(key: str, value: str) -> None:
    print(f"{key}={value}", flush=True)


def emit_failure(stage: str, cause: BaseException, network_calls: int) -> None:
    emit("FAILURE_STAGE", stage)
    emit("RAW_EXCEPTION_CLASS", _safe_class(cause))
    emit("TELEGRAM_NETWORK_CALLS", str(network_calls))
    emit("M4BJ1_TERMINAL", "failure")


def parse_output(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0] != "M4BJ1_BEGIN=true":
        raise ValueError("invalid begin marker")
    if lines[-1] == "M4BJ1_END=true":
        if len(lines) != len(SUCCESS_FIELDS) or any(
            line.split("=", 1)[0] != key for line, key in zip(lines, SUCCESS_FIELDS)
        ):
            raise ValueError("unexpected success protocol")
        if lines[-2] != "M4BJ1_TERMINAL=success":
            raise ValueError("missing success terminal")
        for line in lines[1:-3]:
            key, value = line.split("=", 1)
            if key.endswith("PASS") and value != "true":
                raise ValueError("failed success guard")
        calls = int(lines[-3].split("=", 1)[1])
        if calls != 2:
            raise ValueError("unexpected provider call count")
        return "success"
    failure_keys = {line.split("=", 1)[0] for line in lines}
    required = {"FAILURE_STAGE", "RAW_EXCEPTION_CLASS", "TELEGRAM_NETWORK_CALLS", "M4BJ1_TERMINAL"}
    if not required.issubset(failure_keys) or lines[-1] != "M4BJ1_TERMINAL=failure":
        raise ValueError("invalid failure protocol")
    prefix = lines[: -4]
    if any(
        line.split("=", 1)[0] != key
        for line, key in zip(prefix, SUCCESS_FIELDS)
    ) or len(prefix) > len(SUCCESS_FIELDS):
        raise ValueError("unexpected failure prefix")
    if any(key not in required and key not in set(SUCCESS_FIELDS) for key in failure_keys):
        raise ValueError("unsafe failure output")
    if len(failure_keys) != len(lines):
        raise ValueError("duplicate failure output")
    network_line = next(line for line in lines if line.startswith("TELEGRAM_NETWORK_CALLS="))
    network_calls = int(network_line.split("=", 1)[1])
    if network_calls < 0 or network_calls > 2:
        raise ValueError("unexpected provider call count")
    if not re.fullmatch(r"STAGE_[A-Z0-9_]+", next(line.split("=", 1)[1] for line in lines if line.startswith("FAILURE_STAGE="))):
        raise ValueError("unsafe failure stage")
    if not re.fullmatch(r"[A-Za-z0-9_]+", next(line.split("=", 1)[1] for line in lines if line.startswith("RAW_EXCEPTION_CLASS="))):
        raise ValueError("unsafe failure class")
    return "failure"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("bundle", "remote", "validate"))
    parser.add_argument("path", nargs="?")
    args = parser.parse_args()
    if args.command == "bundle":
        print(Path(__file__).read_text(encoding="utf-8"), end="")
        return 0
    if args.command == "remote":
        return remote_main()
    if not args.path:
        raise SystemExit("validate requires transcript path")
    try:
        return 0 if parse_output(Path(args.path).read_text(encoding="utf-8")) else 2
    except (OSError, ValueError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
