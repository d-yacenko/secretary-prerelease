# CURRENT_TASK

ACTIVE

## REL1D-R2 — exact-release Linux client build/install for human REL1D acceptance

The user already explicitly authorized the controlled REL1D rollout, including R1, R2, and the following human acceptance gate.

REL1D-R1 production backend rollout is **ARCHITECT ACCEPTED** for continuation:

- production backend/runtime: `6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`;
- `refs/heads/production`: `6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`;
- Alembic: `0054 / 0054`;
- deployment harness: PASS;
- health: PASS;
- DB container/volume/`.env`: unchanged;
- rollback: unused;
- no migration, model/provider call, or intentional product-data mutation;
- installed Linux client still: `6f802d6959aca40758376a83d5bdfcbbd77fc537`.

This task is only the exact-release Linux client build/install and startup-only smoke needed to hand the deployed REL1D flow to the human acceptance gate.

Do not deploy backend, run Alembic, move production, perform role-import extraction/grounding/approval, create/retract roles, call a real model/provider, or perform human product acceptance yourself.

## Exact authorized client source

```
CLIENT_SOURCE_SHA=6693578d35c1ea1d6e25bf73768ca0cf6c07dac9
PRODUCTION_BACKEND_SHA=6693578d35c1ea1d6e25bf73768ca0cf6c07dac9
EXPECTED_ALEMBIC=0054
PREVIOUS_INSTALLED_CLIENT_SOURCE=6f802d6959aca40758376a83d5bdfcbbd77fc537
```

The current `main` is newer because it contains rollout-control/reporting ledger changes. It is **not** authorized as the client build source.

Architect verified that the client delta from the currently installed source to the exact release is limited to:

- `client/lib/api/role_import_models.dart`
- `client/lib/api/secretary_api_client.dart`
- `client/lib/assistant/assistant_controller.dart`
- `client/lib/assistant/assistant_screen.dart`
- `client/lib/assistant/role_import_preview.dart`
- `client/lib/local/extraction/extraction_constants.dart`
- `client/lib/local/local_intake_actions.dart`
- `client/test/api/role_import_plan_api_test.dart`
- `client/test/assistant/role_import_plan_test.dart`
- `client/test/assistant/role_import_preview_test.dart`

No `pubspec.yaml` or `pubspec.lock` change is part of this release delta.

## Required bootstrap

