# Current task — PC1-H2-HG1: exact-release human-gate client bundle

## State

- Production application/runtime and `origin/production`: `93dd1e923dfd8df2860db390bf81cf8a0cc80802`.
- Production Alembic: `0051 / 0051`.
- PC1-H2-R1 rollout: ACCEPTED.
- PC1 is deployed and awaits final human merge/undo validation.
- PT1 and later roadmap slices remain unauthorized.

## Goal

Build a fresh Linux debug client bundle from a clean checkout of exact production release:

`93dd1e923dfd8df2860db390bf81cf8a0cc80802`

This is a provenance/build task only. Do not change product source, deploy, install, or write production Person data.

## Required source checks

From the exact checkout, verify the client contains:

- `ValueKey('person-merge')`;
- `Объединить с…`;
- `Поменять, кто останется`;
- `Предложен из-за контакта:`;
- merge picker calls `getPeopleWorkspace(query: ...)`, not generic `searchObjects(... kind: 'person')`;
- client methods `previewPersonMerge`, `applyPersonMerge`, `undoPersonMerge`.

## Tests

Run focused Flutter consolidation tests from this exact checkout.

Require the current H2/H2.1 consolidation expectations to pass, including:

- partial identity substring finds another Person;
- current Person excluded;
- preselected conflict preview shows exact cue;
- swap survivor action present;
- blocker disables final merge;
- undo UI remains present.

Run relevant Flutter analyze for touched consolidation files if practical, and `git diff --check`.

## Bundle provenance

Build into a NEW path that cannot be confused with the old PC1-HG1 bundle.

Recommended root:

`/tmp/pc1-h2-hg1-93dd1e9/`

Create adjacent `BUILD_INFO.txt` containing at least:

- full source SHA;
- build mode;
- UTC build timestamp;
- launcher SHA-256;
- `data/flutter_assets/kernel_blob.bin` SHA-256;
- `EXPECTED_PC1_H2_UI=yes`;
- `PRODUCTION_SHA=93dd1e923dfd8df2860db390bf81cf8a0cc80802`;
- statement that production was not modified.

Do not reuse the old `/tmp/pc1-hg1-a3d546b` bundle.

## Production safety

Do not:

- install or replace the client;
- deploy;
- move `origin/production`;
- execute merge/undo;
- confirm/reject/restore/rename Person data;
- attempt to repair the human tester's existing Person state;
- start PT1 or later roadmap work.

## Completion

1. Record exact bundle path, source SHA, checksums and focused test result in `PROJECT_STATE.md`.
2. Return `CURRENT_TASK.md` to HOLD.
3. Push documentation to `main`.
4. Report:
   - exact HOLD commit;
   - bundle path;
   - launcher SHA-256;
   - kernel SHA-256;
   - focused Flutter result;
   - source checks;
   - confirmation production remains `93dd1e923dfd8df2860db390bf81cf8a0cc80802`, Alembic `0051`.
5. STOP.

Do not perform the human gate yourself.
