# CURRENT_TASK

## Status

ACTIVE

## REL1D-A.1.1 — isolate durable role-import audit tests from shared bootstrap state

REL1D-A implementation `d1d4708d7e491131d81ced19de4495bef0c0ddc5` and REL1D-A.1 implementation `b596967aefac1f1db093ea01ec67561c578a1a3c` are functionally correct in the reviewed product path, but REL1D-A is **not yet Architect source-accepted**.

Architect review of A.1 found one remaining test-isolation defect:

- role-import extraction now correctly uses canonical `ai_trace_session`;
- canonical traces use their own durable session and intentionally survive request/product-session rollback;
- `backend/tests/test_rel1d_role_import_extraction.py` runs those tests as `BOOTSTRAP_USER_ID`;
- its normal `db_session` fixture rollback therefore does not remove the role-import `AITrace` / `AITraceEvent` rows created by the tests;
- subsequent audit/budget tests see those committed test traces, so test order changes global bootstrap-user metrics (for example `test_mixed_workload_summary_metrics` observed 21 traces in its time window).

This task fixes **test hygiene only**.

Do not start REL1D-B/C.

Do not change production extraction, audit, budget, source, upload, client, Person, RoleTerm, or role-write behavior unless an unavoidable testability defect is proven first.

No deploy, migration, client install, or real provider call.

## Product baseline that must remain byte-for-byte semantically unchanged

Preserve:

- exactly one chargeable `model_round` per successful Responses call;
- exactly one `model_round_failed` for an attempted provider call that fails before usage is reported;
- pre-call budget block emits no model event;
- `role_import_proposal` remains non-chargeable;
- 2 input + 3 output tokens = 5 daily tokens;
- canonical durable success/failure trace lifecycle;
- failed trace survives request rollback;
- audit privacy contract;
- raster/document source behavior;
- proposal-only output;
- client preview behavior;
- schema head `0054`.

Production/backend/client remain:
`6f802d6959aca40758376a83d5bdfcbbd77fc537`

Alembic remains:
`0054 / 0054`.

## Required isolation behavior

After any REL1D role-import test finishes, the persistent database must contain exactly the same pre-existing role-import audit traces it contained before that test, unless the test explicitly owns and removes its own committed fixtures during teardown.

The test suite must never:

- delete historical/pre-existing production-like bootstrap-user traces;
- delete traces created by another test/process merely because they share a workload;
- truncate AI audit tables;
- reset the bootstrap database;
- weaken durable-trace assertions;
- change production code to make traces non-durable in tests.

### Preferred correction

In `backend/tests/test_rel1d_role_import_extraction.py`, add a narrowly scoped autouse fixture/helper that:

1. before each test, using an independent real DB session, records the exact existing trace IDs for:
   - `user_id = BOOTSTRAP_USER_ID`;
   - `workload = WORKLOAD_ROLE_IMPORT_EXTRACTION`;

2. yields to the test;

3. after the test, using an independent real DB session:
   - re-reads role-import trace IDs for the bootstrap user;
   - computes only `created_ids = after_ids - before_ids`;
   - deletes `AITraceEvent` rows only for those exact `created_ids`;
   - deletes `AITrace` rows only for those exact `created_ids`;
   - commits cleanup.

This fixture must preserve any trace ID that existed before the individual test.

If FK/cascade semantics permit safe trace deletion directly, that is acceptable, but still constrain deletion to exact per-test created IDs.

Do not use a broad:
- `DELETE ... WHERE workload='role_import_extraction'`;
- user-wide audit delete;
- time-window delete.

### Concurrency safety

The repository test suite is primarily sequential, but cleanup must still be written conservatively.

Prefer one of:

- exact IDs observed/owned by the test itself; or
- baseline-delta IDs plus an additional ownership marker/object-id set created by that test.

If a baseline-delta fixture could accidentally delete another concurrently running process's trace for the same bootstrap user, strengthen ownership matching using the exact source object IDs exercised by that test or another deterministic test-only ownership mechanism.

Do not add test-only markers to production audit metadata.

## Required proof

Add/adjust focused tests/helpers so the following are demonstrably true:

1. a successful extraction test can still inspect its durable committed trace before teardown;
2. a failed extraction test can still:
   - rollback the request/product session;
   - observe the failed durable trace;
   - assert finished/success/error/event semantics;
3. a budget-block test can still observe its durable failed/blocked trace;
4. after each test teardown, only traces created by that test are removed;
5. a pre-existing bootstrap-user `role_import_extraction` trace survives cleanup untouched;
6. no `AITrace` or `AITraceEvent` from an unrelated workload is removed;
7. running the complete REL1D-A extraction test module twice does not monotonically increase bootstrap-user role-import trace count;
8. running REL1D-A extraction tests before an unrelated AI-audit summary test does not add role-import traces into that unrelated test's observed state.

Do not rewrite the unrelated summary test's expected values merely to accommodate leaked test traces.

## Verification sequence

Run at minimum:

1. record baseline persistent count/IDs of bootstrap-user `role_import_extraction` traces;
2. run:
   - `backend/tests/test_rel1d_role_import_extraction.py`;
3. re-read persistent count/IDs and prove they equal the baseline set;
4. run the same extraction module a second time;
5. prove the persistent set still equals the same baseline;
6. run:
   - `backend/tests/test_rel1d_role_import_source.py`;
   - focused AI-audit summary/list tests;
   - focused OpenAI daily-budget tests;
   - REL1A / REL1C focused regressions;
7. Ruff on changed Python;
8. `git diff --check`.

### Known unrelated failures

Do not repair these in this slice:

- `test_register_same_revision_already_ingested_skips_content`;
- `test_register_long_text_chunks_embedded_by_worker_and_ranked_in_context`;
- `test_metadata_only_upload_persisted_for_later_ingest`;
- `test_mixed_workload_summary_metrics` if it already fails from pre-existing shared DB state **after proving this slice adds zero traces to that state**;
- `test_transcription_actual_usage_blocks_the_next_paid_call` if it still independently fails because the supplied test payload is not valid WAV.

The acceptance criterion is not that unrelated historical shared-state debt magically disappears. The criterion is that REL1D tests leave **zero additional durable audit artifacts** behind and do not change those failures.

## Expected changed files

Expected product-code changes: **none**.

Expected changed file:

- `backend/tests/test_rel1d_role_import_extraction.py`

A tiny test-only helper/fixture module is acceptable if genuinely cleaner.

Do not modify production code merely to help cleanup.

If production code unexpectedly appears necessary, STOP and record the blocker instead of broadening scope.

## Production / external-effect boundary

Test/source-only.

Do not:

- move `production`;
- deploy;
- migrate;
- build/install client;
- call real OpenAI/provider;
- mutate production Person/Role/source data.

## Completion protocol

After correction:

1. append a compact REL1D-A.1.1 result to `PROJECT_STATE.md` with:
   - exact cleanup ownership rule;
   - proof pre-existing traces survive;
   - baseline IDs/count before/after first run/after second run;
   - focused test counts;
   - confirmation product code unchanged;

2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - exact test counts;
   - persistent role-import trace baseline unchanged after repeated test runs;
   - schema still `0054`;
   - production/client still `6f802d...`;
   - no deploy/migration/client/model/provider/product-data action;
   - REL1D-B/C not started;

3. commit + push to `main`;

4. STOP.

Do not start REL1D-B from HOLD.
