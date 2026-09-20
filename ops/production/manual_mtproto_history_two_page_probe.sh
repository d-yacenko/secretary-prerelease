#!/usr/bin/env bash
set -euo pipefail

CANONICAL_ORIGIN="https://github.com/d-yacenko/secretary-prerelease.git"
EXPECTED_RELEASE="23fa07df213d5a70a6dc1d3c8b32af39228107eb"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET_FILE="$SCRIPT_DIR/target.json"

fail() {
  printf 'MANUAL_M4AO1_BLOCKED=%s\n' "$1"
  exit 2
}

[ "$#" -eq 0 ] || fail "unexpected_arguments"

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

readarray -t target_values < <(python3 - "$TARGET_FILE" 2>/dev/null <<'PY'
import json
import sys
from pathlib import Path

p = Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
expected = {
    "ssh_target": "root@web-itx.duckdns.org", "ssh_port": 22,
    "host_key_sha256": "SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs",
    "repository_path": "/opt/secretary",
    "origin_url": "https://github.com/d-yacenko/secretary-prerelease.git",
    "health_url": "http://127.0.0.1:18080/health",
    "compose_files": ["infra/compose.yaml", "infra/compose.deploy.yaml"],
}
if data != expected:
    raise ValueError()
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

ssh-keyscan -t ed25519 -T 5 -p "$SSH_PORT" "$HOST" >"$SCAN" 2>/dev/null || true
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

printf '%s\n' 'MANUAL_M4AO1_BEGIN=true'
printf '%s\n' 'CANONICAL_REPO_PASS=true'
printf '%s\n' 'TARGET_PIN_PASS=true'

# Build a self-contained stdlib helper; no remote files are created.
HELPER="$SCRIPT_DIR/manual_mtproto_history_two_page.py"
python3 "$HELPER" bundle >"$TMPDIR_LOCAL/remote.py" 2>/dev/null || fail "bundle"
set +e
ssh -T -p "$SSH_PORT" \
  -o StrictHostKeyChecking=yes \
  -o "UserKnownHostsFile=$KNOWN" \
  -o GlobalKnownHostsFile=/dev/null \
  -o HostKeyAlgorithms=ssh-ed25519 \
  -o PasswordAuthentication=no \
  -o KbdInteractiveAuthentication=no \
  -o PreferredAuthentications=publickey \
  "$SSH_TARGET" python3 -B - \
  <"$TMPDIR_LOCAL/remote.py" >"$TMPDIR_LOCAL/remote.stdout" 2>"$SSH_ERR"
ssh_rc=$?
python3 "$HELPER" validate "$TMPDIR_LOCAL/remote.stdout" 2>/dev/null
protocol_rc=$?
set -e
[ "$protocol_rc" -eq 0 ] || exit "$protocol_rc"
[ "$ssh_rc" -eq 0 ] || fail "ssh_failed"
printf '%s\n' 'MANUAL_M4AO1_END=true'
