#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HELPER="$SCRIPT_DIR/verify_telegram_bot_retirement.py"
TARGET="$SCRIPT_DIR/target.json"
fail() { printf 'M4BM1_BLOCKED=%s\n' "$1"; exit 2; }
[ "$#" -eq 0 ] || fail unexpected_arguments
for cmd in git python3 ssh ssh-keyscan ssh-keygen mktemp awk; do command -v "$cmd" >/dev/null || fail "missing_$cmd"; done
[ "$(git -C "$ROOT" branch --show-current 2>/dev/null || true)" = main ] || fail wrong_local_branch
[ -z "$(git -C "$ROOT" status --porcelain)" ] || fail local_worktree_dirty
git -C "$ROOT" fetch --prune origin main production >/dev/null 2>&1 || fail local_fetch
EXPECTED="$(python3 "$HELPER" release 2>/dev/null)" || fail release_contract
[ "$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)" = "$(git -C "$ROOT" rev-parse origin/main 2>/dev/null || true)" ] || fail local_main_stale
[ "$(git -C "$ROOT" rev-parse origin/production 2>/dev/null || true)" = "$EXPECTED" ] || fail local_production_ref
mapfile -t target_values < <(python3 "$HELPER" target "$TARGET" 2>/dev/null) || fail target_parse
[ "${#target_values[@]}" -eq 5 ] || fail target_parse
SSH_TARGET="${target_values[0]}"; SSH_PORT="${target_values[1]}"; EXPECTED_PIN="${target_values[2]}"; REMOTE_PATH="${target_values[3]}"; ORIGIN="${target_values[4]}"
[ "$(git -C "$ROOT" remote get-url origin 2>/dev/null || true)" = "$ORIGIN" ] || fail wrong_local_origin
HOST="${SSH_TARGET#*@}"; TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
ssh-keyscan -t ed25519 -T 5 -p "$SSH_PORT" "$HOST" >"$TMP/scan" 2>/dev/null || true
: >"$TMP/known"
while IFS= read -r line; do [ -n "$line" ] || continue; case "$line" in \#*) continue;; esac; printf '%s\n' "$line" >"$TMP/key"; [ "$(ssh-keygen -lf "$TMP/key" -E sha256 2>/dev/null | awk 'NR==1 {print $2}')" = "$EXPECTED_PIN" ] && printf '%s\n' "$line" >>"$TMP/known"; done <"$TMP/scan"
[ -s "$TMP/known" ] || fail host_key_pin_mismatch
python3 "$HELPER" bundle >"$TMP/remote.py" 2>/dev/null || fail bundle
set +e
ssh -T -p "$SSH_PORT" -o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$TMP/known" -o GlobalKnownHostsFile=/dev/null -o HostKeyAlgorithms=ssh-ed25519 -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no -o PreferredAuthentications=publickey "$SSH_TARGET" "cd $REMOTE_PATH && python3 - remote" <"$TMP/remote.py" >"$TMP/stdout" 2>"$TMP/stderr"
ssh_rc=$?
python3 "$HELPER" validate "$TMP/stdout" >/dev/null 2>&1
protocol_rc=$?
set -e
[ "$protocol_rc" -eq 0 ] || fail remote_protocol
cat "$TMP/stdout"
[ "$ssh_rc" -eq 0 ] || fail ssh_failed
