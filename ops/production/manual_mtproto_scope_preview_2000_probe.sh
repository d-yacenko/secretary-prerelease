#!/usr/bin/env bash
set -euo pipefail

CANONICAL_ORIGIN="https://github.com/d-yacenko/secretary-prerelease.git"
EXPECTED_RELEASE="cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET_FILE="$SCRIPT_DIR/target.json"
HELPER="$SCRIPT_DIR/manual_mtproto_scope_preview_2000.py"

fail() { printf 'MANUAL_M4BB2_BLOCKED=%s\n' "$1"; exit 2; }
[ "$#" -eq 0 ] || fail unexpected_arguments
for cmd in git python3 ssh ssh-keyscan ssh-keygen mktemp; do command -v "$cmd" >/dev/null || fail "missing_$cmd"; done
[ -f "$TARGET_FILE" ] || fail target_missing
[ "$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)" = "$CANONICAL_ORIGIN" ] || fail wrong_local_origin
mapfile -t target_values < <(python3 - "$TARGET_FILE" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
expected = {
    "ssh_target": "root@web-itx.duckdns.org", "ssh_port": 22,
    "host_key_sha256": "SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs",
    "repository_path": "/opt/secretary",
    "origin_url": "https://github.com/d-yacenko/secretary-prerelease.git",
    "health_url": "http://127.0.0.1:18080/health",
    "compose_files": ["infra/compose.yaml", "infra/compose.deploy.yaml"],
}
if data != expected: raise SystemExit(1)
for key in ("ssh_target", "ssh_port", "host_key_sha256", "repository_path"): print(data[key])
PY
) || fail target_parse
[ "${#target_values[@]}" -eq 4 ] || fail target_parse
SSH_TARGET="${target_values[0]}"; SSH_PORT="${target_values[1]}"; EXPECTED_PIN="${target_values[2]}"
HOST="${SSH_TARGET#*@}"
TMPDIR_LOCAL="$(mktemp -d)"; trap 'rm -rf "$TMPDIR_LOCAL"' EXIT
ssh-keyscan -t ed25519 -T 5 -p "$SSH_PORT" "$HOST" >"$TMPDIR_LOCAL/scan" 2>/dev/null || true
: >"$TMPDIR_LOCAL/known_hosts"
while IFS= read -r line; do
  [ -n "$line" ] || continue
  case "$line" in \#*) continue;; esac
  printf '%s\n' "$line" >"$TMPDIR_LOCAL/key"
  [ "$(ssh-keygen -lf "$TMPDIR_LOCAL/key" -E sha256 2>/dev/null | awk 'NR==1 {print $2}')" = "$EXPECTED_PIN" ] && printf '%s\n' "$line" >>"$TMPDIR_LOCAL/known_hosts"
done <"$TMPDIR_LOCAL/scan"
[ -s "$TMPDIR_LOCAL/known_hosts" ] || fail host_key_pin_mismatch
printf '%s\n' MANUAL_M4BB2_BEGIN=true CANONICAL_REPO_PASS=true TARGET_PIN_PASS=true
python3 "$HELPER" bundle >"$TMPDIR_LOCAL/remote.py" 2>/dev/null || fail bundle
set +e
ssh -T -p "$SSH_PORT" -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$TMPDIR_LOCAL/known_hosts" \
  -o GlobalKnownHostsFile=/dev/null -o HostKeyAlgorithms=ssh-ed25519 -o PasswordAuthentication=no \
  -o KbdInteractiveAuthentication=no -o PreferredAuthentications=publickey "$SSH_TARGET" python3 -B - \
  <"$TMPDIR_LOCAL/remote.py" >"$TMPDIR_LOCAL/remote.stdout" 2>"$TMPDIR_LOCAL/ssh.stderr"
ssh_rc=$?
python3 "$HELPER" validate "$TMPDIR_LOCAL/remote.stdout" 2>/dev/null
protocol_rc=$?
set -e
[ "$protocol_rc" -eq 0 ] || exit "$protocol_rc"
[ "$ssh_rc" -eq 0 ] || fail ssh_failed
printf '%s\n' MANUAL_M4BB2_END=true
