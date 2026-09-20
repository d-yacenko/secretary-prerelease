#!/usr/bin/env bash
set -euo pipefail

CANONICAL_ORIGIN="https://github.com/d-yacenko/secretary-prerelease.git"
DEFAULT_RELEASE="23fa07df213d5a70a6dc1d3c8b32af39228107eb"
EXPECTED_RELEASE="${1:-$DEFAULT_RELEASE}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET_FILE="$SCRIPT_DIR/target.json"

fail() {
  printf 'MANUAL_M4AN2_BLOCKED=%s\n' "$1"
  exit 2
}

for cmd in git python3 ssh ssh-keyscan ssh-keygen mktemp; do
  command -v "$cmd" >/dev/null 2>&1 || fail "missing_${cmd}"
done

case "$EXPECTED_RELEASE" in
  ''|*[!0-9a-f]*) fail "invalid_expected_release" ;;
esac
[ "${#EXPECTED_RELEASE}" -eq 40 ] || fail "invalid_expected_release"

[ -f "$TARGET_FILE" ] || fail "target_missing"

origin="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)"
[ "$origin" = "$CANONICAL_ORIGIN" ] || fail "wrong_local_origin"

readarray -t target_values < <(python3 - "$TARGET_FILE" <<'PY'
import json
import sys
from pathlib import Path

p = Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
for key in ("ssh_target", "ssh_port", "host_key_sha256", "repository_path"):
    print(data[key])
PY
)

[ "${#target_values[@]}" -eq 4 ] || fail "target_parse"
SSH_TARGET="${target_values[0]}"
SSH_PORT="${target_values[1]}"
EXPECTED_PIN="${target_values[2]}"
REMOTE_REPO="${target_values[3]}"

[ "$SSH_TARGET" = "root@web-itx.duckdns.org" ] || fail "target_mismatch"
[ "$SSH_PORT" = "22" ] || fail "port_mismatch"
[ "$REMOTE_REPO" = "/opt/secretary" ] || fail "repo_path_mismatch"

HOST="${SSH_TARGET#*@}"
TMPDIR_LOCAL="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_LOCAL"' EXIT
SCAN="$TMPDIR_LOCAL/scan"
KNOWN="$TMPDIR_LOCAL/known_hosts"
SSH_ERR="$TMPDIR_LOCAL/ssh.stderr"

ssh-keyscan -T 5 -p "$SSH_PORT" "$HOST" >"$SCAN" 2>/dev/null || true
: >"$KNOWN"

while IFS= read -r line; do
  [ -n "$line" ] || continue
  case "$line" in \#*) continue ;; esac
  one="$TMPDIR_LOCAL/one"
  printf '%s\n' "$line" >"$one"
  fp="$(ssh-keygen -lf "$one" -E sha256 2>/dev/null | awk 'NR==1 {print $2}')"
  if [ "$fp" = "$EXPECTED_PIN" ]; then
    printf '%s\n' "$line" >>"$KNOWN"
  fi
done <"$SCAN"

[ -s "$KNOWN" ] || fail "host_key_pin_mismatch"

printf '%s\n' 'MANUAL_M4AN2_BEGIN=true'
printf '%s\n' 'CANONICAL_REPO_PASS=true'
printf '%s\n' 'TARGET_PIN_PASS=true'

REMOTE_HELPER="$TMPDIR_LOCAL/remote.sh"
# Stream the same closed protocol validator to the remote shell in memory.
PROTOCOL_FILE="$SCRIPT_DIR/manual_mtproto_structural_protocol.py"
[ -f "$PROTOCOL_FILE" ] || fail "protocol_missing"
printf 'PROTOCOL_VALIDATOR=%q\n' "$(cat "$PROTOCOL_FILE")" >"$REMOTE_HELPER"
cat >>"$REMOTE_HELPER" <<'REMOTE'
#!/usr/bin/env bash
set -u

EXPECTED_RELEASE="$1"
REPO="/opt/secretary"
COMPOSE=(docker compose --env-file /opt/secretary/.env -f infra/compose.yaml -f infra/compose.deploy.yaml)

emit_bool() {
  printf '%s=%s\n' "$1" "$2"
}

