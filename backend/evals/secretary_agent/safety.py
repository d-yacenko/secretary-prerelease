"""AH2-MR1 guards. They do not print secrets or open a database."""

from __future__ import annotations

import re
from typing import Any

from evals.secretary_agent.models import EvalRun

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_SECRET_KEYS = re.compile(
    r"(api[_-]?key|password|secret|(?:^|_)token(?:_|$)|authorization|dsn|database_url|credential)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_CREDENTIAL_DSN = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s/]+@", re.IGNORECASE)
_FORBIDDEN_KEYS = frozenset(
    {
        "chain_of_thought",
        "reasoning_trace",
        "hidden_reasoning",
        "raw_request",
        "raw_response",
        "provider_request",
        "provider_response",
        "wire_payload",
        "production_user_id",
        "production_user",
    }
)
_PUBLIC_CONFIG_KEYS = frozenset(
    {
        "model",
        "reasoning_effort",
        "verbosity",
        "max_rounds",
        "max_output_tokens",
        "reference_datetime",
        "timezone",
        "mode",
        "system_instructions",
        "tool_definitions",
        "instructions_chars",
    }
)
_LIVE_TRANSPORTS = frozenset(
    {
        "GmailTransport",
        "SmtpTransport",
        "ImapTransport",
        "CalDavTransport",
        "MattermostTransport",
        "TeamsTransport",
        "TelegramMtprotoTransport",
    }
)


class EvalSafetyError(RuntimeError):
    pass


def assert_eval_database(engine: Any, *, disposable: bool) -> dict[str, str]:
    if disposable is not True:
        raise EvalSafetyError("database target is not explicitly classified as eval/disposable")
    url = getattr(engine, "url", None)
    host = str(getattr(url, "host", "") or "").strip().lower()
    database = str(getattr(url, "database", "") or "").strip()
    if host not in _LOCAL_HOSTS or "web-itx.duckdns.org" in host:
        raise EvalSafetyError("database host is not a local disposable target")
    if not database:
        raise EvalSafetyError("database name is not classified as local/disposable")
    return {"host": host, "database": database, "disposable": "true"}


def build_safe_artifact_payload(run: EvalRun, public_config: dict[str, Any]) -> dict[str, Any]:
    if set(public_config) - _PUBLIC_CONFIG_KEYS:
        raise EvalSafetyError("artifact config is outside the public allowlist")
    _reject_mapping(public_config)
    payload = {
        "scenario_id": run.scenario_id,
        "utterance": run.utterance,
        "run_id": run.run_id,
        "calls": [call.model_dump(mode="json") for call in run.calls],
        "symbols": dict(run.symbols),
        "final_facts": dict(run.final_facts),
        "final_answer": run.final_answer,
        "model": run.model,
        "config": {key: public_config[key] for key in sorted(_PUBLIC_CONFIG_KEYS) if key in public_config},
    }
    _reject_mapping(payload)
    return payload


def assert_dry_run_transports(transports: tuple[object, ...]) -> None:
    for transport in transports:
        name = type(transport).__name__
        if name in _LIVE_TRANSPORTS or not name.startswith("Fake"):
            raise EvalSafetyError("scripted dry run cannot use a live transport")


def assert_no_secrets(payload: Any) -> None:
    if _secret_paths(payload) or _SECRET_VALUE.search(repr(payload)) or _CREDENTIAL_DSN.search(repr(payload)):
        raise EvalSafetyError("artifact contains secret fields")


def _reject_mapping(payload: Any) -> None:
    for key in _keys(payload):
        normalized = key.lower()
        if normalized in _FORBIDDEN_KEYS or normalized.startswith("production_"):
            raise EvalSafetyError("artifact contains a forbidden field")
    assert_no_secrets(payload)


def _keys(payload: Any) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.append(str(key))
            found.extend(_keys(value))
    elif isinstance(payload, list):
        for value in payload:
            found.extend(_keys(value))
    return found


def _secret_paths(payload: Any) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _SECRET_KEYS.search(str(key)):
                found.append(str(key))
            found.extend(_secret_paths(value))
    elif isinstance(payload, list):
        for value in payload:
            found.extend(_secret_paths(value))
    return found
