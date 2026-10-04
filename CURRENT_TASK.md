# CURRENT_TASK

ACTIVE

## REL1D-HG-R2 — exact-release Linux client build/install for accepted HG1.1/HG1.2

REL1D-HG-R1 backend rollout is accepted for continuation.

Exact live production state:

```
CLIENT_SOURCE_SHA=1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320
PRODUCTION_BACKEND_SHA=1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320
PREVIOUS_INSTALLED_CLIENT_SOURCE=6693578d35c1ea1d6e25bf73768ca0cf6c07dac9
EXPECTED_ALEMBIC=0054
CANONICAL_LAUNCHER_BUNDLE=/home/d.yacenko/.local/share/personal-secretary-preview/19228c9d84bbc0350b78e2d0600710dc3ddf368f/bundle
```

The accepted client product delta from the currently installed source is limited to:

- `client/lib/assistant/assistant_screen.dart`
- `client/lib/assistant/role_import_preview.dart`
- `client/test/assistant/role_import_preview_test.dart`
- `client/test/assistant/role_import_scroll_test.dart`

No `pubspec.yaml` or `pubspec.lock` change is part of this release delta.

This task is ONLY the exact-release Linux client build/install and startup smoke.

Do not deploy backend, move production, run Alembic, perform the human REL1D acceptance flow, call a real model/provider, or mutate product data.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- prior REL1D-R2/R2.1 client rollout ledger if needed.

Verify before building:

1. fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task;
2. fresh `origin/production == CLIENT_SOURCE_SHA`;
3. production backend/runtime remains exact `PRODUCTION_BACKEND_SHA`;
4. production Alembic remains `0054 / 0054`;
5. exact `CLIENT_SOURCE_SHA` resolves locally;
6. a clean detached checkout/worktree can be created exactly at `CLIENT_SOURCE_SHA`.

Do not alter backend/runtime configuration.

Do not read, print, copy, rotate, or modify:

- saved API tokens;
- secure-storage secrets;
- provider credentials;
- user product data.

## Phase 1 — exact-source clean client build

Create a clean detached checkout/worktree at exactly:

`1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320`

Require:

- `git rev-parse HEAD` equals that exact SHA;
- checkout clean before build;
- `client/pubspec.yaml` and `client/pubspec.lock` come from that SHA;
- no source edit to make build/tests pass.

From `client/`:

1. run `flutter pub get`;
2. verify `pubspec.yaml` and `pubspec.lock` remain unchanged;
3. run at minimum:
   - `test/assistant/role_import_preview_test.dart`
   - `test/assistant/role_import_plan_test.dart`
   - `test/assistant/role_import_scroll_test.dart`
   - `test/assistant/assistant_action_plan_test.dart`
   - `test/assistant/assistant_conversations_test.dart`
4. run focused `flutter analyze` on:
   - `lib/assistant/assistant_screen.dart`
   - `lib/assistant/role_import_preview.dart`
   - the new/modified focused test files if supported by the normal project analyze workflow;
5. run `flutter build linux --debug`.

Do not fix unrelated source or dependency issues inside this task.

The bundle must contain:

- executable `personal_secretary`;
- adjacent `lib/`;
- adjacent `data/`.

Record:

- exact source SHA;
- Flutter version;
- Dart version;
- build timestamp;
- executable SHA-256;
- `data/flutter_assets/kernel_blob.bin` SHA-256 if present;
- staged artifact path.

If a focused test, analyze gate, or build fails for a genuine regression, do not install. Return HOLD with the exact sanitized failure and STOP.

A warning demonstrably identical to the accepted source baseline may be recorded as pre-existing/non-blocking; do not edit unrelated source merely to silence it.

## Phase 2 — canonical install target verification

The canonical installed human client target is the existing bundle referenced by the unchanged `personal-secretary.desktop` launcher:

`/home/d.yacenko/.local/share/personal-secretary-preview/19228c9d84bbc0350b78e2d0600710dc3ddf368f/bundle`

Verify at execution time:

- the launcher still resolves uniquely to `CANONICAL_LAUNCHER_BUNDLE/personal_secretary`;
- the current installed bundle exists;
- the target is user-writable;
- current installed executable/kernel correspond to the prior exact-release client or are otherwise unambiguously the launcher installation.

Do not choose another install target.

If the launcher no longer resolves exactly to the canonical bundle, return HOLD and STOP.

## Phase 3 — replace the whole launcher bundle

If a `personal_secretary` process is running:

- verify its executable path;
- close only the Secretary process cleanly;
- do not kill unrelated processes.

Then:

1. preserve the entire current canonical bundle as a **new** rollback backup beside the target;
2. do not overwrite:
   - `bundle.rollback-rel1-r2`;
   - `bundle.rollback-rel1d-r2`;
   - any prior rollback backup;
3. replace the whole canonical bundle with the freshly built exact-release bundle:
   - executable;
   - `lib/`;
   - `data/`;
4. do not edit `personal-secretary.desktop`;
5. verify installed executable SHA-256 equals the freshly built artifact;
6. verify installed kernel SHA-256 when present;
7. verify installed `lib/` and `data/` exist.

Do not leave a mixed old/new bundle.

Do not touch configuration or user-data locations outside the bundle:

- XDG config;
- preferences;
- secure storage;
- API URL;
- tokens;
- caches/user product data.

## Phase 4 — startup-only smoke

Relaunch via the same existing desktop launcher/entrypoint.

Verify only:

- launched executable resolves under `CANONICAL_LAUNCHER_BUNDLE`;
- process starts;
- window appears;
- process remains alive long enough to prove startup.

Ordinary pre-existing Atk/accessibility warnings may be recorded if they do not stop startup.

Executor must **not**:

- attach a role-import source;
- press `Извлечь роли`;
- press `Сопоставить`;
- select Person/promotion rows;
- prepare/approve/reject a role-import plan;
- inspect People/Tasks/Inbox for product acceptance;
- create/retract roles;
- send Assistant messages;
- trigger sync;
- call model/provider APIs.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG-R2` entry to `PROJECT_STATE.md`, including:
   - exact client source SHA;
   - Flutter/Dart versions;
   - focused test/analyze/build results;
   - staged artifact path;
   - executable/kernel hashes;
   - canonical installed bundle path;
   - rollback backup path;
   - installed hash verification;
   - startup smoke and launched executable path;
   - launcher file unchanged;
   - config/secure storage/API URL/tokens untouched;
   - production backend/ref still exact `1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320`;
   - Alembic still `0054 / 0054`;
   - no backend deploy/migration/model/provider/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - REL1D-HG-R2 succeeded;
   - installed Linux client source = `1879aabc97bfc5ed13fbc2ffa4d0c9c7ccbb3320`;
   - production backend/source/ref = same SHA;
   - Alembic = `0054 / 0054`;
   - HG1.1/HG1.2 are now deployed on backend and client;
   - human REL1D acceptance is the next gate;
   - first human action is to reopen Secretary with a role-import source and repeat extraction/grounding;
   - Executor did not perform the human gate;
   - do not start another slice.

3. commit + push ledger updates to `main`.

4. STOP.

On blocker:

- keep the freshly built exact-release artifact intact when safe;
- do not improvise another install target;
- record precise sanitized state;
- return HOLD;
- commit/push accurate ledger if appropriate;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
