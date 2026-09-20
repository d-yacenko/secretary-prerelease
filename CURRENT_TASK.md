# Current task — Telegram MTProto M4AN2: bootstrap + zero-provider structural localization

## Status

Executor bootstrap has been standardized and is now mandatory through:
- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`

Production runtime/ref:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Current diagnostic position:
- M4AK manual Sync returned provider-neutral HTTP 503;
- account/group discovery remained usable;
- M4AM2R2 provider-sequence probe executed exactly once but stopped before Telegram calls at:
  - `FAILURE_STAGE=STAGE_1_DB_SESSION`
  - `RAW_EXCEPTION_CLASS=RuntimeError`
  - `TELEGRAM_NETWORK_CALLS=0`
- that stage is too broad to identify the actual pre-provider failure;
- M4AN1 structural localization did not run because that Executor environment lacked usable SSH credentials.

No conclusion about Telegram auth/history should be drawn from those Executor/bootstrap failures.

## Goal

In ONE work cycle:

1. establish canonical Executor bootstrap;
2. if bootstrap PASS, immediately run one zero-provider read-only structural localization;
3. identify the exact pre-provider substage hidden inside M4AM's broad `STAGE_1_DB_SESSION`.

Do not create intermediate Git/SSH phases.

## Mandatory bootstrap

Follow exactly:
`docs/executor_bootstrap.md`

Canonical repository:
`https://github.com/d-yacenko/secretary-prerelease.git`

If the current checkout is wrong-origin, unrelated, dirty, or contains unknown local state:
- leave it untouched;
- use a fresh temporary clone of the canonical repo.

From canonical `origin/main`, read:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- relevant `ops/production/*` files.

Verify:
- `origin/production == 23fa07df213d5a70a6dc1d3c8b32af39228107eb`
- canonical target.json unchanged;
- pinned production host-key contract intact;
- actual pinned read-only public-key-only SSH no-op to the canonical target succeeds. For this BREAK-GLASS diagnostic, require `PasswordAuthentication=no`, `KbdInteractiveAuthentication=no`, and `PreferredAuthentications=publickey`; `BatchMode=yes` is non-gating.

If bootstrap cannot be established before remote execution:

Return only:
`EXECUTOR_BOOTSTRAP_BLOCKED=<sanitized_reason>`

and confirm:
- production remote execution = 0;
- Telegram/provider calls = 0;
- production mutation = 0.

Then STOP.

Do NOT create a follow-up phase for the bootstrap failure.

## Authorization

If bootstrap PASS:

BREAK-GLASS READ-ONLY SSH is explicitly authorized for this task.

Use only the canonical target from:
`ops/production/target.json`

Use strict pinned SSH with public-key-only auth:
- StrictHostKeyChecking=yes
- temporary verified UserKnownHostsFile
- GlobalKnownHostsFile=/dev/null
- HostKeyAlgorithms=ssh-ed25519
- PasswordAuthentication=no
- KbdInteractiveAuthentication=no
- PreferredAuthentications=publickey

For this read-only diagnostic path, do not require `BatchMode=yes`.

No alternative host/alias/directory/credential probing.

## Remote guards

Before structural child:

Verify read-only:
- production HEAD exact `23fa07df213d5a70a6dc1d3c8b32af39228107eb`;
- remote `origin/production` exact same SHA;
- production worktree clean.

If any remote guard fails:
STOP with one sanitized runtime blocker.
Do not repair.

## Outer structural localization

Run each existing production read-only check separately and report only booleans:

- `COMPOSE_CONFIG_PASS=true|false`
- `DB_RUNNING_PASS=true|false`
- `API_RUNNING_PASS=true|false`
- `WORKER_RUNNING_PASS=true|false`
- `DB_HEALTH_PASS=true|false`
- `ALEMBIC_0046_PASS=true|false`

Use canonical Compose prefix from `docs/deploy.md`.

Do not print resolved environment or secrets.

## One read-only API-container child

Only if outer checks allow the child to run, execute exactly one child through the same invocation shape as M4AM:

`docker compose ... exec -T api python3 -`

The child must stop BEFORE TelegramClient construction.

It may only:

1. import the exact app modules used by M4AM;
2. open `SessionLocal` read-only;
3. query MTProto accounts;
4. query manual-selected selections;
5. read current history state into local variables;
6. construct `CredentialEncryption`;
7. decrypt stored session without output;
8. parse `StringSession`;
9. decrypt provider reference without output;
10. parse and validate the provider reference against the selected peer;
11. exit.

