# Current task — Telegram MTProto M4AN1R2: restore executor SSH readiness outside production

## Status

M4AN1R established that the current Executor environment has no usable ambient SSH credential path.

Observed local-only facts:
- SSH client available;
- SSH_AUTH_SOCK set;
- SSH_AUTH_SOCK path is a valid socket;
- ssh-agent query did not yield usable identities;
- SSH agent key count = 0;
- no readable identity-file candidates were found;
- M4AM/M4AN do not set an explicit IdentityFile/IdentityAgent;
- production SSH therefore depends on ambient/default credentials;
- production network connections = 0;
- Telegram/provider calls = 0.

This is an Executor-environment blocker, not a Secretary runtime or Telegram conclusion.

## Goal

Restore or re-enter an Executor environment where the pre-existing authorized production SSH credential path is available, then verify readiness LOCALLY ONLY.

This task does NOT authorize a production SSH connection.

## Important boundary

Do not create new production credentials.

Do not copy private keys into the repository.

Do not ask the user to paste private keys, passwords, passphrases, tokens, recovery codes, or key material into chat.

Do not modify production.

The intended action is to restore the same pre-existing credential mechanism that previously allowed M4AM2R2 / production deployment SSH to authenticate.

Examples of acceptable environment-level recovery, performed by the human/Executor outside repo mutation:
- return to the shell/session where the SSH agent already has the authorized key loaded;
- restart/reconnect the Executor environment if its credential forwarding/agent integration was lost;
- use the normal workstation/agent credential integration already used for prior successful production tasks.

Do not generate/add a new key unless separately authorized outside this task.

## Local verification after credential restoration

Without connecting to production, rerun only:

- SSH_AUTH_SOCK set/valid check;
- `ssh-add -l` sanitized count;
- `ssh -G web-itx.duckdns.org` sanitized parsing;
- readable identity candidate count.

Return only:

- `SSH_AUTH_SOCK_SET=true|false`
- `SSH_AUTH_SOCK_VALID=true|false`
- `SSH_AGENT_QUERY_OK=true|false`
- `SSH_AGENT_KEY_COUNT=<n>`
- `SSH_CONFIG_PARSE_PASS=true|false`
- `CONFIG_USER_IS_ROOT=true|false`
- `IDENTITY_AGENT_CONFIGURED=true|false`
- `IDENTITY_FILE_COUNT=<n>`
- `IDENTITIES_ONLY=true|false`
- `PUBKEY_AUTH_ENABLED=true|false`
- `READABLE_IDENTITY_FILE_COUNT=<n>`
- `AMBIENT_CREDENTIAL_PATH_AVAILABLE=true|false`

Do not print:
- key fingerprints;
- identity paths;
- agent socket path;
- config contents;
- private/public key material.

## Success condition

Ready only if:
`AMBIENT_CREDENTIAL_PATH_AVAILABLE=true`

and at least one of:
- valid agent with usable key count > 0;
- readable identity file candidate usable by SSH config.

If still false:
STOP. Do not attempt production SSH.

## Forbidden

Do NOT:
- connect to production;
- run ssh against production;
- run ssh-keyscan;
- retry M4AN1;
- retry M4AM;
- retry Secretary Sync;
- change repository refs/files;
- change production;
- create/copy/commit SSH private keys;
- print secrets;
- call Telegram.

## Handoff

If local credential readiness becomes true, report the sanitized readiness fields and final marker:

`TELEGRAM_MTPROTO_M4AN1R2_SSH_READY`

Then STOP.

A separate task will authorize any production SSH retry.

`CURRENT_TASK.md` is the source of active authorization.