outer_blocked() {
  printf 'M4AM_GENERIC_DB_STAGE_CAUSE=%s\n' "$1"
  printf '%s\n' 'MANUAL_M4AN2_REMOTE_TERMINAL=blocked'
  exit 0
}

cd "$REPO" 2>/dev/null || {
  printf '%s\n' 'REMOTE_REPO_PASS=false'
  outer_blocked REMOTE_REPO
}

head="$(git rev-parse HEAD 2>/dev/null || true)"
prod="$(git rev-parse origin/production 2>/dev/null || true)"
dirty="$(git status --porcelain 2>/dev/null || true)"

if [ "$head" = "$EXPECTED_RELEASE" ]; then emit_bool REMOTE_HEAD_PASS true; else emit_bool REMOTE_HEAD_PASS false; fi
if [ "$prod" = "$EXPECTED_RELEASE" ]; then emit_bool REMOTE_PRODUCTION_REF_PASS true; else emit_bool REMOTE_PRODUCTION_REF_PASS false; fi
if [ -z "$dirty" ]; then emit_bool REMOTE_WORKTREE_CLEAN true; else emit_bool REMOTE_WORKTREE_CLEAN false; fi

if [ "$head" != "$EXPECTED_RELEASE" ] || [ "$prod" != "$EXPECTED_RELEASE" ] || [ -n "$dirty" ]; then
  outer_blocked REMOTE_GUARD
fi

if "${COMPOSE[@]}" config --format json >/dev/null 2>/dev/null; then
  emit_bool COMPOSE_CONFIG_PASS true
else
  emit_bool COMPOSE_CONFIG_PASS false
  outer_blocked COMPOSE_CONFIG
fi

service_running() {
  local service="$1"
  local cid state
  cid="$("${COMPOSE[@]}" ps -q "$service" 2>/dev/null | head -n 1)"
  [ -n "$cid" ] || return 1
  state="$(docker inspect -f '{{.State.Running}}' "$cid" 2>/dev/null || true)"
  [ "$state" = "true" ]
}

if service_running db; then emit_bool DB_RUNNING_PASS true; else emit_bool DB_RUNNING_PASS false; outer_blocked DB_RUNNING; fi
if service_running api; then emit_bool API_RUNNING_PASS true; else emit_bool API_RUNNING_PASS false; outer_blocked API_RUNNING; fi
if service_running worker; then emit_bool WORKER_RUNNING_PASS true; else emit_bool WORKER_RUNNING_PASS false; outer_blocked WORKER_RUNNING; fi

db_cid="$("${COMPOSE[@]}" ps -q db 2>/dev/null | head -n 1)"
db_health="$(docker inspect -f '{{.State.Health.Status}}' "$db_cid" 2>/dev/null || true)"
if [ "$db_health" = "healthy" ]; then
  emit_bool DB_HEALTH_PASS true
else
  emit_bool DB_HEALTH_PASS false
  outer_blocked DB_HEALTH
fi

# docker exec must not consume the remaining SSH-streamed bash script.
emit_bool ALEMBIC_CHECK_STARTED true
revision="$("${COMPOSE[@]}" exec -T db sh -lc 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "${POSTGRES_USER:-secretary}" -d "${POSTGRES_DB:-secretary}" -At -c "SELECT version_num FROM alembic_version"' </dev/null 2>/dev/null || true)"
if [ "$revision" = "0046" ]; then
  emit_bool ALEMBIC_0046_PASS true
else
  emit_bool ALEMBIC_0046_PASS false
  outer_blocked ALEMBIC
fi

child_out="$(mktemp)"
child_err="$(mktemp)"
cleanup_child() { rm -f "$child_out" "$child_err"; }
trap cleanup_child EXIT

emit_bool CHILD_STARTED true
"${COMPOSE[@]}" exec -T api python3 - >"$child_out" 2>"$child_err" <<'PY'
from __future__ import annotations


def emit(key: str, value: str) -> None:
    print(f"{key}={value}", flush=True)


