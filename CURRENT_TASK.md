# Current task — Telegram MTProto M4AN1: zero-provider structural localization

## Status

M4AM2R2 executed the approved live probe exactly once.

Result:
- canonical fresh clone/preflight PASS;
- `FAILURE_STAGE=STAGE_1_DB_SESSION`;
- `RAW_EXCEPTION_CLASS=RuntimeError`;
- `MESSAGE_ORDINAL=0`;
- `TELEGRAM_NETWORK_CALLS=0`;
- page/provider calls = 0;
- no production mutation.

No Telegram provider operation occurred.

The M4AM two-page provider probe MUST NOT be run again in this task.

The current `STAGE_1_DB_SESSION` is intentionally/accidentally broad and can represent several different pre-provider failures. This task authorizes one read-only structural localization only.

## Goal

Identify exactly which pre-provider substage caused the M4AM2R2 stop, while making ZERO Telegram network/provider calls.

Distinguish at least:

1. remote release/ref/worktree guard;
2. compose config;
3. db/api/worker running;
4. DB health;
5. Alembic 0046;
6. API-container Python child start;
7. child imports;
8. SessionLocal DB query;
9. account cardinality;
10. manual-selected group cardinality;
11. current history-state read;
12. CredentialEncryption construction;
13. stored session decrypt + StringSession parse;
14. stored reference decrypt/parse/peer-match;
15. child return code;
16. whether child emitted ANY stderr.

Stop before TelegramClient construction.

## Authorization

BREAK-GLASS READ-ONLY SSH is explicitly authorized for this task.

Use only the canonical production target and pinned ED25519 fingerprint from:
`ops/production/target.json`

Use:
- BatchMode=yes;
- StrictHostKeyChecking=yes;
- temporary verified UserKnownHostsFile;
- GlobalKnownHostsFile=/dev/null;
- HostKeyAlgorithms=ssh-ed25519.

No alternative host discovery/fallback.

## Local source

Use a fresh canonical clone or another known-clean canonical checkout of:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read:
- `origin/main:CURRENT_TASK.md`
- `origin/main:PROJECT_STATE.md`
- `origin/main:AGENTS.md`
- `docs/deploy.md`
- relevant production helper files.

Require:
- `origin/production == 23fa07df213d5a70a6dc1d3c8b32af39228107eb`
- canonical target.json unchanged.

## Remote preflight

Read-only verify:
- production HEAD exact `23fa07df213d5a70a6dc1d3c8b32af39228107eb`;
- origin/production exact same SHA;
- worktree clean.

If any fails: STOP.

## Structural localization

Run the equivalent outer checks separately and emit only booleans/stage tokens:

- `COMPOSE_CONFIG_PASS`
- `DB_RUNNING_PASS`
- `API_RUNNING_PASS`
- `WORKER_RUNNING_PASS`
- `DB_HEALTH_PASS`
- `ALEMBIC_0046_PASS`

Then run exactly one read-only Python child through the same invocation shape used by the probe:

`docker compose ... exec -T api python3 -`

The child must:

- import the exact app modules used by M4AM;
- open `SessionLocal` read-only;
- query MTProto accounts;
- query manual-selected chat selections;
- emit only cardinality booleans;
- read history state into local variables but emit only booleans;
- construct `CredentialEncryption`;
- decrypt stored session but never print it;
- parse `StringSession`;
- decrypt stored provider reference but never print it;
- parse/validate reference against the selected peer;
- STOP before TelegramClient construction;
- make no Telegram calls.

Safe child outputs:

- `IMPORTS_PASS=true|false`
- `DB_QUERY_PASS=true|false`
- `ACCOUNT_EXACTLY_ONE=true|false`
- `MANUAL_SELECTED_EXACTLY_ONE=true|false`
- `HISTORY_STATE_READ_PASS=true|false`
- `INITIAL_STATE=true|false`
- `HISTORY_COMPLETE_BEFORE=true|false`
- `BACKFILL_CURSOR_PRESENT_BEFORE=true|false`
- `CREDENTIAL_ENCRYPTION_CONSTRUCT_PASS=true|false`
- `SESSION_DECRYPT_PASS=true|false`
- `STRING_SESSION_PARSE_PASS=true|false`
- `REFERENCE_DECRYPT_PASS=true|false`
- `REFERENCE_PARSE_PASS=true|false`
- `REFERENCE_PEER_MATCH_PASS=true|false`
- `FAILURE_SUBSTAGE=<allowlisted token|none>`
- `RAW_EXCEPTION_CLASS=<safe class token|none>`
- `TELEGRAM_NETWORK_CALLS=0`

Parent must additionally report:

- `CHILD_RETURN_CODE_ZERO=true|false`
- `CHILD_STDERR_PRESENT=true|false`

Do NOT output stderr contents.

If child catches a failure, it must emit only:
- safe failure substage;
- safe exception class name;
- prior safe booleans;
and exit 0 with no traceback.

Suggested allowlisted substages:

- IMPORTS
- DB_QUERY
- ACCOUNT_CARDINALITY
- MANUAL_SELECTION_CARDINALITY
- HISTORY_STATE_READ
- ENCRYPTION_CONSTRUCT
- SESSION_DECRYPT
- STRING_SESSION_PARSE
- REFERENCE_DECRYPT
- REFERENCE_PARSE
- REFERENCE_PEER_MATCH
- NONE

## Critical diagnostic question

If all child safe checks PASS but `CHILD_STDERR_PRESENT=true`, report that explicitly. The original M4AM wrapper collapses any child stderr into generic `STAGE_1_DB_SESSION`, so this would identify a harness-level false block.

If outer compose/service/DB/Alembic checks PASS and child return code/stderr are clean but a child substage fails, report that exact sanitized substage/class.

## Strictly forbidden

Do NOT:
- run `diagnose_mtproto_history_two_page.py` again;
- construct TelegramClient;
- connect to Telegram;
- call is_user_authorized;
- call iter_messages;
- call application fetch_history;
- retry Secretary Sync;
- login/re-login;
- Apply Scope;
- discover groups/folders;
- write DB;
- materialize/upsert;
- emit IDs/content/session/reference/credentials;
- print raw stderr/traceback;
- edit production files/env;
- restart/recreate services;
- change refs;
- run migrations;
- enable AI;
- change Bot API.

## Required report

Return only:

### Transport/guards
- target/pin PASS;
- SSH PASS;
- release/ref/worktree guards.

### Outer structure
- COMPOSE_CONFIG_PASS
- DB_RUNNING_PASS
- API_RUNNING_PASS
- WORKER_RUNNING_PASS
- DB_HEALTH_PASS
- ALEMBIC_0046_PASS

### Child structure
- CHILD_RETURN_CODE_ZERO
- CHILD_STDERR_PRESENT
- safe child booleans listed above
- FAILURE_SUBSTAGE
- RAW_EXCEPTION_CLASS
- TELEGRAM_NETWORK_CALLS=0

Confirm:
- no TelegramClient/provider calls;
- no DB writes/materialization;
- no raw IDs/content/session/reference;
- production unchanged.

Final marker:
`TELEGRAM_MTPROTO_M4AN1_STRUCTURAL_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
