#!/usr/bin/env python3
"""Read-only HG2 repair preflight. Streamed only by hg2_repair_preflight.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path("/opt/secretary")
CANONICAL_ORIGIN = "https://github.com/d-yacenko/secretary-prerelease.git"
PRODUCTION_SHA = "f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6"
EXPECTED_ALEMBIC = "0054"
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(REPO / ".env"),
    "-f",
    "infra/compose.yaml",
    "-f",
    "infra/compose.deploy.yaml",
]
BLOCKED_STAGES = {
    "arguments",
    "cwd",
    "origin",
    "worktree",
    "head",
    "production_ref",
    "db_running",
    "api_running",
    "worker_running",
    "db_health",
    "api_health",
    "alembic",
    "command",
    "read_only",
    "census_output",
}

CLASSIFIER_SOURCE = r'''
from uuid import UUID

FACT_ORDER = (
    "TELEGRAM_ACCOUNTS",
    "TELEGRAM_COARSE_CANDIDATES",
    "TELEGRAM_LOCAL_REPAIRABLE",
    "TELEGRAM_HIDDEN",
    "TELEGRAM_INVALID_PROVENANCE",
    "TELEGRAM_ALREADY_ENRICHED",
    "TELEGRAM_ACCOUNTS_WITH_LOCAL_REPAIRABLE",
    "TELEGRAM_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT",
    "MATTERMOST_ACCOUNTS",
    "MATTERMOST_COARSE_CANDIDATES",
    "MATTERMOST_LOCAL_REPAIRABLE",
    "MATTERMOST_HIDDEN",
    "MATTERMOST_INVALID_PROVENANCE",
    "MATTERMOST_ALREADY_ENRICHED",
    "MATTERMOST_ACCOUNTS_WITH_LOCAL_REPAIRABLE",
    "MATTERMOST_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT",
    "TEAMS_ACCOUNTS",
    "TEAMS_COARSE_CANDIDATES",
    "TEAMS_LOCAL_REPAIRABLE",
    "TEAMS_HIDDEN",
    "TEAMS_INVALID_PROVENANCE",
    "TEAMS_ALREADY_ENRICHED",
    "TEAMS_ACCOUNTS_WITH_LOCAL_REPAIRABLE",
    "TEAMS_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT",
    "GMAIL_ACCOUNTS",
    "GMAIL_ATTRIBUTABLE",
    "GMAIL_COARSE_CANDIDATES",
    "GMAIL_LOCAL_REPAIRABLE",
    "GMAIL_HIDDEN",
    "GMAIL_INVALID_PROVENANCE",
    "GMAIL_ALREADY_ENRICHED",
    "GMAIL_UNATTRIBUTABLE",
    "GMAIL_UNMATCHED_SOURCE_ACCOUNT",
    "GMAIL_ACCOUNTS_WITH_LOCAL_REPAIRABLE",
    "GMAIL_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT",
    "YANDEX_ACCOUNTS",
    "YANDEX_COARSE_CANDIDATES",
    "YANDEX_LOCAL_REPAIRABLE",
    "YANDEX_HIDDEN",
    "YANDEX_INVALID_PROVENANCE",
    "YANDEX_ALREADY_ENRICHED",
    "YANDEX_STORED_UIDVALIDITY_MATCH",
    "YANDEX_STORED_UIDVALIDITY_DIFFER",
    "YANDEX_STORED_UIDVALIDITY_UNVERIFIED",
    "YANDEX_UNATTRIBUTABLE",
    "YANDEX_NON_INBOX_OUTSIDE_REPAIR",
    "YANDEX_ACCOUNTS_WITH_LOCAL_REPAIRABLE",
    "YANDEX_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT",
)


class PreflightError(RuntimeError):
    def __init__(self, stage):
        self.stage = stage
        super().__init__(stage)


def require_transaction_read_only(value):
    if value != "on":
        raise PreflightError("read_only")


def _sid(value):
    return "" if value is None else str(value)


def _meta(row):
    metadata = row.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _tombstoned(row):
    return row.get("deleted_at") is not None


def _hidden(row):
    return row.get("status") == "deleted"


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _json_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _nonempty(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _blank_source(metadata):
    return _nonempty(metadata.get("source_account_email")) is None


def _kind_missing(metadata):
    return "sender_kind" not in metadata or metadata.get("sender_kind") is None


def _display_blank(metadata):
    return _nonempty(metadata.get("author_display_name")) is None


def _author_id(metadata):
    return _nonempty(metadata.get("author_user_id"))


def _gmail_key_present(metadata, key):
    return key in metadata


def _yandex_key_present(metadata, key):
    return key in metadata


def _teams_external(tenant_id, microsoft_user_id, chat_id, message_id):
    try:
        tenant = str(UUID(str(tenant_id).strip()))
        user = str(UUID(str(microsoft_user_id).strip()))
    except (ValueError, AttributeError):
        return None
    return f"{tenant}|{user}|{chat_id}|{message_id}"


def _yandex_external(uidvalidity, uid):
    return f"inbox:{uidvalidity}:{uid}"


def _account_extent(counts):
    positive = [count for count in counts.values() if count > 0]
    if not positive:
        return 0, 0
    return len(positive), max(positive)


def _bump(counts, account_id):
    counts[account_id] = counts.get(account_id, 0) + 1


def census(
    objects,
    telegram_accounts,
    telegram_selections,
    mattermost_accounts,
    teams_accounts,
    gmail_accounts,
    yandex_accounts,
):
    facts = {key: 0 for key in FACT_ORDER}
    facts["TELEGRAM_ACCOUNTS"] = len(telegram_accounts)
    facts["MATTERMOST_ACCOUNTS"] = len(mattermost_accounts)
    facts["TEAMS_ACCOUNTS"] = len(teams_accounts)
    facts["GMAIL_ACCOUNTS"] = len(gmail_accounts)
    facts["YANDEX_ACCOUNTS"] = len(yandex_accounts)

    telegram_by_key = {
        (_sid(row["user_id"]), _sid(row["id"])): row for row in telegram_accounts
    }
    active_peers = {
        (_sid(row["account_id"]), _json_int(row.get("peer_id")))
        for row in telegram_selections
        if row.get("scope_active") is True and _json_int(row.get("peer_id")) is not None
    }
    mattermost_by_key = {
        (_sid(row["user_id"]), _sid(row["id"]), row.get("server_url")): row
        for row in mattermost_accounts
    }
    teams_by_key = {
        (
            _sid(row["user_id"]),
            _sid(row["id"]),
            row.get("tenant_id"),
            row.get("microsoft_user_id"),
        ): row
        for row in teams_accounts
    }
    gmail_by_key = {
        (_sid(row["user_id"]), row.get("email")): row for row in gmail_accounts
    }
    yandex_by_key = {
        (_sid(row["user_id"]), row.get("email")): row for row in yandex_accounts
    }
    telegram_counts = {}
    mattermost_counts = {}
    teams_counts = {}
    gmail_counts = {}
    yandex_counts = {}

    for row in objects:
        if _tombstoned(row):
            continue
        provider = row.get("provider")
        kind = row.get("kind")
        metadata = _meta(row)
        user_id = _sid(row.get("user_id"))
        if provider == "telegram" and kind == "chat_message":
            _classify_telegram(
                facts,
                telegram_counts,
                telegram_by_key,
                active_peers,
                row,
                metadata,
                user_id,
            )
        elif provider == "mattermost" and kind == "chat_message":
            _classify_mattermost(
                facts,
                mattermost_counts,
                mattermost_by_key,
                metadata,
                user_id,
                row,
            )
        elif provider == "teams" and kind == "chat_message":
            _classify_teams(
                facts,
                teams_counts,
                teams_by_key,
                row,
                metadata,
                user_id,
            )
        elif provider == "gmail" and kind == "email":
            _classify_gmail(
                facts,
                gmail_counts,
                gmail_by_key,
                row,
                metadata,
                user_id,
            )
        elif provider == "yandex_mail" and kind == "email":
            _classify_yandex(
                facts,
                yandex_counts,
                yandex_by_key,
                row,
                metadata,
                user_id,
            )

    _finish_extent(
        facts,
        "TELEGRAM",
        telegram_counts,
    )
    _finish_extent(facts, "MATTERMOST", mattermost_counts)
    _finish_extent(facts, "TEAMS", teams_counts)
    _finish_extent(facts, "GMAIL", gmail_counts)
    _finish_extent(facts, "YANDEX", yandex_counts)
    repairable = facts["YANDEX_LOCAL_REPAIRABLE"]
    stored = (
        facts["YANDEX_STORED_UIDVALIDITY_MATCH"]
        + facts["YANDEX_STORED_UIDVALIDITY_DIFFER"]
        + facts["YANDEX_STORED_UIDVALIDITY_UNVERIFIED"]
    )
    if stored != repairable:
        raise PreflightError("census_output")
    return facts


def _finish_extent(facts, prefix, counts):
    accounts, maximum = _account_extent(counts)
    facts[f"{prefix}_ACCOUNTS_WITH_LOCAL_REPAIRABLE"] = accounts
    facts[f"{prefix}_MAX_LOCAL_REPAIRABLE_PER_ACCOUNT"] = maximum


def _classify_telegram(facts, counts, accounts, active_peers, row, metadata, user_id):
    if metadata.get("transport") != "mtproto" or metadata.get("direction") != "inbound":
        return
    account = accounts.get((user_id, _sid(metadata.get("account_id"))))
    if account is None:
        return
    if not _kind_missing(metadata):
        facts["TELEGRAM_ALREADY_ENRICHED"] += 1
        return
    facts["TELEGRAM_COARSE_CANDIDATES"] += 1
    if _hidden(row):
        facts["TELEGRAM_HIDDEN"] += 1
        return
    peer_id = _json_int(metadata.get("peer_id"))
    message_id = _positive_int(metadata.get("message_id"))
    if (
        message_id is None
        or peer_id is None
        or ( _sid(account["id"]), peer_id) not in active_peers
    ):
        facts["TELEGRAM_INVALID_PROVENANCE"] += 1
        return
    facts["TELEGRAM_LOCAL_REPAIRABLE"] += 1
    _bump(counts, _sid(account["id"]))


def _classify_mattermost(facts, counts, accounts, metadata, user_id, row):
    account = accounts.get((user_id, _sid(metadata.get("account_id")), metadata.get("server_url")))
    if account is None:
        return
    if not _display_blank(metadata):
        facts["MATTERMOST_ALREADY_ENRICHED"] += 1
        return
    facts["MATTERMOST_COARSE_CANDIDATES"] += 1
    if _hidden(row):
        facts["MATTERMOST_HIDDEN"] += 1
        return
    if _author_id(metadata) is None:
        facts["MATTERMOST_INVALID_PROVENANCE"] += 1
        return
    facts["MATTERMOST_LOCAL_REPAIRABLE"] += 1
    _bump(counts, _sid(account["id"]))


def _classify_teams(facts, counts, accounts, row, metadata, user_id):
    account = accounts.get(
        (
            user_id,
            _sid(metadata.get("account_id")),
            metadata.get("tenant_id"),
            metadata.get("teams_user_id"),
        )
    )
    if account is None or metadata.get("direction") != "inbound":
        return
    if not _kind_missing(metadata):
        facts["TEAMS_ALREADY_ENRICHED"] += 1
        return
    facts["TEAMS_COARSE_CANDIDATES"] += 1
    if _hidden(row):
        facts["TEAMS_HIDDEN"] += 1
        return
    if _teams_target(account, row, metadata) is None:
        facts["TEAMS_INVALID_PROVENANCE"] += 1
        return
    facts["TEAMS_LOCAL_REPAIRABLE"] += 1
    _bump(counts, _sid(account["id"]))


def _teams_target(account, row, metadata):
    chat_id = _nonempty(metadata.get("chat_id"))
    message_id = _nonempty(metadata.get("message_id"))
    sender_id = _nonempty(metadata.get("sender_id"))
    display = _nonempty(metadata.get("sender_display_name"))
    if chat_id is None or message_id is None or sender_id is None or display is None:
        return None
    expected = _teams_external(
        account.get("tenant_id"),
        account.get("microsoft_user_id"),
        chat_id,
        message_id,
    )
    if expected is None or row.get("external_id") != expected:
        return None
    return expected


def _classify_gmail(facts, counts, accounts, row, metadata, user_id):
    if _blank_source(metadata):
        facts["GMAIL_UNATTRIBUTABLE"] += 1
        return
    account = accounts.get((user_id, metadata.get("source_account_email")))
    if account is None:
        facts["GMAIL_UNMATCHED_SOURCE_ACCOUNT"] += 1
        return
    facts["GMAIL_ATTRIBUTABLE"] += 1
    both = _gmail_key_present(metadata, "to_participants") and _gmail_key_present(
        metadata, "cc_participants"
    )
    if both:
        facts["GMAIL_ALREADY_ENRICHED"] += 1
        return
    facts["GMAIL_COARSE_CANDIDATES"] += 1
    if _hidden(row):
        facts["GMAIL_HIDDEN"] += 1
        return
    if _gmail_message_id(row, metadata) is None:
        facts["GMAIL_INVALID_PROVENANCE"] += 1
        return
    facts["GMAIL_LOCAL_REPAIRABLE"] += 1
    _bump(counts, _sid(account["id"]))


def _gmail_message_id(row, metadata):
    message_id = metadata.get("message_id")
    external_id = row.get("external_id")
    if not isinstance(message_id, str) or not message_id.strip():
        return None
    if not isinstance(external_id, str) or not external_id.strip():
        return None
    if external_id != message_id:
        return None
    return message_id


def _classify_yandex(facts, counts, accounts, row, metadata, user_id):
    if _blank_source(metadata):
        facts["YANDEX_UNATTRIBUTABLE"] += 1
        return
    missing_structured = not (
        _yandex_key_present(metadata, "to_participants")
        and _yandex_key_present(metadata, "cc_participants")
    )
    if metadata.get("folder") != "INBOX":
        if missing_structured:
            facts["YANDEX_NON_INBOX_OUTSIDE_REPAIR"] += 1
        return
    account = accounts.get((user_id, metadata.get("source_account_email")))
    if account is None:
        return
    if not missing_structured:
        facts["YANDEX_ALREADY_ENRICHED"] += 1
        return
    facts["YANDEX_COARSE_CANDIDATES"] += 1
    if _hidden(row):
        facts["YANDEX_HIDDEN"] += 1
        return
    structural = _yandex_structural(row, metadata)
    if structural is None:
        facts["YANDEX_INVALID_PROVENANCE"] += 1
        return
    facts["YANDEX_LOCAL_REPAIRABLE"] += 1
    _bump(counts, _sid(account["id"]))
    stored = _positive_int((account.get("sync_state") or {}).get("inbox_uidvalidity"))
    if stored is None:
        facts["YANDEX_STORED_UIDVALIDITY_UNVERIFIED"] += 1
    elif stored == structural:
        facts["YANDEX_STORED_UIDVALIDITY_MATCH"] += 1
    else:
        facts["YANDEX_STORED_UIDVALIDITY_DIFFER"] += 1


def _yandex_structural(row, metadata):
    uid = _positive_int(metadata.get("imap_uid"))
    uidvalidity = _positive_int(metadata.get("imap_uidvalidity"))
    if uid is None or uidvalidity is None:
        return None
    if row.get("external_id") != _yandex_external(uidvalidity, uid):
        return None
    return uidvalidity
'''

ADAPTER_SOURCE = r'''
def _mapping(user_id, provider, kind, external_id, deleted_at, status, metadata):
    return {
        "user_id": user_id,
        "provider": provider,
        "kind": kind,
        "external_id": external_id,
        "deleted_at": deleted_at,
        "status": status,
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def _read_only_facts():
    from sqlalchemy import select, text

    from app.db.models import (
        GoogleAccount,
        MattermostAccount,
        Object,
        TeamsAccount,
        TelegramMtprotoAccount,
        TelegramMtprotoChatSelection,
        YandexMailAccount,
    )
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        mode = session.scalar(text("SHOW transaction_read_only"))
        require_transaction_read_only(mode)
        objects = [
            _mapping(*row)
            for row in session.execute(
                select(
                    Object.user_id,
                    Object.provider,
                    Object.kind,
                    Object.external_id,
                    Object.deleted_at,
                    Object.status,
                    Object.metadata_,
                ).where(Object.deleted_at.is_(None))
            )
        ]
        telegram_accounts = [
            {"id": item_id, "user_id": user_id}
            for item_id, user_id in session.execute(
                select(TelegramMtprotoAccount.id, TelegramMtprotoAccount.user_id)
            )
        ]
        telegram_selections = [
            {"account_id": account_id, "peer_id": peer_id, "scope_active": scope_active}
            for account_id, peer_id, scope_active in session.execute(
                select(
                    TelegramMtprotoChatSelection.account_id,
                    TelegramMtprotoChatSelection.peer_id,
                    TelegramMtprotoChatSelection.scope_active,
                )
            )
        ]
        mattermost_accounts = [
            {"id": item_id, "user_id": user_id, "server_url": server_url}
            for item_id, user_id, server_url in session.execute(
                select(
                    MattermostAccount.id,
                    MattermostAccount.user_id,
                    MattermostAccount.server_url,
                )
            )
        ]
        teams_accounts = [
            {
                "id": item_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "microsoft_user_id": microsoft_user_id,
            }
            for item_id, user_id, tenant_id, microsoft_user_id in session.execute(
                select(
                    TeamsAccount.id,
                    TeamsAccount.user_id,
                    TeamsAccount.tenant_id,
                    TeamsAccount.microsoft_user_id,
                )
            )
        ]
        gmail_accounts = [
            {"id": item_id, "user_id": user_id, "email": email}
            for item_id, user_id, email in session.execute(
                select(GoogleAccount.id, GoogleAccount.user_id, GoogleAccount.email)
            )
        ]
        yandex_accounts = [
            {
                "id": item_id,
                "user_id": user_id,
                "email": email,
                "sync_state": sync_state,
            }
            for item_id, user_id, email, sync_state in session.execute(
                select(
                    YandexMailAccount.id,
                    YandexMailAccount.user_id,
                    YandexMailAccount.email,
                    YandexMailAccount.sync_state,
                )
            )
        ]
        return census(
            objects,
            telegram_accounts,
            telegram_selections,
            mattermost_accounts,
            teams_accounts,
            gmail_accounts,
            yandex_accounts,
        )
    finally:
        session.close()


def container_main():
    try:
        facts = _read_only_facts()
    except PreflightError as exc:
        print(f"CHILD_BLOCKED={exc.stage}")
        print("CHILD_ERROR_CLASS=PreflightError")
        return 1
    except Exception as exc:
        print("CHILD_BLOCKED=census_output")
        name = type(exc).__name__
        if name.isascii() and name.isidentifier():
            print(f"CHILD_ERROR_CLASS={name}")
        else:
            print("CHILD_ERROR_CLASS=SanitizedError")
        return 1
    print("CHILD_READ_ONLY=on")
    for key in FACT_ORDER:
        print(f"{key}={facts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(container_main())
'''

_CLASSIFIER: dict = {}
exec(CLASSIFIER_SOURCE, _CLASSIFIER)  # noqa: S102
census = _CLASSIFIER["census"]
FACT_ORDER = _CLASSIFIER["FACT_ORDER"]
PreflightError = _CLASSIFIER["PreflightError"]
require_transaction_read_only = _CLASSIFIER["require_transaction_read_only"]
CHILD_SOURCE = CLASSIFIER_SOURCE + "\n" + ADAPTER_SOURCE


class RemotePreflightError(RuntimeError):
    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__(stage)


def run(command: list[str], *, stdin: str | None = None) -> str:
    result = subprocess.run(
        command,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RemotePreflightError("command")
    return result.stdout.strip()


def git(*args: str) -> str:
    return run(["git", *args])


def compose(*args: str, stdin: str | None = None) -> str:
    return run([*COMPOSE, *args], stdin=stdin)


def require_repository(expected_sha: str) -> None:
    if Path.cwd().resolve() != REPO:
        raise RemotePreflightError("cwd")
    if git("remote", "get-url", "origin") != CANONICAL_ORIGIN:
        raise RemotePreflightError("origin")
    if git("status", "--porcelain"):
        raise RemotePreflightError("worktree")
    if git("rev-parse", "HEAD") != expected_sha:
        raise RemotePreflightError("head")
    if git("rev-parse", "origin/production") != expected_sha:
        raise RemotePreflightError("production_ref")


def require_alembic_output(text: str) -> None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines != [f"{EXPECTED_ALEMBIC} (head)"]:
        raise RemotePreflightError("alembic")


def require_runtime(health_url: str) -> None:
    for service in ("db", "api", "worker"):
        container = compose("ps", "-q", service).strip()
        if not container:
            raise RemotePreflightError(f"{service}_running")
        state = run(["docker", "inspect", "-f", "{{.State.Running}}", container])
        if state != "true":
            raise RemotePreflightError(f"{service}_running")
    db = compose("ps", "-q", "db").strip()
    if run(["docker", "inspect", "-f", "{{.State.Health.Status}}", db]) != "healthy":
        raise RemotePreflightError("db_health")
    body = run(["curl", "-fsS", health_url]).replace(" ", "")
    if '"status":"ok"' not in body:
        raise RemotePreflightError("api_health")
    require_alembic_output(compose("exec", "-T", "api", "alembic", "current"))


def parse_child_output(text: str) -> dict[str, int]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise RemotePreflightError("census_output")
    if lines[0].startswith("CHILD_BLOCKED="):
        stage = lines[0].split("=", 1)[1]
        if stage not in BLOCKED_STAGES or len(lines) != 2:
            raise RemotePreflightError("census_output")
        if not lines[1].startswith("CHILD_ERROR_CLASS="):
            raise RemotePreflightError("census_output")
        raise RemotePreflightError(stage)
    if lines[0] != "CHILD_READ_ONLY=on":
        raise RemotePreflightError("read_only")
    if len(lines) != 1 + len(FACT_ORDER):
        raise RemotePreflightError("census_output")
    facts: dict[str, int] = {}
    for line, key in zip(lines[1:], FACT_ORDER, strict=True):
        prefix = f"{key}="
        if not line.startswith(prefix) or not line[len(prefix) :].isdecimal():
            raise RemotePreflightError("census_output")
        value_text = line[len(prefix) :]
        if value_text != "0" and value_text.startswith("0"):
            raise RemotePreflightError("census_output")
        facts[key] = int(value_text)
    return facts


def run_child() -> dict[str, int]:
    output = compose("exec", "-T", "api", "python3", "-", stdin=CHILD_SOURCE)
    return parse_child_output(output)


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != PRODUCTION_SHA:
        print("HG2_PREFLIGHT_BLOCKED=arguments", flush=True)
        print("HG2_PREFLIGHT_ERROR_CLASS=RemotePreflightError", flush=True)
        print("PROVIDER_NETWORK_CALLS=0", flush=True)
        return 1
    try:
        require_repository(sys.argv[1])
        require_runtime(sys.argv[2])
    except RemotePreflightError as exc:
        print(f"HG2_PREFLIGHT_BLOCKED={exc.stage}", flush=True)
        print("HG2_PREFLIGHT_ERROR_CLASS=RemotePreflightError", flush=True)
        print("PROVIDER_NETWORK_CALLS=0", flush=True)
        return 1
    print("HG2_PREFLIGHT_MARKER=started", flush=True)
    try:
        facts = run_child()
    except RemotePreflightError as exc:
        print(f"HG2_PREFLIGHT_BLOCKED={exc.stage}", flush=True)
        print("HG2_PREFLIGHT_ERROR_CLASS=RemotePreflightError", flush=True)
        print("PROVIDER_NETWORK_CALLS=0", flush=True)
        return 1
    print("HG2_PREFLIGHT_GUARDS=pass", flush=True)
    print("HG2_PREFLIGHT_READ_ONLY=on", flush=True)
    for key in FACT_ORDER:
        print(f"{key}={facts[key]}", flush=True)
    print("YANDEX_PROVIDER_UIDVALIDITY_KNOWN=false", flush=True)
    print("PROVIDER_NETWORK_CALLS=0", flush=True)
    print("HG2_PREFLIGHT_TERMINAL=success", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
