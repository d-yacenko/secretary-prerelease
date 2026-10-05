# CURRENT_TASK

ACTIVE

## REL1D-HG2D3.1 — fail-closed HG2 preflight harness corrective

REL1D-HG2D3 implementation:

`2d98c4a85a4d0825bddb62b1da9bfbfed2201791`

is NOT YET source-accepted.

The overall D3 architecture is accepted, but two narrow correctness issues must be fixed before any live production census is authorized.

Production/backend remains:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic remains:

`0054 / 0054`

This task is SOURCE-ONLY.

Do NOT run SSH.
Do NOT query production.
Do NOT call providers.
Do NOT run repair.

## Allowed files

Change only:

- `ops/production/remote_hg2_repair_preflight.py`
- `ops/production/tests/test_hg2_repair_preflight.py`

Do not change the local entrypoint unless a test proves it is strictly required for these two fixes. Prefer no change to:

- `ops/production/hg2_repair_preflight.py`

No backend/app, backend/tests, schema, dependency, deploy harness, target, client, or ledger-unrelated file changes.

## Corrective 1 — exact single Alembic head

Current defect:

`require_alembic_output(...)` accepts output merely containing:

`0054 (head)`

That is not fail-closed because multi-head output could pass.

Change the guard so success requires exactly one non-empty logical line and that line is exactly:

`0054 (head)`

Reject at minimum:

- `0054`
- `0053 (head)`
- `0054 (head)\n0055 (head)`
- `0055 (head)\n0054 (head)`
- `0054 (head) extra`
- empty output

Whitespace around the one logical line may be normalized only in the same conservative manner already used elsewhere in production harnesses.

Do not change expected Alembic from `0054`.

## Corrective 2 — Yandex structured-key presence must match HG2C6 mutation semantics

Deployed HG2C6 only adds a structured field when the metadata key is ABSENT:

- `"to_participants" not in metadata`
- `"cc_participants" not in metadata`

It preserves an existing key exactly, even when its value is `None`.

The D3 census must use the SAME key-presence semantics.

Change Yandex classifier presence logic so:

- a key is PRESENT iff `key in metadata`;
- value `None`, empty list, or non-empty list are all existing values;
- a row is missing structured data only when at least one of the two keys is ABSENT.

Consequences to prove:

1. both keys present, even if one or both values are `None`:
   - not a Yandex coarse candidate;
   - counted under `YANDEX_ALREADY_ENRICHED` / both-keys-present bucket according to the existing protocol name;
   - no local-repairable count.

2. one key present as `None`, the other key absent:
   - still a coarse candidate because HG2C6 may add the absent key;
   - local provenance classification proceeds normally;
   - the existing `None` key is not described as writable/replaceable.

3. both keys absent:
   - unchanged existing candidate behavior.

Do NOT change Gmail semantics. Gmail already uses exact key presence and matches HG2C5.

Do NOT modify HG2C6 service in this task.

## Visibility note

No visibility change is required.

Architect review confirmed that D3 query excludes `deleted_at IS NOT NULL` rows before classification, and the remaining `status == "deleted"` check is equivalent to the remaining branch of deployed `is_object_hidden_from_active_reads`.

Do not broaden this task into a visibility refactor.

## Required tests

Update/add focused tests proving at minimum:

1. exact single `0054 (head)` passes;
2. each malformed/multi-head Alembic example above fails with stage `alembic`;
3. Yandex both keys present with `None` values is not coarse/local-repairable and is counted as both-keys-present/already-enriched;
4. Yandex one existing `None` key + one absent key remains a candidate, with local provenance behavior unchanged;
5. Yandex both keys absent remains a candidate;
6. existing aggregate leakage/parser tests remain green;
7. zero-provider/read-only source proofs remain green.

Run at minimum:

- `python3 -m pytest -q ops/production/tests/test_hg2_repair_preflight.py`
- `python3 -m pytest -q ops/production/tests/test_people_p1_person_census.py`
- Ruff on the two touched files;
- `git diff --check`.

Record exact totals.

## Explicit non-goals

Do not:

- execute the preflight harness;
- connect by SSH;
- query production DB;
- call providers;
- run any repair/sync/backfill/reconcile;
- change production ref/runtime;
- change any HG2 repair service;
- change schema/migrations/dependencies;
- build/install client;
- start human REL1D acceptance.

## Completion protocol

On success:

1. append compact factual `REL1D-HG2D3.1` entry to `PROJECT_STATE.md` with:
   - implementation SHA;
   - exact two source/test files changed;
   - exact single-head Alembic behavior;
   - exact Yandex key-presence semantics;
   - test totals;
   - Ruff/diff-check results;
   - explicit no SSH/production/provider/repair action;
2. replace `CURRENT_TASK.md` with HOLD stating:
   - D3.1 implementation SHA;
   - D3/D3.1 harness ready for Architect review;
   - production remains `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`;
   - Alembic remains `0054 / 0054`;
   - no live census/repair/provider call without fresh Architect authorization;
3. commit + push to `main`;
4. STOP.

On blocker:

- record the exact bounded blocker;
- do not widen scope;
- HOLD;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
