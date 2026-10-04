# CURRENT_TASK

ACTIVE

## REL1D-HG2A.1 — isolate the generic 400-row budget regression test

REL1D-HG2A implementation:

`2cb5a2fe583333da5dfd1fd13d40be404b6fecae`

is **NOT YET SOURCE-ACCEPTED** only because one required focused test is red.

Current focused result:

- 155 passed
- 1 failed
- pre-existing HTTP 422 warning

The sole failure is:

`backend/tests/test_person_c3_communication_count.py::test_count_stops_at_the_communication_scan_budget`

Architect review found this is a test-isolation defect, not evidence of an HG2A runtime regression.

The test:

- monkeypatches generic `MAX_PERSON_SCAN_ROWS` to 1;
- creates its matched communication fixtures at fixed `NOW=2026-09-24T12:00Z`;
- uses the shared bootstrap user;
- therefore any newer baseline communication rows already present for that same user legitimately occupy the one-row newest-first scan and make the test fixture invisible.

This task is ONLY to make that generic budget test deterministic and isolated.

Do not change HG2A runtime semantics.

## Exact live state

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `backend/tests/conftest.py`
- `backend/tests/test_person_c3_communication_count.py`
- `backend/tests/test_rel1d_hg2a_scan_window.py`
- HG2A runtime files touched by `2cb5a2fe...` only for regression awareness.

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.

Do not move `production`.

## Required implementation

Fix the failing generic budget test by isolating it from any pre-existing communication rows for the bootstrap user.

Preferred shape:

- create a unique test User inside the current `db_session` transaction;
- issue a bearer token for that user using existing test fixtures/helpers;
- run the same People workspace/API assertion under that isolated user;
- create the Person, identity, and communication fixtures for that isolated user;
- preserve the test's actual contract:
  - generic `MAX_PERSON_SCAN_ROWS` monkeypatched to 1;
  - newest matching communication is counted;
  - `recent_communication_count == 1`;
  - `recent_communication_count_truncated is True`.

If the adjacent test:

`test_truncated_scan_does_not_report_a_missing_older_message_as_complete_zero`

has the same bootstrap-user/fixed-time brittleness, isolate it in the same bounded change so both generic budget tests are deterministic.

An equivalent minimal isolation strategy is acceptable only if it proves independence from arbitrary pre-existing rows and does not mutate runtime code.

## Explicit constraints

Do not solve the test by:

- changing message ordering;
- changing `MAX_PERSON_SCAN_ROWS`;
- changing the new 10,000 role-import ceiling;
- changing cutoff/lookback semantics;
- changing production service defaults;
- weakening assertions;
- deleting or rewriting unrelated baseline DB rows;
- using future timestamps to "win" ordering;
- globally cleaning the test database;
- modifying connector code;
- modifying role-import runtime code merely to satisfy the test.

Runtime Python under `backend/app/**` should remain unchanged unless an actual independent runtime bug is discovered. If such a bug is discovered, STOP and return HOLD instead of expanding scope.

## Required checks

Run the isolated failing test first.

Then run the same seven-file focused HG2A pytest set used for implementation review, including at minimum:

- `backend/tests/test_person_c3_communication_count.py`
- `backend/tests/test_rel1d_hg2a_scan_window.py`
- `backend/tests/test_rel1d_role_import_grounding.py`
- `backend/tests/test_rel1d_role_import_participants.py`
- `backend/tests/test_rel1d_role_import_mentions.py`
- `backend/tests/test_rel1d_role_import_batch.py`
- directly affected generic Person promotion tests

Expected acceptance gate:

- 0 failed.

The previous total was 155 passed / 1 failed; if test selection is identical, the expected result is 156 passed / 0 failed.

Also run:

- Ruff on touched Python/test files;
- `git diff --check`.

Do not rerun client tests; client is untouched.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG2A.1` entry to `PROJECT_STATE.md` stating:
   - implementation SHA;
   - test files changed;
   - exact isolation strategy;
   - isolated failing test result;
   - full focused HG2A test result;
   - Ruff/diff-check result;
   - explicit confirmation runtime HG2A source/semantics were not changed;
   - explicit no deploy/install/migration/provider/model/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2A.1 implementation SHA;
   - HG2A + HG2A.1 ready for Architect source review;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - do not start connector normalization or rollout without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker:

- record exact bounded blocker;
- return HOLD;
- do not change runtime semantics to force green;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
