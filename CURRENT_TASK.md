# Current task — ACTIVE

## AH2-CLI1 — exact-production Linux client build/install for human remediation regression

User explicitly authorized this client operation on 2026-10-03.

Authorization scope is exactly:

- build the Linux Flutter client from the exact current production release source;
- install/replace the currently used local Linux client bundle if and only if the existing target is identified unambiguously and can be replaced safely;
- relaunch the client for the human tester;
- no backend deploy;
- no Alembic migration;
- no production ref change;
- no production data mutation by Executor;
- no real Assistant/model/provider product test by Executor.

## Exact authorized client source

```
CLIENT_SOURCE_SHA=2314bf72101fbd83d50a7b264154d73740e28db1
PRODUCTION_BACKEND_SHA=2314bf72101fbd83d50a7b264154d73740e28db1
EXPECTED_ALEMBIC=0052
```

Architect verified before authorization:

- `origin/production = 2314bf72101fbd83d50a7b264154d73740e28db1`;
- production health is PASS;
- Alembic is `0052 / 0052`;
- there are **no changes under `client/**`** between `CLIENT_SOURCE_SHA` and the current Architect HOLD/main `d79fbab95a98cc50cab0cbd6e96992ae6f245f9a`;
- therefore the exact production SHA is also the exact accepted client source for UX-CAP1/AP1/STG1 client behavior.

The task-authorization commit is newer than `CLIENT_SOURCE_SHA` and must not be used as the build source.

## Required bootstrap

Use only the canonical repository:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read:

- `AGENTS.md`
- `CURRENT_TASK.md`
- relevant Flutter/client build notes in repository history/ledger if needed.

Do not alter backend/runtime configuration.

Do not read, print, copy, rotate, or modify saved API tokens, secure-storage secrets, provider credentials, or user data.

## Phase 1 — exact-source clean build

Create a clean detached checkout/worktree at exactly:

`2314bf72101fbd83d50a7b264154d73740e28db1`

Verify:

- `git rev-parse HEAD` equals the exact SHA;
- checkout is clean before build;
- `client/pubspec.lock` and `client/pubspec.yaml` come from that SHA;
- no source file is edited to make the build pass.

From `client/`:

1. run `flutter pub get`;
2. run focused tests that cover the accepted remediation client surfaces at minimum:
   - `test/assistant/assistant_action_plan_test.dart`
   - `test/voice/voice_assistant_a_test.dart` if present at this SHA
   - `test/capture/capture_test.dart`
   - `test/graph/graph_workspace_screen_test.dart`
   - any focused API-model test that covers `PendingAction.presentation`;
3. run focused `flutter analyze` on the changed remediation client files where practical;
4. run `flutter build linux --debug`.

Known historical baseline note:

- if the three old Graph detail-route finder failures reappear, first prove they are the same documented baseline failures rather than a new regression; do not modify product source just to silence them.
- UX-CAP1.1 previously updated those tests, so on this exact accepted source they are expected to be green; any new red result must be investigated before install.

Build must produce a complete Linux bundle including:

- `personal_secretary`;
- adjacent `lib/`;
- adjacent `data/`.

Record:

- exact source SHA;
- Flutter/Dart version;
- build timestamp;
- executable SHA-256;
- `data/flutter_assets/kernel_blob.bin` SHA-256 if present.

Optionally create a small local `BUILD_INFO.txt` adjacent to the staged artifact. Do not commit generated bundle artifacts.

## Phase 2 — identify the currently used client safely

Before replacing anything, identify the current human-used Linux client target read-only.

Use the running `personal_secretary` process and/or its existing desktop launcher to determine the exact executable and containing bundle directory.

Safety rules:

- there must be one unambiguous human client target;
- do not guess an install directory;
- do not create a new system-wide install path merely because the current target is unclear;
- do not modify desktop launchers unless the existing launcher clearly points to the bundle being replaced;
- do not require or request sudo/root credentials.

If the current target cannot be identified unambiguously or replacement would require privileges not already available non-interactively:

- do not replace anything;
- leave the new exact-release bundle built and launchable;
- return HOLD with the blocker and artifact path;
- STOP.

## Phase 3 — replace the local client bundle

If the current target is unambiguous and user-writable:

1. close only the running `personal_secretary` process cleanly;
2. preserve the existing bundle directory as a local rollback backup adjacent to or safely near the install target;
3. do **not** touch user configuration outside the bundle:
   - XDG config;
   - preferences;
   - secure storage;
   - saved API URL;
   - tokens;
   - cached user data;
4. replace the whole application bundle, not just the executable:
   - launcher/executable;
   - `lib/`;
   - `data/`;
5. verify the installed executable hash matches the freshly built artifact hash;
6. verify installed bundle has the expected `lib/` and `data/`;
7. relaunch through the same existing user entrypoint/launcher when possible.

Do not leave a mixed old/new bundle.

## Phase 4 — startup-only smoke

Executor may perform only a startup smoke:

- process launches;
- window appears;
- process remains alive long enough to prove startup;
- no product interaction.

Executor must **not**:

- open Tasks/People/Inbox content for inspection;
- send an Assistant message;
- approve/reject an action;
- create/update/delete data;
- trigger provider sync;
- call external providers.

Any ordinary accessibility warning that was already documented and does not stop the process may be recorded, but do not broaden this task to UI/runtime cleanup.

## Human regression gate after install

Executor does not perform this gate.

After successful installation, the human tester will validate at minimum:

1. **AP1 semantic approval card**
   - selected Task context;
   - stage a `waiting_on` update through the already accepted PER1/CTX1 flow;
   - approval card should show semantic text such as:
     - `Изменить задачу: <title>`
     - `Ожидает: Ольга Володько`
   - raw UUID must not be the primary label.

2. **STG1 staging truth**
   - staged mutation shows no model-authored “already changed” prose;
   - approval card remains visible.

3. **UX-CAP1 fresh capture**
   - abandon a contextual capture;
   - open global `+ Задача`;
   - prior hidden context must not leak into the fresh capture.

4. **External approval regression**
   - Gmail/Mattermost preview style remains human-readable when next exercised; no need for Executor to send anything during installation.

## Explicit non-goals

Do not:

- move `production`;
- deploy backend;
- run Alembic;
- modify DB/schema;
- change Flutter/Dart dependencies;
- edit client source;
- fix unrelated tests;
- alter API base URL or credentials;
- wipe preferences/secure storage;
- install system packages requiring sudo;
- build Android;
- run real model/provider actions;
- start Scheduled Activity work or another remediation slice.

## Completion protocol

On successful build + install:

1. append a compact factual AH2-CLI1 result to `PROJECT_STATE.md`, including:
   - source SHA;
   - Flutter/Dart version;
   - exact focused test/analyze results;
   - bundle artifact path;
   - executable/kernel hashes;
   - previous installed bundle path;
   - rollback-backup path;
   - installed bundle path;
   - successful startup-only smoke;
   - explicit statement that config/secure storage/API URL/tokens were untouched;
   - no backend deploy/migration/model/provider/product-data action;
2. return `CURRENT_TASK.md` to HOLD for the human client regression;
3. HOLD must state the installed client source SHA and the first human test to perform;
4. commit + push ledger updates to `main`;
5. STOP.

On safe-install blocker:

- keep the built artifact intact;
- record only sanitized paths/facts;
- return `CURRENT_TASK.md` to HOLD;
- do not invent another install target;
- commit/push ledger if accurate;
- STOP.

Do not start any further task from HOLD.
