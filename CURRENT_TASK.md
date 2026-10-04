# CURRENT_TASK

ACTIVE

## REL1D-R2.1 — converge Linux client onto the canonical launcher bundle

REL1D-R2 build is accepted.

The exact-release client was successfully built from:

`6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`

Focused tests/build passed and the source was not edited. The install stopped only because a running `personal_secretary` process came from the older staging artifact directory while the desktop launcher points at the persistent installed bundle.

Historical ledger resolves this ambiguity:

- prior successful `REL1-R2` explicitly installed the exact-production client into the bundle referenced by `personal-secretary.desktop`;
- that persistent launcher target is:
  `/home/d.yacenko/.local/share/personal-secretary-preview/19228c9d84bbc0350b78e2d0600710dc3ddf368f/bundle`;
- the prior path
  `/home/d.yacenko/tmp/rel1-r2-6f802d6-artifact/bundle`
  is a staging artifact, not the canonical installed target.

Therefore the canonical human-used install target for this corrective is the existing launcher bundle, provided the launcher still resolves exactly to that path at execution time.

This task is only to finish the already-authorized REL1D-R2 client replacement safely.

Do not rebuild unless the staged REL1D-R2 artifact fails integrity checks. Do not deploy backend, run Alembic, move production, change source, call model/provider APIs, or perform the human REL1D acceptance flow.

## Exact contract

```
CLIENT_SOURCE_SHA=6693578d35c1ea1d6e25bf73768ca0cf6c07dac9
PRODUCTION_BACKEND_SHA=6693578d35c1ea1d6e25bf73768ca0cf6c07dac9
EXPECTED_ALEMBIC=0054
STAGED_BUNDLE=/home/d.yacenko/tmp/rel1d-r2-6693578-artifact/bundle
CANONICAL_LAUNCHER_BUNDLE=/home/d.yacenko/.local/share/personal-secretary-preview/19228c9d84bbc0350b78e2d0600710dc3ddf368f/bundle
EXPECTED_EXECUTABLE_SHA256=e59dcbca7f6911d3c292c9802eb1baa1fcacf7e60f7c607819b50d5b36bedab7
EXPECTED_KERNEL_SHA256=785cb75b14790c2adab5d96a11f1224d6869c3ff5964c3c4613899503594b839
```

## Bootstrap and preflight

Follow fresh `AGENTS.md`, `CURRENT_TASK.md`, `PROJECT_STATE.md`, and `docs/executor_bootstrap.md`.

Verify before mutation:

1. fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task;
2. `origin/production == CLIENT_SOURCE_SHA`;
3. production backend/source is still `CLIENT_SOURCE_SHA`;
4. no backend or migration action is needed;
5. `STAGED_BUNDLE` exists with executable, `lib/`, and `data/`;
6. staged executable SHA-256 is exactly `EXPECTED_EXECUTABLE_SHA256`;
7. if `data/flutter_assets/kernel_blob.bin` exists, its SHA-256 is exactly `EXPECTED_KERNEL_SHA256`;
8. the existing desktop launcher still resolves uniquely to `CANONICAL_LAUNCHER_BUNDLE/personal_secretary`;
9. `CANONICAL_LAUNCHER_BUNDLE` is user-writable.

If any of these fail, do not improvise, do not choose a new target, return HOLD with a sanitized blocker, and STOP.

Do not read or modify saved API tokens, secure storage, preferences, provider credentials, or user product data.

## Replacement

The currently running process from the old temporary staging artifact is not the install target.

If a `personal_secretary` process is running:

- verify its executable path;
- if it is the old staging artifact or the canonical launcher bundle, close only that process cleanly;
- do not kill unrelated processes.

Then:

1. preserve the whole existing `CANONICAL_LAUNCHER_BUNDLE` as a new local rollback backup beside the launcher target; do not overwrite the existing `bundle.rollback-rel1-r2`;
2. copy/replace the whole bundle from `STAGED_BUNDLE` into the exact canonical launcher bundle path;
3. do not edit `personal-secretary.desktop`;
4. verify installed executable SHA-256 equals `EXPECTED_EXECUTABLE_SHA256`;
5. verify installed `lib/` and `data/` exist;
6. verify installed kernel hash when present;
7. leave the old temporary staging artifact alone unless removal is explicitly necessary for this task — cleanup is not a goal.

Do not leave a mixed old/new bundle.

## Startup-only smoke

Relaunch using the same existing desktop launcher/entrypoint, not by directly running the staging artifact.

Verify only:

- the launched process executable resolves under `CANONICAL_LAUNCHER_BUNDLE`;
- process launches;
- window appears;
- process remains alive long enough to prove startup.

Do not:

- add a file;
- press `Извлечь роли`;
- press `Сопоставить`;
- prepare/approve/reject a role-import ActionPlan;
- inspect People/Tasks/Inbox for acceptance;
- create/retract roles;
- send Assistant messages;
- trigger sync;
- call model/provider APIs.

## Success completion

On success:

1. append a compact `REL1D-R2.1` factual entry to `PROJECT_STATE.md` with:
   - exact staged source SHA;
   - staged and installed executable hashes;
   - installed kernel hash if present;
   - canonical launcher bundle path;
   - rollback backup path;
   - prior running executable path;
   - confirmation that the launcher file itself was not edited;
   - startup smoke result and launched executable path;
   - config/secure storage/API URL/tokens untouched;
   - production backend/ref still exact `6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`;
   - Alembic still recorded as `0054 / 0054`;
   - no backend deploy/migration/model/provider/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - REL1D-R2.1 succeeded;
   - installed Linux client source = `6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`;
   - production backend/source/ref = same SHA;
   - human REL1D acceptance is now the next gate;
   - first human action: open Secretary, add a supported explicit role-import source, then press `Извлечь роли`;
   - Executor did not perform the human gate;
   - do not start another slice.

3. commit + push ledger updates to `main`.

4. STOP.

On any blocker:

- do not partially install;
- if replacement already started and cannot be completed safely, restore only from the newly created rollback backup when that restoration is straightforward and exact;
- otherwise stop and report the precise sanitized state without improvising;
- return HOLD;
- commit/push accurate ledger if appropriate;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