def safe_class(exc: BaseException) -> str:
    name = type(exc).__name__
    allowed = {
        "RuntimeError", "ValueError", "TypeError", "AttributeError", "ImportError",
        "ModuleNotFoundError", "OperationalError", "ProgrammingError", "DatabaseError",
        "InterfaceError", "InvalidToken", "KeyError", "IndexError", "UnicodeDecodeError",
        "InvalidRequestError", "StatementError",
        "TelegramMtprotoProviderReferenceInvalidError",
    }
    return name if name in allowed else "OTHER"


def fail(stage: str, exc: BaseException) -> None:
    emit("FAILURE_SUBSTAGE", stage)
    emit("RAW_EXCEPTION_CLASS", safe_class(exc))
    emit("TELEGRAM_NETWORK_CALLS", "0")
    emit("M4AN2_CHILD_TERMINAL", "complete")
    raise SystemExit(0)


try:
    from sqlalchemy import select
    from app.connectors.google.encryption import CredentialEncryption
    from app.connectors.telegram.mtproto_transport import (
        _input_peer_from_reference,
        validate_provider_peer_reference,
    )
    from app.core.config import settings
    from app.db.models import TelegramMtprotoAccount, TelegramMtprotoChatSelection
    from app.db.session import SessionLocal
    from telethon.sessions import StringSession
except Exception as exc:
    emit("IMPORTS_PASS", "false")
    fail("IMPORTS", exc)

emit("IMPORTS_PASS", "true")

try:
    with SessionLocal() as db:
        accounts = list(db.scalars(select(TelegramMtprotoAccount)))
        selections = list(
            db.scalars(
                select(TelegramMtprotoChatSelection).where(
                    TelegramMtprotoChatSelection.manual_selected.is_(True)
                )
            )
        )
except Exception as exc:
    emit("DB_QUERY_PASS", "false")
    fail("DB_QUERY", exc)

emit("DB_QUERY_PASS", "true")
emit("ACCOUNT_EXACTLY_ONE", str(len(accounts) == 1).lower())
emit("MANUAL_SELECTED_EXACTLY_ONE", str(len(selections) == 1).lower())

if len(accounts) != 1:
    fail("ACCOUNT_CARDINALITY", RuntimeError())
if len(selections) != 1:
    fail("MANUAL_SELECTION_CARDINALITY", RuntimeError())

account = accounts[0]
selection = selections[0]

try:
    latest = selection.history_latest_message_id
    complete = bool(selection.history_complete)
    cursor = selection.history_backfill_before_message_id
    _ = selection.history_cutoff_at
except Exception as exc:
    emit("HISTORY_STATE_READ_PASS", "false")
    fail("HISTORY_STATE_READ", exc)

emit("HISTORY_STATE_READ_PASS", "true")
emit("INITIAL_STATE", str(latest is None).lower())
emit("HISTORY_COMPLETE_BEFORE", str(complete).lower())
emit("BACKFILL_CURSOR_PRESENT_BEFORE", str(cursor is not None).lower())

try:
    encryption = CredentialEncryption(settings.secretary_credential_key)
except Exception as exc:
    emit("CREDENTIAL_ENCRYPTION_CONSTRUCT_PASS", "false")
    fail("ENCRYPTION_CONSTRUCT", exc)

emit("CREDENTIAL_ENCRYPTION_CONSTRUCT_PASS", "true")

try:
    session_value = encryption.decrypt(account.session_encrypted)
    if not session_value:
        raise ValueError()
except Exception as exc:
    emit("SESSION_DECRYPT_PASS", "false")
    fail("SESSION_DECRYPT", exc)

emit("SESSION_DECRYPT_PASS", "true")

try:
    StringSession(session_value)
except Exception as exc:
    emit("STRING_SESSION_PARSE_PASS", "false")
    fail("STRING_SESSION_PARSE", exc)

emit("STRING_SESSION_PARSE_PASS", "true")

try:
    reference_value = encryption.decrypt(selection.provider_peer_reference_encrypted)
    if not reference_value:
        raise ValueError()
except Exception as exc:
    emit("REFERENCE_DECRYPT_PASS", "false")
    fail("REFERENCE_DECRYPT", exc)

emit("REFERENCE_DECRYPT_PASS", "true")

try:
    _input_peer_from_reference(reference_value)
