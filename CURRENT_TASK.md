# Current task — ACTIVE

## REL1-R2 — exact-production Linux client build/install for human REL1A acceptance

The user already explicitly authorized the controlled REL1A rollout, including the exact-release client install stage.

REL1-R1 production migration/backend rollout is **ARCHITECT ACCEPTED** for continuation:

- production backend/source: `6f802d6959aca40758376a83d5bdfcbbd77fc537`;
- `refs/heads/production`: `6f802d6959aca40758376a83d5bdfcbbd77fc537`;
- Alembic: `0054 / 0054`;
- migration harness: PASS;
- health: PASS;
- DB container/volume/`.env`: unchanged;
- rollback: unused.

This task is only the exact-production Linux client build/install and startup smoke needed to hand REL1A to the human acceptance gate.

Do not deploy backend, run Alembic, move production, create/retract roles, or perform any product acceptance action yourself.

## Exact authorized client source

```
CLIENT_SOURCE_SHA=6f802d6959aca40758376a83d5bdfcbbd77fc537
PRODUCTION_BACKEND_SHA=6f802d6959aca40758376a83d5bdfcbbd77fc537
EXPECTED_ALEMBIC=0054
PREVIOUS_INSTALLED_CLIENT_SOURCE=2314bf72101fbd83d50a7b264154d73740e28db1
```

Architect verified the exact client delta from the previously installed source to the production release is limited to:

- `client/lib/api/api_models.dart`
- `client/lib/api/secretary_api_client.dart`
- `client/lib/graph/graph_workspace_screen.dart`
- `client/lib/graph/person_roles_section.dart`
- `client/test/graph/person_roles_section_test.dart`

The current `main`/ledger commits are newer than the production product release. They are NOT authorized as the client build source.

## Required bootstrap

Use only the canonical repository:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- relevant client build/install notes and prior client-install ledger entry.

Verify before building:

- `origin/production == CLIENT_SOURCE_SHA`;
- exact source SHA resolves locally;
- a clean detached checkout/worktree can be created at exactly `CLIENT_SOURCE_SHA`.

Do not alter backend/runtime configuration.

Do not read, print, copy, rotate, or modify:

- saved API tokens;
- secure-storage secrets;
- provider credentials;
- user product data.

## Phase 1 — exact-source clean build

Create a clean detached checkout/worktree at exactly:

`6f802d6959aca40758376a83d5bdfcbbd77fc537`

Require:

- `git rev-parse HEAD` equals the exact SHA;
- checkout clean before build;
- `client/pubspec.yaml` and `client/pubspec.lock` come from that SHA;
- no source edit to make build/tests pass.

From `client/`:

1. `flutter pub get`;
2. run at minimum:
   - `test/graph/person_roles_section_test.dart`
   - `test/graph/people_overview_test.dart`
   - `test/graph/people_create_test.dart`
   - `test/graph/graph_workspace_screen_test.dart`
3. run focused `flutter analyze` on:
   - `lib/api/api_models.dart`
   - `lib/api/secretary_api_client.dart`
   - `lib/graph/graph_workspace_screen.dart`
   - `lib/graph/person_roles_section.dart`
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

If focused tests/build fail for a genuine release regression, do not install. Return HOLD with the exact sanitized failure.

## Phase 2 — identify the current human-used Linux client safely

Re-identify the current installed client target read-only.

Prior ledger says the previous exact-production client was installed from source `2314bf...`, but do not blindly assume the path is unchanged.

Use the running `personal_secretary` process and/or the existing desktop launcher to determine the exact executable and containing bundle directory.

Safety rules:

- exactly one unambiguous human client target;
- do not guess an install directory;
- do not create a new system-wide location merely because the current target is unclear;
- do not require or request sudo/root credentials;
- do not edit the launcher unless it is strictly necessary and the existing launcher target is unambiguous.

If the target cannot be identified safely or replacement requires unavailable privileges:

- leave the freshly built exact-release bundle intact;
- do not replace anything;
- return HOLD with sanitized artifact path + blocker;
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

Executor must NOT:

- open People/Tasks/Inbox content for product inspection;
- add/retract a role;
- create/edit Person data;
- send an Assistant message;
- approve/reject an action;
- trigger provider sync;
- call real model/provider APIs.

Ordinary pre-existing desktop accessibility warnings may be recorded if they do not stop startup. Do not broaden this task into UI/runtime cleanup.

## Human REL1A acceptance gate after install

Executor does not perform this gate.

After successful install, the human tester should validate the deployed role surface:

1. **Role section**
   - open an existing Person;
   - `Роли` section is visible and usable.

2. **Create a genuinely new role**
   - enter a role not already in the vocabulary;
   - explicit `Создать роль «…»` appears only after current-query server truth returns;
   - create succeeds.

3. **Reuse an existing role**
   - type an existing role using a lexical case/whitespace variant, e.g. `ДИРЕКТОР` for existing `Директор`;
   - existing term is suggested/reused;
   - create-new is not offered as if it were a distinct exact lexical term.

4. **Optional context**
   - assign an existing role with a distinct context;
   - context is shown with the assignment.

5. **Retract**
   - remove one role assignment;
   - it disappears from active presentation without deleting unrelated roles.

6. **Person card/detail presentation**
   - role summary appears without raw ids;
   - multiple roles render coherently.

Optional Unicode hardening spot-check, only if the human wants it:

- verify a `Straße` / `STRASSE` lexical pair resolves to one RoleTerm.

Human acceptance may create/retract test role facts by explicit human action. Executor must not manufacture those facts.

## Explicit non-goals

Do not:

- move `production`;
- deploy backend;
- run Alembic;
- modify DB/schema;
- edit client source;
- change Flutter/Dart dependencies;
- alter API base URL or credentials;
- wipe preferences or secure storage;
- install system packages requiring sudo;
- build Android;
- run real model/provider actions;
- perform human role acceptance;
- start REL1B, REL1C, REL1D, Organization, or Scheduled Activity.

## Completion protocol

On successful build + install:

1. append a compact factual REL1-R2 result to `PROJECT_STATE.md`, including:
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
   - no backend deploy/migration/production-ref/model/provider/product-data action;

2. replace `CURRENT_TASK.md` with HOLD stating:
   - installed client source = `6f802d6959aca40758376a83d5bdfcbbd77fc537`;
   - production backend/source = same exact SHA;
   - production Alembic = `0054 / 0054`;
   - first human REL1A acceptance action to perform;
   - no REL1B/REL1C/REL1D started;

3. commit + push ledger updates to `main`;

4. STOP.

On safe-install blocker:

- keep the exact-release built artifact intact;
- record sanitized blocker/path;
- return HOLD;
- do not invent another install target;
- commit/push accurate ledger if appropriate;
- STOP.

Do not start human acceptance or another product slice from this task.
