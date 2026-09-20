# Current task — Telegram MTProto M4AO1: build/review human-shell two-page provider probe

## Status

M4AN2 human-shell structural localization is complete and PASS on production runtime/ref:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Confirmed PASS:
- canonical repo / target pin / remote HEAD / origin/production / clean worktree;
- Compose / db / api / worker / DB health;
- Alembic 0046;
- imports / DB query / exact account+manual selection cardinality;
- history-state read;
- CredentialEncryption construction;
- session decrypt + StringSession parse;
- provider reference decrypt / parse / peer match;
- child return code zero;
- child stderr absent;
- `TELEGRAM_NETWORK_CALLS=0`;
- `FAILURE_SUBSTAGE=NONE`;
- `M4AM_GENERIC_DB_STAGE_CAUSE=NOT_REPRODUCED_PRE_PROVIDER`.

Current selection state remains:
- `INITIAL_STATE=true`
- `HISTORY_COMPLETE_BEFORE=false`
- `BACKFILL_CURSOR_PRESENT_BEFORE=false`

Earlier M4AH3 already proved page1:
- 100 messages seen;
- 100 exact `_history_entry_from_message` conversions;
- no invalid entries.

Therefore the remaining unproven portion of the failed manual Sync is the bounded provider sequence after page1, especially a derived second-page initial backfill when page1 is full.

## Goal

BUILD / REVIEW ONLY.

Create and review a corrected human-shell two-page Telegram MTProto provider probe that can later be executed manually from the proven human sandbox SSH context.

Do NOT execute it live in this task.

## Executor workspace

Work only from:

`~/work/secretary-executor`

Canonical origin:

`https://github.com/d-yacenko/secretary-prerelease.git`

Do not use:
- `~/work/secretary`
- `~/work/secretary-prerelease`

for implementation work.

## Required bootstrap

Before implementation:

```bash
git fetch origin
git switch main
git pull --ff-only
git remote get-url origin
git rev-parse HEAD
git status --short
```

Require:
- exact canonical origin;
- current `origin/main`;
- clean worktree.