except Exception as exc:
    emit("REFERENCE_PARSE_PASS", "false")
    fail("REFERENCE_PARSE", exc)

emit("REFERENCE_PARSE_PASS", "true")

try:
    validate_provider_peer_reference(reference_value, expected_peer_id=selection.peer_id)
except Exception as exc:
    emit("REFERENCE_PEER_MATCH_PASS", "false")
    fail("REFERENCE_PEER_MATCH", exc)

emit("REFERENCE_PEER_MATCH_PASS", "true")
emit("FAILURE_SUBSTAGE", "NONE")
emit("RAW_EXCEPTION_CLASS", "NONE")
emit("TELEGRAM_NETWORK_CALLS", "0")
emit("M4AN2_CHILD_TERMINAL", "complete")
PY
child_rc=$?

if [ "$child_rc" -eq 0 ]; then emit_bool CHILD_RETURN_CODE_ZERO true; else emit_bool CHILD_RETURN_CODE_ZERO false; fi
if [ -s "$child_err" ]; then emit_bool CHILD_STDERR_PRESENT true; else emit_bool CHILD_STDERR_PRESENT false; fi

if ! python3 -c "$PROTOCOL_VALIDATOR" child "$child_out" 2>/dev/null; then
  emit_bool CHILD_TERMINAL_RESULT invalid
  outer_blocked CHILD_PROTOCOL
fi
emit_bool CHILD_TERMINAL_RESULT valid

failure="$(sed -n 's/^FAILURE_SUBSTAGE=//p' "$child_out" | tail -n 1)"
peer_pass="$(sed -n 's/^REFERENCE_PEER_MATCH_PASS=//p' "$child_out" | tail -n 1)"

if [ -n "$failure" ] && [ "$failure" != "NONE" ]; then
  printf 'M4AM_GENERIC_DB_STAGE_CAUSE=%s\n' "$failure"
elif [ -s "$child_err" ] && [ "$peer_pass" = "true" ]; then
  printf '%s\n' 'M4AM_GENERIC_DB_STAGE_CAUSE=CHILD_STDERR_COLLAPSE'
elif [ "$child_rc" -eq 0 ] && [ "$peer_pass" = "true" ]; then
  printf '%s\n' 'M4AM_GENERIC_DB_STAGE_CAUSE=NOT_REPRODUCED_PRE_PROVIDER'
else
  printf '%s\n' 'M4AM_GENERIC_DB_STAGE_CAUSE=CHILD_EXECUTION'
fi

printf '%s\n' 'TELEGRAM_MTPROTO_M4AN2_STRUCTURAL_READY'
printf '%s\n' 'MANUAL_M4AN2_REMOTE_TERMINAL=structural'
REMOTE

set +e
ssh -T \
  -p "$SSH_PORT" \
  -o StrictHostKeyChecking=yes \
  -o "UserKnownHostsFile=$KNOWN" \
  -o GlobalKnownHostsFile=/dev/null \
  -o HostKeyAlgorithms=ssh-ed25519 \
  -o PasswordAuthentication=no \
  -o KbdInteractiveAuthentication=no \
  -o PreferredAuthentications=publickey \
  "$SSH_TARGET" \
  bash -s -- "$EXPECTED_RELEASE" \
  <"$REMOTE_HELPER" >"$TMPDIR_LOCAL/remote.stdout" 2>"$SSH_ERR"
ssh_rc=$?
python3 "$PROTOCOL_FILE" remote "$TMPDIR_LOCAL/remote.stdout" 2>/dev/null
protocol_rc=$?
set -e

if [ "$protocol_rc" -eq 3 ]; then
  fail "remote_incomplete"
elif [ "$protocol_rc" -ne 0 ]; then
  fail "remote_protocol"
fi

if [ "$ssh_rc" -ne 0 ]; then
  printf '%s\n' 'MANUAL_M4AN2_BLOCKED=ssh_failed'
  if [ -s "$SSH_ERR" ]; then printf '%s\n' 'SSH_STDERR_PRESENT=true'; else printf '%s\n' 'SSH_STDERR_PRESENT=false'; fi
  exit 2
fi

printf '%s\n' 'MANUAL_M4AN2_END=true'
