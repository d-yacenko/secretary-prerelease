# Current task — Telegram MTProto M4AN1R: local-only SSH credential readiness

## Status

M4AN1 did not reach production remote execution.

Confirmed:
- canonical target/pin local check PASS;
- strict host-key verification PASS;
- SSH authentication/remote execution FAIL;
- remote helper did not start;
- no production guards obtained;
- no structural child;
- no Telegram/provider calls;
- no DB writes/materialization;
- production unchanged.

Earlier M4AM2R2 did authenticate successfully and start remote code from the same canonical target, so this task must determine whether the current Executor environment has lost or changed SSH credential availability.

## Goal

Inspect only the LOCAL SSH client/agent configuration relevant to authentication.

Do NOT connect to production in this task.

## Canonical target

Use target metadata only to identify the destination name for local config expansion:

`root@web-itx.duckdns.org`

Do not run ssh/ssh-keyscan/openssl/nc/curl or any command that opens a network connection to the production host.

## Allowed local checks

Run locally and emit only sanitized booleans/counts.

1. SSH client availability:
- `ssh -V` may be invoked locally;
- report `SSH_CLIENT_AVAILABLE=true|false`;
- do not report full version string unless needed.

2. SSH agent environment:
- whether `SSH_AUTH_SOCK` is set;
- whether its path exists and is a socket;
- do NOT print the path.

Emit:
- `SSH_AUTH_SOCK_SET=true|false`
- `SSH_AUTH_SOCK_VALID=true|false`

3. Agent key inventory:
If SSH_AUTH_SOCK is valid, run `ssh-add -l`.

Do NOT print key fingerprints/comments/key material.

Emit only:
- `SSH_AGENT_QUERY_OK=true|false`
- `SSH_AGENT_KEY_COUNT=<bounded integer>`

Interpret ssh-add exit 1/no identities as query succeeded with key count 0 where appropriate.
If no usable agent exists:
- `SSH_AGENT_QUERY_OK=false`
- key count 0.

4. Expanded SSH config, local-only:
Use:
`ssh -G web-itx.duckdns.org`

This must not connect.

Parse locally and do NOT print raw output.

Emit only:
- `SSH_CONFIG_PARSE_PASS=true|false`
- `CONFIG_USER_IS_ROOT=true|false`
- `IDENTITY_AGENT_CONFIGURED=true|false`
- `IDENTITY_FILE_COUNT=<bounded integer>`
- `IDENTITIES_ONLY=true|false`
- `PUBKEY_AUTH_ENABLED=true|false`

Do NOT emit identity file paths, agent socket paths, usernames other than boolean root match, proxy commands, hostnames, or config contents.

5. Local identity-file usability:
For each identity file resolved by `ssh -G`, expand `~` locally and check only:
- file exists;
- regular file;
- readable.

Do NOT read key contents.
Do NOT hash/fingerprint keys.
Do NOT print paths.

Emit:
- `READABLE_IDENTITY_FILE_COUNT=<bounded integer>`

6. Compare against M4AM/M4AN SSH argv semantics from repository source, without network:
- report whether either harness explicitly sets `IdentityFile`, `IdentityAgent`, or `IdentitiesOnly`;
- report whether both otherwise rely on ambient/default SSH credential resolution.

Emit:
- `M4AM_EXPLICIT_IDENTITY=false|true`
- `M4AN_EXPECTS_AMBIENT_IDENTITY=false|true`
- `AMBIENT_CREDENTIAL_PATH_AVAILABLE=true|false`

## Forbidden

Do NOT:
- connect to production;
- run ssh against production;
- run ssh-keyscan in this task;
- retry M4AN1;
- run M4AM diagnostic again;
- touch production;
- change ~/.ssh/config;
- change agent state;
- add/remove ssh-agent keys;
- copy/decrypt/read private keys;
- print identity paths/fingerprints/comments;
- change repository refs/files;
- retry Secretary Sync;
- call Telegram.

## Interpretation

A. Agent socket valid + key count >0
=> ambient agent credentials exist. Next task may authorize exactly one authenticated read-only SSH retry.

B. Agent absent/invalid or key count 0, but readable identity files exist
=> default file-based auth may still be possible; inspect whether ssh -G would consider them. Do not connect yet.

C. No agent credentials and no readable identity file candidates
=> current Executor environment lacks an SSH credential path. Do not retry production SSH until credential availability is restored outside this task.

D. ssh -G shows an unexpected local config constraint (e.g. identities-only with no usable identity)
=> report sanitized booleans; no repair in this task.

## Required report

Return only:

- SSH_CLIENT_AVAILABLE
- SSH_AUTH_SOCK_SET
- SSH_AUTH_SOCK_VALID
- SSH_AGENT_QUERY_OK
- SSH_AGENT_KEY_COUNT
- SSH_CONFIG_PARSE_PASS
- CONFIG_USER_IS_ROOT
- IDENTITY_AGENT_CONFIGURED
- IDENTITY_FILE_COUNT
- IDENTITIES_ONLY
- PUBKEY_AUTH_ENABLED
- READABLE_IDENTITY_FILE_COUNT
- M4AM_EXPLICIT_IDENTITY
- M4AN_EXPECTS_AMBIENT_IDENTITY
- AMBIENT_CREDENTIAL_PATH_AVAILABLE

Confirm:
- production network connections = 0;
- no SSH config/agent/key mutation;
- no Telegram/provider calls.

Final marker:
`TELEGRAM_MTPROTO_M4AN1R_SSH_LOCAL_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
