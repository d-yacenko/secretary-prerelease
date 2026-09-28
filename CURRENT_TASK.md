# Current task — PP1-HG1: exact human-gate client bundle

## State

- People PP1-R1 is deployed and accepted at production/runtime `07bd8bafdb2f53a6a8475fc2d792687fa373a149`, Alembic `0051`.
- Human PP1 acceptance is pending.
- The user currently does not see the promotion suggestions and may be running an older installed desktop client.
- Exact client source at release `07bd8bafdb2f53a6a8475fc2d792687fa373a149` contains the PP1 sections «Предлагаемые люди» and «Скрытые предложения».
- Do not change production, schema, provider state, or product behavior in this task.

## Goal

Produce a fresh Linux debug bundle from the **exact production release SHA** so the human PP1 gate can be tested with an unambiguous client artifact.

This is build/provenance work only.

## Required procedure

1. Use a fresh canonical checkout per `docs/executor_bootstrap.md`.
2. Fetch and verify exact commit:
   `07bd8bafdb2f53a6a8475fc2d792687fa373a149`.
3. Verify before build that at that exact commit:
   - `client/lib/graph/graph_workspace_screen.dart` contains «Предлагаемые люди»;
   - it contains «Скрытые предложения»;
   - the client API/model code contains the PP1 promotion fields/actions.
4. Build Linux debug from that exact detached commit.
5. Do not alter source to make the build succeed. If the exact release does not build, STOP and report.
6. Place/copy the completed bundle under a fresh clearly named temp directory containing `pp1-human-07bd8ba` in its path.
7. Compute SHA-256 of:
   - `personal_secretary` executable;
   - optionally the complete bundle manifest if convenient.
8. Write a small plain-text `BUILD_INFO.txt` adjacent to the executable containing only:
   - source SHA;
   - build mode;
   - executable SHA-256;
   - build timestamp;
   - statement that production backend target was not modified.
   This file is artifact provenance only; do not add it to application source or Git.
9. Do **not** replace/install the user's existing client automatically. Human must launch the exact reported executable path explicitly.

## Verification

Run the focused Flutter PP1 promotion tests from the exact release source before/after build as appropriate.

At minimum confirm the tests covering:
- suggested people rendering;
- add;
- suppress;
- restore.

No backend test rerun is required unless the build unexpectedly depends on backend code.

## Explicitly out of scope

- No source-code change.
- No version bump.
- No production deploy or ref movement.
- No DB write.
- No provider/model call.
- No promotion approval/suppression on behalf of the user.
- No installing/replacing the current desktop client.
- No next People/Person Knowledge slice.
- No synthetic production data.

## Completion

1. Record in `PROJECT_STATE.md` the exact bundle path, source SHA, executable SHA-256, and test result.
2. Return `CURRENT_TASK.md` to HOLD with human PP1 acceptance still pending.
3. Commit/push documentation-only completion to `main`.
4. Report the exact executable path and checksum, then STOP.

The human gate is performed by the user by launching that exact executable.
