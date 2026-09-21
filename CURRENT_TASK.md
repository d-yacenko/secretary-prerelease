# Current task — Telegram MTProto M4BB2: build/review read-only 2000+1 scope preview probe

## Status

M4BB1 code is accepted at:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

Production remains:
`cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`

Alembic:
`0046`

Production currently has exactly one saved folder configuration from the human UI:
`Личное`

The previous UI preview reported:
- scope count 28;
- configured folders 1;
- skipped broadcast 12 / bot 19 / unsupported 19;
- truncated=true.

No Apply Scope and no manual Sync followed.

## Important pre-deploy safety finding

Existing recurring MTProto behavior calls `reconcile_scope()` before each recurring history pass.

Therefore, once the wider M4BB1 scan is deployed, the already-saved folder could be reconciled automatically by the recurring worker before the human has time to run another UI preview or press `Apply Scope`.

Do NOT deploy M4BB1 yet.

We need a complete read-only preview against the current production session while production still has the old 500-dialog fail-closed behavior.

## Goal

BUILD / REVIEW ONLY.

Create a one-shot HUMAN-SHELL production probe that computes the configured folder scope with the accepted M4BB1 semantics:

- scan at most 2001 provider dialogs;
- retain/process only first 2000;
- `truncated=false` when total dialogs <= 2000;
- `truncated=true` only if a 2001st dialog is actually observed;
- use the same canonical folder filter matching and dialog conversion rules;
- exclude muted dialogs exactly as scope service does;
- aggregate skipped reasons only for retained first 2000;
- report only safe aggregate output.

Do NOT run the live probe in this task.

## Executor workspace

Work only from:
`~/work/secretary-executor`

Canonical origin:
`https://github.com/d-yacenko/secretary-prerelease.git`

Bootstrap:
```bash
git fetch origin
git switch main
git pull --ff-only
git remote get-url origin
git rev-parse HEAD
git status --short
```

Require canonical origin, current `origin/main`, clean worktree.

Read:
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/target.json`
- existing manual MTProto production probes for trust/output protocol patterns
- `backend/app/connectors/telegram/mtproto_transport.py`
- `backend/app/services/telegram_mtproto_scope_service.py`
- `backend/app/connectors/telegram/mtproto_account_store.py`

## New artifact

Create:
`ops/production/manual_mtproto_scope_preview_2000_probe.sh`

A bundled Python helper and focused tests are allowed/preferred.

The helper may execute inside the running API container from stdin, but it must remain read-only.

## Production pin for future live run

The probe must require exact current production runtime/ref:
`cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`

Expected Alembic:
`0046`

Require the normal pinned target/host-key/repo/worktree/container/DB-health guards.

Use the accepted production DB credential/host Alembic check with isolated stdin.

## Provider behavior

This is a read-only provider probe only.

Allowed provider operations:
1. decrypt the already-stored MTProto session in memory;
2. connect;
3. verify authorization;
4. read folder definitions;
5. iterate at most 2001 dialogs.

No history fetch.

No message fetch.

No mutation.

Prefer reusing canonical conversion/filter helpers from the production code:
- folder-name/definition handling;
- `_dialog_from_dialog`;
- `dialog_matches_filter`;
- canonical muted handling.

Because current production does not yet contain M4BB1, the probe may implement the 2000+1 loop explicitly while reusing canonical conversion/filter helpers.

## Database behavior

Read-only only:
- use `SessionLocal(autoflush=False)`;
- require exactly one MTProto account;
- require exactly one configured sync folder;
- do not flush/commit;
- do not change selection rows;
- do not call `reconcile_scope`.

## Safe output

Allowed fields:

```text
MANUAL_M4BB2_BEGIN=true
CANONICAL_REPO_PASS=true
TARGET_PIN_PASS=true
REMOTE_REPO_PASS=true
REMOTE_HEAD_PASS=true
REMOTE_PRODUCTION_REF_PASS=true
REMOTE_WORKTREE_CLEAN=true
COMPOSE_CONFIG_PASS=true
DB_RUNNING_PASS=true
API_RUNNING_PASS=true
WORKER_RUNNING_PASS=true
DB_HEALTH_PASS=true
ALEMBIC_0046_PASS=true
ACCOUNT_EXACTLY_ONE=true
CONFIGURED_FOLDER_EXACTLY_ONE=true
IGNORE_MUTED=true
DIALOGS_SCANNED_RETAINED=<0..2000>
SCOPE_MATCH_COUNT=<aggregate>
SKIPPED_BROADCAST=<aggregate>
SKIPPED_BOT=<aggregate>
SKIPPED_UNSUPPORTED=<aggregate>
SKIPPED_OTHER=<aggregate>
TRUNCATED=true|false
TELEGRAM_NETWORK_CALLS=<bounded count>
M4BB2_TERMINAL=success
MANUAL_M4BB2_END=true
```

Do NOT print:
- folder name;
- peer IDs;
- account IDs;
- user IDs;
- dialog titles/usernames;
- message IDs/content;
- session/reference/access hashes;
- DB credentials;
- raw provider objects;
- traceback/raw stderr.

Folder name is already known to the human, but the production probe should still stay aggregate-only.

## Failure handling

Fail closed on:
- wrong repo/ref/runtime;
- wrong Alembic;
- account/folder cardinality mismatch;
- auth invalid;
- unknown/unsafe output;
- provider exception;
- premature EOF.

Use allowlisted stage/class output only.

No retries after provider execution starts.

## Strictly forbidden

Do NOT:
- deploy;
- move production ref;
- call `reconcile_scope`;
- Apply Scope;
- history sync/fetch;
- message fetch;
- write/flush/commit DB;
- change folder config;
- login/re-login;
- restart/recreate containers;
- migrate;
- enable AI;
- change Bot API.

## Required local tests

At minimum:
1. 499 dialogs -> not truncated.
2. exactly 500 -> not truncated.
3. exactly 2000 -> not truncated.
4. 2001 -> truncated.
5. provider iteration stops at 2001.
6. matched scope dedupes by peer.
7. muted dialogs excluded.
8. skipped counts cover retained 2000 only.
9. account cardinality fail closed.
10. configured-folder cardinality fail closed.
11. no history method call.
12. no reconcile call.
13. no DB flush/commit.
14. auth invalid sanitized.
15. provider failure sanitized.
16. premature EOF.
17. unsafe output fail closed.
18. Alembic host/credential + stdin isolation regression.
19. `bash -n`.
20. helper compile.
21. Ruff.
22. `git diff --check`.

## Deliverable

If PASS:
- commit/push canonical main;
- update `PROJECT_STATE.md`;
- DO NOT run live probe;
- DO NOT deploy M4BB1.

Report:
- commit SHA;
- files changed;
- focused test results;
- lint/diff-check;
- production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_M4BB2_SCOPE_PREVIEW_PROBE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
