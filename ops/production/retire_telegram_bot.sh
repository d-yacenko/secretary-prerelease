#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET_FILE="$SCRIPT_DIR/target.json"
HELPER="$SCRIPT_DIR/retire_telegram_bot.py"

fail() { printf 'M4BJ1_BLOCKED=%s\n' "$1"; exit 2; }
[ "$#" -eq 0 ] || fail unexpected_arguments
for cmd in git python3 ssh ssh-keyscan ssh-keygen mktemp awk; do command -v "$cmd" >/dev/null || fail "missing_$cmd"; done
[ -f "$TARGET_FILE" ] || fail target_missing
[ "$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || true)" = "main" ] || fail wrong_local_branch
if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
  fail local_worktree_dirty
fi
git -C "$REPO_ROOT" fetch --prune origin main production >/dev/null 2>&1 || fail local_fetch
EXPECTED_RELEASE="$(python3 "$HELPER" release 2>/dev/null)" || fail release_contract
[ "$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)" = "$(git -C "$REPO_ROOT" rev-parse origin/main 2>/dev/null || true)" ] || fail local_main_stale
[ "$(git -C "$REPO_ROOT" rev-parse origin/production 2>/dev/null || true)" = "$EXPECTED_RELEASE" ] || fail local_production_ref

mapfile -t target_values < <(python3 "$HELPER" target "$TARGET_FILE" 2>/dev/null) || fail target_parse
[ "${#target_values[@]}" -eq 5 ] || fail target_parse
SSH_TARGET="${target_values[0]}"
SSH_PORT="${target_values[1]}"
EXPECTED_PIN="${target_values[2]}"
REMOTE_REPOSITORY_PATH="${target_values[3]}"
CANONICAL_ORIGIN="${target_values[4]}"
[ "$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)" = "$CANONICAL_ORIGIN" ] || fail wrong_local_origin
HOST="${SSH_TARGET#*@}"

TMPDIR_LOCAL="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_LOCAL"' EXIT
ssh-keyscan -t ed25519 -T 5 -p "$SSH_PORT" "$HOST" >"$TMPDIR_LOCAL/scan" 2>/dev/null || true
: >"$TMPDIR_LOCAL/known_hosts"
while IFS= read -r line; do
  [ -n "$line" ] || continue
  case "$line" in \#*) continue ;; esac
  printf '%s\n' "$line" >"$TMPDIR_LOCAL/key"
  [ "$(ssh-keygen -lf "$TMPDIR_LOCAL/key" -E sha256 2>/dev/null | awk 'NR==1 {print $2}')" = "$EXPECTED_PIN" ] && printf '%s\n' "$line" >>"$TMPDIR_LOCAL/known_hosts"
done <"$TMPDIR_LOCAL/scan"
[ -s "$TMPDIR_LOCAL/known_hosts" ] || fail host_key_pin_mismatch

python3 "$HELPER" bundle >"$TMPDIR_LOCAL/remote.py" 2>/dev/null || fail bundle
set +e
ssh -T -p "$SSH_PORT" -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o "UserKnownHostsFile=$TMPDIR_LOCAL/known_hosts" -o GlobalKnownHostsFile=/dev/null \
  -o HostKeyAlgorithms=ssh-ed25519 -o PasswordAuthentication=no \
  -o KbdInteractiveAuthentication=no -o PreferredAuthentications=publickey \
  "$SSH_TARGET" "cd $REMOTE_REPOSITORY_PATH && python3 - remote" \
  <"$TMPDIR_LOCAL/remote.py" >"$TMPDIR_LOCAL/remote.stdout" 2>"$TMPDIR_LOCAL/ssh.stderr"
ssh_rc=$?
python3 "$HELPER" validate "$TMPDIR_LOCAL/remote.stdout" 2>/dev/null
protocol_rc=$?
set -e
[ -s "$TMPDIR_LOCAL/remote.stdout" ] && cat "$TMPDIR_LOCAL/remote.stdout"
[ "$protocol_rc" -eq 0 ] || fail remote_protocol
[ "$(grep -c '^M4BJ1_TERMINAL=failure$' "$TMPDIR_LOCAL/remote.stdout" || true)" -eq 0 ] || exit 2
[ "$ssh_rc" -eq 0 ] || fail ssh_failed