Use only the canonical repository:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/executor_bootstrap.md`
- prior exact-production Linux client install ledger/task if needed.

Verify before building:

- fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task;
- `origin/production == CLIENT_SOURCE_SHA`;
- exact `CLIENT_SOURCE_SHA` resolves locally;
- a clean detached checkout/worktree can be created at exactly `CLIENT_SOURCE_SHA`;
- production backend/runtime and branch remain exact `PRODUCTION_BACKEND_SHA`;
- Alembic remains `0054 / 0054`.

Do not alter backend/runtime configuration.

Do not read, print, copy, rotate, or modify:

- saved API tokens;
- secure-storage secrets;
- provider credentials;
- user product data.

## Phase 1 — exact-source clean build

Create a clean detached checkout/worktree at exactly:

`6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`

Require:

- `git rev-parse HEAD` equals the exact SHA;
- checkout clean before build;
- `client/pubspec.yaml` and `client/pubspec.lock` come from that SHA;
- no source edit to make build/tests pass.

From `client/`:

1. run `flutter pub get`;
2. run at minimum:
   - `test/assistant/role_import_preview_test.dart`
   - `test/assistant/role_import_plan_test.dart`
   - `test/api/role_import_plan_api_test.dart`
   - `test/assistant/assistant_action_plan_test.dart`
   - `test/assistant/assistant_conversations_test.dart`
3. run focused `flutter analyze` on:
   - `lib/api/role_import_models.dart`
   - `lib/api/secretary_api_client.dart`
   - `lib/assistant/assistant_controller.dart`
   - `lib/assistant/assistant_screen.dart`
   - `lib/assistant/role_import_preview.dart`
   - `lib/local/extraction/extraction_constants.dart`
   - `lib/local/local_intake_actions.dart`
4. run `flutter build linux --debug`.

Do not fix unrelated source or dependency issues inside this task.

The bundle must be complete and internally consistent:

- executable `personal_secretary`;
- adjacent `lib/`;
- adjacent `data/`.

Record:

- exact source SHA;
- Flutter version;
- Dart version;
- build timestamp;
- built executable SHA-256;
- `data/flutter_assets/kernel_blob.bin` SHA-256 if present.

A local adjacent `BUILD_INFO.txt` is allowed. Do not commit generated bundle artifacts.

If a focused test, analyze gate, or build fails for a genuine release regression, do not install. Return HOLD with the exact sanitized failure and STOP.

A previously documented warning is not permission to ignore a new warning. If a warning is demonstrably identical to the accepted source baseline and non-blocking, record that exact fact; do not edit product source to silence unrelated debt.

## Phase 2 — identify the current human-used Linux client safely

Re-identify the current installed client target read-only.

Prior ledger says the currently installed exact-production client source is:

`6f802d6959aca40758376a83d5bdfcbbd77fc537`

Do not blindly assume the installation path is unchanged.

Use the running `personal_secretary` process and/or the existing desktop launcher to determine the exact executable and containing bundle directory.

Safety rules:

- exactly one unambiguous human client target;
- do not guess an install directory;
- do not create a new system-wide location merely because the current target is unclear;
- do not require or request sudo/root credentials;
- do not edit the launcher unless strictly necessary and the existing launcher target is unambiguous.

If the target cannot be identified safely or replacement requires unavailable privileges:

- leave the freshly built exact-release bundle intact;
- do not replace anything;
- record a sanitized artifact path + blocker;
- return HOLD;
- STOP.

## Phase 3 — replace the whole local bundle

If the current target is unambiguous and user-writable:

1. close only the running `personal_secretary` process cleanly if it is running;
2. preserve the entire existing bundle as a local rollback backup adjacent to or safely near the install target;
3. do not touch user configuration outside the bundle:
   - XDG config;
   - preferences;
   - secure storage;
   - API URL;
   - tokens;
   - caches/user data;
4. replace the whole bundle, not only the executable:
   - executable;
   - `lib/`;
   - `data/`;
5. verify installed executable SHA-256 equals the freshly built artifact SHA-256;
6. verify installed `lib/` and `data/` exist;
7. relaunch through the same existing user launcher/entrypoint when possible.

Do not leave a mixed old/new bundle.

## Phase 4 — startup-only smoke

Executor may perform only a startup smoke:

- process launches;
- window appears;
- process remains alive long enough to prove startup.

Executor must **not**:

- add a file for REL1D acceptance;
- press `Извлечь роли`;
- press `Сопоставить`;
- prepare/approve/reject a role-import plan;
- open People/Tasks/Inbox content for product inspection;
- create/edit/retract Person role data;
- send an Assistant message;
- approve/reject an ordinary Assistant action;
- trigger provider sync;
- call a real model/provider API.

Ordinary pre-existing desktop accessibility warnings may be recorded if they do not stop startup. Do not broaden this task into UI/runtime cleanup.

## Human REL1D acceptance gate after install

Executor does not perform this gate.

After successful install, the human tester/Architect should exercise one explicit end-to-end REL1D flow using a user-supplied PNG/JPEG/WEBP screenshot with visible names and role/title text, or another already-supported role-import source.

### A. Source + extraction

1. Open Secretary and add the source as Assistant active context.
2. Press `Извлечь роли`.
3. Verify:
   - preview heading is `Черновик извлечения ролей`;
   - extracted name / role / optional context evidence is inspectable;
   - before confirmation the UI says `Ничего не сохранено`;
   - no Person or role assignment is created merely by extraction;
   - truncation is visible if reported.

This is the human acceptance gate and may make the explicitly authorized real extraction/model call. Executor must not make it.

### B. Grounding

1. Press `Сопоставить`.
2. Verify the UI distinguishes, where applicable:
   - exact resolved existing Person;
   - ambiguous Person requiring explicit choice;
   - promotion candidate requiring explicit choice and warning that a new Person will be created only after confirmation;
   - unresolved Person, which cannot be selected.
3. Verify role vocabulary grounding distinguishes:
   - `Использовать существующую роль: ...`;
   - `Новая роль: ...`;
   - lexical suggestions are advisory and do not silently replace the extracted role.

No durable role or Person write should have happened yet.

### C. Explicit selection + frozen ActionPlan

1. Explicitly select only the row(s) intended for persistence.
2. For ambiguous/promotion rows, make an explicit Person/candidate choice first; there must be no default salience-based selection.
3. Press `Подготовить изменения`.
4. Verify the pending card:
   - says `Требует подтверждения`;
   - shows source title;
   - shows selected/total counts;
   - shows target display, existing/new Person mode, role, optional context, and existing/new vocabulary mode;
   - does not expose promotion candidate keys, raw identity values, normalized role keys, provenance internals, or other frozen canonical payload internals.
5. While the role-import plan is pending, conversation switching should be blocked rather than allowing the plan to leak into another conversation/session.

### D. Reject/no-write check

For the first prepared plan, press `Отклонить`.

Verify:

- UI says `Отклонено`;
- `Ничего не сохранено` remains true;
- no selected role assignment or new Person from that plan appears;
- if source/grounding are still current, `Изменить выбор` is available.

### E. Confirmed write

Without changing the source unnecessarily, prepare the intended selection again and press `Подтвердить`.

Verify:

- UI reports `Изменения сохранены` when something changed, or `Изменений нет` only for a truthful no-op;
- result counts and row statuses are coherent (`Применено`, `Уже было`, `Дубликат выбранной строки` as applicable);
- exactly the explicitly confirmed Person promotion/role assignments appear in People;
- existing exact RoleTerms are reused;
- a genuinely new extracted RoleTerm is created only when needed;
- semantic near-duplicates are not silently merged;
- optional context is preserved;
- approval does not append an Assistant chat message and does not perform an Assistant resume/model call.

If the source or grounding becomes stale, the UI must require new extraction or grounding rather than applying an obsolete plan.

## Explicit non-goals

Do not:

- move `production`;
- deploy backend;
- run Alembic or any migration harness;
- modify DB/schema;
- edit client source;
- change Flutter/Dart dependencies;
- alter API base URL or credentials;
- wipe preferences or secure storage;
- install system packages requiring sudo;
- build Android;
- run the human REL1D acceptance flow as Executor;
- call real model/provider APIs as Executor;
- start ORG1, Scheduled Activity, G3B, MCP expansion, or any new product slice.

## Completion protocol

On successful build + install:

1. append a compact factual `REL1D-R2` result to `PROJECT_STATE.md`, including:
   - exact source SHA;
   - Flutter/Dart versions;
   - focused test results;
   - focused analyze result;
   - build result;
   - staged artifact path;
   - executable/kernel hashes;
   - previous installed bundle path;
   - rollback-backup path;
   - installed bundle path;
   - installed executable hash verification;
   - startup-only smoke result;
   - explicit confirmation config/secure storage/API URL/tokens were untouched;
   - production backend/ref still exact `6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`;
   - Alembic still `0054 / 0054`;
   - no backend deploy/migration/production-ref/model/provider/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - REL1D-R2 succeeded;
   - installed client source = `6693578d35c1ea1d6e25bf73768ca0cf6c07dac9`;
   - production backend/source = same exact SHA;
   - production branch = same exact SHA;
   - Alembic = `0054 / 0054`;
   - first human acceptance action: add an explicit role-import source in Assistant and press `Извлечь роли`;
   - Executor did not perform the human gate;
   - do not start another slice from that HOLD.

3. commit + push ledger updates to `main`.

4. STOP.

On safe-install blocker or genuine release regression:

- keep any exact-release built artifact intact if safe;
- record only sanitized facts/paths;
- return HOLD;
- do not invent another install target;
- do not repair unrelated source;
- commit/push accurate ledger if appropriate;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
