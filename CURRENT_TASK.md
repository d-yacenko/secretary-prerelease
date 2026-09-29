# Current task — PT1-H2-HG2: exact-release final human-gate client bundle

## State

- Production application/runtime and `origin/production`: `44407ed6e972a05809d55874acaa966cc7e141c8`.
- Production Alembic: `0051 / 0051`.
- PT1-H2-R1 rollout: ACCEPTED.
- PT1-H2 source is deployed and awaits final human validation.
- People Landscape and later roadmap slices remain unauthorized.

## Goal

Build a fresh Linux debug client bundle from a clean checkout of exact production release:

`44407ed6e972a05809d55874acaa966cc7e141c8`

This is provenance/build only. Do not change product source, deploy, install, or write production Person / Task↔Person data.

## Required source checks

Verify the exact checkout contains the corrected Person-side wording:

Role choices in `Связать с задачей`:
- `Этот человек попросил выполнить`
- `Задача поручена этому человеку`
- `Ждём от этого человека`
- `Этот человек участвует`

Verify the dialog shows a selected-fact summary containing the current Person title and selected Task title before `Добавить`.

Verify Person involvement tile wording:
- `Просит выполнить`
- `Поручена этому человеку`
- `Ждём от этого человека`
- `Участвует`

Also verify:
- canonical role payloads remain `requested_by/delegated_to/waiting_on/involves`;
- add/remove/decision endpoints are unchanged;
- no generic `related_to` path is used for PT1;
- terminal Task filtering remains intact.

## Tests

Run the focused PT1 Person bridge Flutter tests from this exact checkout.

Require at minimum:
- all four role choices are directionally explicit;
- `requested_by` selected summary states that the Person requests/asks for the Task;
- `delegated_to` selected summary states that the Task is assigned to the Person;
- resulting tiles preserve those directions;
- existing add/remove/confirm/reject/navigation/idempotency/terminal-filter tests remain passing.

Run relevant Flutter analyze and `git diff --check`.

## Bundle provenance

Build into a NEW path, e.g.:

`/tmp/pt1-h2-hg2-44407ed/`

Create adjacent `BUILD_INFO.txt` with:
- full source SHA;
- build mode;
- UTC timestamp;
- launcher SHA-256;
- `data/flutter_assets/kernel_blob.bin` SHA-256;
- `EXPECTED_PT1_H2_UI=yes`;
- `PRODUCTION_SHA=44407ed6e972a05809d55874acaa966cc7e141c8`;
- statement that production was not modified.

Do not reuse the old PT1-HG1 bundle.

## Production safety

Do not:
- install or replace the client;
- deploy;
- move `origin/production`;
- create/remove/confirm/reject Task↔Person relations in production;
- modify Person data;
- start People Landscape or later roadmap work.

## Completion

1. Record exact bundle path, source SHA, checksums, focused test result and source checks in `PROJECT_STATE.md`.
2. Return `CURRENT_TASK.md` to HOLD.
3. Push documentation to `main`.
4. Report exact HOLD SHA, bundle path, checksums, tests, and confirmation production remains `44407ed6e972a05809d55874acaa966cc7e141c8`, Alembic `0051`.
5. STOP.

Do not perform the human gate yourself.