Then read:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/manual_mtproto_structural_probe.sh`
- accepted diagnostic helper at exact review SHA `48816aedd639268770b2fb67caa22e048ce03493` only as reference.

Do not rerun the old helper as-is.

## New artifact

Create a new human-shell probe under `ops/production/`, for example:

`manual_mtproto_history_two_page_probe.sh`

A small protocol/parser helper and focused tests are allowed if useful.

## Required runtime semantics for the future human run

The probe must be read-only and bounded.

### Production guards

Before provider work, verify:
- canonical target from `ops/production/target.json`;
- pinned ED25519 host key exact;
- production HEAD exact `23fa07df213d5a70a6dc1d3c8b32af39228107eb`;
- remote `origin/production` exact same SHA;
- production worktree clean;
- Compose/db/api/worker/DB health PASS;
- Alembic 0046 PASS.

### Structural state

Inside API container, verify exactly one MTProto account and exactly one manual-selected group.

Decrypt session/reference only in memory and never print either.

Validate:
- session decrypt;
- StringSession parse;
- provider-reference decrypt;
- provider-reference parse;
- provider-reference peer match.

### Provider sequence

Mirror the production initial history sequence closely.

Current expected state is initial:
- latest message id absent;
- history incomplete;
- no backfill cursor.

Page 1:
- fresh Telethon client;
- construct from stored StringSession;
- connect once;
- `is_user_authorized()` once;
- `iter_messages(..., limit=100, reverse=False)`;
- apply exact `_history_entry_from_message` conversion to every returned message;
- no materialization.

After page1:
- use the exact production `_next_backfill_state` logic with the same cutoff semantics;
- decide whether page2 is required;
- if page2 is not required, stop successfully.

Page 2 only when required:
- use a NEW fresh Telethon client, matching production `fetch_history`;
- connect once;
- `is_user_authorized()` once;
- `iter_messages(..., max_id=<derived cursor>, limit<=100, reverse=False)`;
- exact `_history_entry_from_message` conversion;
- no materialization.

### Hard bounds

- max pages: 2;
- max messages total: 200;
- max logical provider operations total: 6:
  - connect <=2
  - is_user_authorized <=2
  - iter_messages <=2
- no automatic retry;
- no discovery;
- no write RPC;
- no login;
- no Sync API call;
- no application `fetch_history`;
- no DB writes;
- no flush/commit/materialization/upsert;
- no service restart/recreate;
- no production file/env/ref mutation.

### Safe output only

Allowed output should be sanitized aggregate/stage/class facts only.

Include:
- production guard booleans;
- account/manual-selection cardinality booleans;
- structural decrypt/reference booleans;
- `INITIAL_STATE`
- `HISTORY_COMPLETE_BEFORE`
- `BACKFILL_CURSOR_PRESENT_BEFORE`
- `PAGE1_PASS`
- `PAGE1_MESSAGES_SEEN`
- `PAGE1_ENTRIES_CONVERTED`
- `PAGE1_ENTRIES_NONE`
- `PAGE2_REQUIRED`
- if page2 runs:
  - `PAGE2_PASS`
  - `PAGE2_MESSAGES_SEEN`
  - `PAGE2_ENTRIES_CONVERTED`
  - `PAGE2_ENTRIES_NONE`
- `CONNECT_CALL_COUNT`
- `IS_USER_AUTHORIZED_CALL_COUNT`
- `ITER_MESSAGES_CALL_COUNT`
- `MESSAGES_SEEN_TOTAL`
- `ENTRIES_CONVERTED_TOTAL`
- `TELEGRAM_NETWORK_CALLS`
- on failure:
  - allowlisted `FAILURE_STAGE`
  - sanitized `RAW_EXCEPTION_CLASS`
  - bounded `MESSAGE_ORDINAL`

Never print:
- message text;
- sender;
- timestamps;
- message IDs;
- peer/group/account IDs;
- session;
- provider reference;
- Telegram API credentials;
- DB credentials;
- traceback;
- raw stderr.

## Failure taxonomy

Use explicit stages, at minimum:

- `STAGE_0_RELEASE_REF`
- `STAGE_0_PRODUCTION_REF`
- `STAGE_0_WORKTREE`
- `STAGE_1_IMPORTS`
- `STAGE_1_DB_SESSION`
- `STAGE_1_SESSION_DECRYPT`
- `STAGE_1_REFERENCE_DECRYPT`
- `STAGE_1_REFERENCE_PARSE`
- `STAGE_1_REFERENCE_PEER_MATCH`
- `STAGE_2_PAGE1_CONNECT`
- `STAGE_2_PAGE1_AUTHORIZED`
- `STAGE_3_PAGE1_ITERATION`
- `STAGE_3_PAGE1_CONVERSION`
- `STAGE_4_PAGE2_CONNECT`
- `STAGE_4_PAGE2_AUTHORIZED`
- `STAGE_5_PAGE2_ITERATION`
- `STAGE_5_PAGE2_CONVERSION`

If provider authorization returns false, classify within the appropriate AUTHORIZED stage without revealing details.

## Human-shell bridge requirements

The new probe must be intended for manual launch from the proven human sandbox shell.

Use:
- canonical target.json;
- strict pinned host-key verification;
- public-key-only SSH;
- `PasswordAuthentication=no`;
- `KbdInteractiveAuthentication=no`;
- `PreferredAuthentications=publickey`.

Do not rely on Executor subprocess SSH.

The local wrapper must fail closed:
- validate ordered/allowlisted remote output;
- require explicit remote terminal marker;
- premature EOF => sanitized blocker;
- unsafe/unknown output => sanitized blocker;
- never print raw remote stderr.

## Tests / review

Run local-only tests. Do NOT connect to production.

Minimum checks:
- `bash -n` on shell wrapper;
- parser/protocol tests for valid one-page completion;
- valid two-page completion;
- page1 staged failures;
- page2 staged failures;
- premature EOF at every major stage;
- unknown/unsafe output fails closed;
- count bounds enforced;
- network-call bounds enforced;
- no DB-write/materialization path exists;
- no Sync/login/discovery/write RPC exists;
- no application `fetch_history` call exists;
- no production connection occurs during tests.

Run Ruff/diff-check as applicable.

## Deliverable

If review passes:
- commit/push to canonical main;
- update `PROJECT_STATE.md` with the factual reviewed-probe result;
- do NOT run the live probe.

Report:
- commit SHA;
- changed files;
- focused test counts;
- lint/diff-check;
- confirmation production SSH = 0;
- confirmation Telegram/provider calls = 0;
- confirmation production mutation = 0.

Final marker:

`TELEGRAM_MTPROTO_M4AO1_HUMAN_TWO_PAGE_PROBE_READY`

Then STOP.

A separate human task will authorize exactly one live manual run.
