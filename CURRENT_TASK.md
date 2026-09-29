# Current task — PT1-HG1: exact-release human-gate client bundle

## State

- Production application/runtime and `origin/production`: `02855ee49cc2fe31cd68f4649235d61665dbbcb1`.
- Production Alembic: `0051 / 0051`.
- PT1-R1 rollout: ACCEPTED.
- PT1 source is deployed and awaits final human validation.
- People Landscape and later roadmap slices remain unauthorized.

## Goal

Build a fresh Linux debug client bundle from a clean checkout of exact production release:

`02855ee49cc2fe31cd68f4649235d61665dbbcb1`

This is a provenance/build task only. Do not change product source, deploy, install, or write production Person / Task↔Person data.

## Required source checks

From the exact checkout, verify the client contains:

- Person section `Участие в задачах`;
- action `Связать с задачей`;
- role choices `Запросил`, `Поручено`, `Ждём`, `Участвует`;
- Person involvement model includes `edge_id`;
- Task picker excludes terminal-for-reads statuses through the shared lifecycle helper;
- Person-side add calls canonical `POST /tasks/{task_id}/actors`;
- remove calls canonical `DELETE /tasks/{task_id}/actors/{edge_id}`;
- proposed actor uses canonical relation decision endpoint;
- no generic `related_to` path is used for PT1.

## Tests

Run focused Flutter PT1/Person bridge tests from this exact checkout.

Require at minimum:
- active Task can be linked from Person with an explicit role;
- terminal Tasks are absent from picker;
- second role on same Task remains a separate involvement row;
- linked-task count does not increment for a second role on the same Task;
- confirmed role can be removed;
- proposed role can be confirmed/rejected;
- task navigation still works.

Run relevant Flutter analyze and `git diff --check`.

## Bundle provenance

Build into a NEW path, for example:

`/tmp/pt1-hg1-02855ee/`

Create adjacent `BUILD_INFO.txt` containing:
- full source SHA;
- build mode;
- UTC build timestamp;
- launcher SHA-256;
- `data/flutter_assets/kernel_blob.bin` SHA-256;
- `EXPECTED_PT1_UI=yes`;
- `PRODUCTION_SHA=02855ee49cc2fe31cd68f4649235d61665dbbcb1`;
- statement that production was not modified.

Do not reuse prior PC1 bundles.

## Production safety

Do not:
- install or replace the client;
- deploy;
- move `origin/production`;
- create/remove/confirm/reject Task↔Person relations in production;
- write Person data;
- start People Landscape or later roadmap work.

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
   - confirmation production remains `02855ee49cc2fe31cd68f4649235d61665dbbcb1`, Alembic `0051`.
5. STOP.

Do not perform the human gate yourself.