No TelegramClient.
No connect.
No is_user_authorized.
No iter_messages.

## Safe child protocol

Allowed output only:

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
- `FAILURE_SUBSTAGE=<allowlisted token|NONE>`
- `RAW_EXCEPTION_CLASS=<safe identifier|NONE>`
- `TELEGRAM_NETWORK_CALLS=0`

Allowlisted failure substages:

- `IMPORTS`
- `DB_QUERY`
- `ACCOUNT_CARDINALITY`
- `MANUAL_SELECTION_CARDINALITY`
- `HISTORY_STATE_READ`
- `ENCRYPTION_CONSTRUCT`
- `SESSION_DECRYPT`
- `STRING_SESSION_PARSE`
- `REFERENCE_DECRYPT`
- `REFERENCE_PARSE`
- `REFERENCE_PEER_MATCH`
- `NONE`

If child catches a failure:
- emit only safe prior booleans;
- emit sanitized substage and exception class;
- exit 0;
- no traceback.

Parent additionally reports:

- `CHILD_RETURN_CODE_ZERO=true|false`
- `CHILD_STDERR_PRESENT=true|false`

Never print stderr contents.

## Critical diagnostic branch

If all safe child checks PASS and:
`CHILD_STDERR_PRESENT=true`

report this explicitly as:
`M4AM_GENERIC_DB_STAGE_CAUSE=CHILD_STDERR_COLLAPSE`

because the M4AM wrapper converts any child stderr into generic `STAGE_1_DB_SESSION`.

If a specific outer/child substage fails, report:
`M4AM_GENERIC_DB_STAGE_CAUSE=<safe_substage>`

If everything through reference validation passes and child stderr is false:
`M4AM_GENERIC_DB_STAGE_CAUSE=NOT_REPRODUCED_PRE_PROVIDER`

Do not proceed to Telegram calls in this task.

## Strictly forbidden

Do NOT:
- run `diagnose_mtproto_history_two_page.py` again;
- retry Secretary Sync;
- construct TelegramClient;
- connect to Telegram;
- call is_user_authorized;
- call iter_messages;
- call application fetch_history;
- login/re-login;
- Apply Scope;
- discover groups/folders;
- write DB;
- materialize/upsert;
- emit account/group/peer/message IDs;
- emit message text/sender/timestamps;
- emit session/reference/credentials;
- print raw stderr/traceback;
- edit production files/env;
- restart/recreate services;
- change refs;
- run migrations;
- enable MTProto AI;
- change Bot API.

## Required report

### Bootstrap
If PASS, only:
- canonical repo: PASS
- authorized refs/SHAs: PASS
- clean/exact checkout: PASS
- target/pin: PASS
- pinned public-key-only SSH no-op: PASS

### Remote guards
- production HEAD/ref/worktree: PASS/FAIL

### Outer
- COMPOSE_CONFIG_PASS
- DB_RUNNING_PASS
- API_RUNNING_PASS
- WORKER_RUNNING_PASS
- DB_HEALTH_PASS
- ALEMBIC_0046_PASS

### Child
- CHILD_RETURN_CODE_ZERO
- CHILD_STDERR_PRESENT
- all safe child booleans
- FAILURE_SUBSTAGE
- RAW_EXCEPTION_CLASS
- TELEGRAM_NETWORK_CALLS=0
- M4AM_GENERIC_DB_STAGE_CAUSE

Confirm:
- TelegramClient/provider calls = 0;
- DB writes/materialization = 0;
- production mutation = 0;
- no raw IDs/content/session/reference emitted.

Final marker:
`TELEGRAM_MTPROTO_M4AN2_STRUCTURAL_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.


## Human-shell bridge

Because the Executor subprocess does not share the same SSH credential/broker context as the human sandbox terminal, the canonical manual bridge for this task is:

`ops/production/manual_mtproto_structural_probe.sh`

It is intended to be launched from the human sandbox shell where ordinary SSH already works.

The script:
- verifies the canonical local repo and target metadata;
- verifies the pinned ED25519 host key;
- uses public-key-only SSH auth with password and keyboard-interactive disabled;
- performs only the zero-provider structural localization authorized above;
- never constructs TelegramClient;
- never performs Telegram/provider calls;
- never writes DB/materializes data;
- emits only sanitized booleans/stage/class facts.

Run from a fresh/canonical checkout on current main:

`bash ops/production/manual_mtproto_structural_probe.sh`

Then paste its output back to the Architect.

