# Current task — People P1R2R: local-only census verifier contract repair

People P1R2 is INCONCLUSIVE.

The single production census authorization was consumed after `CENSUS_MARKER=started`. Do not rerun production in this task.

Static review found two concrete verifier contract defects:

1. Remote `run_census()` sends:
   - `BEGIN TRANSACTION READ ONLY;`
   - aggregate `SELECT`
   - `COMMIT;`
   through `psql -At`, then requires exactly one non-empty stdout line.
   Normal psql command-status output can add `BEGIN` and `COMMIT`, so a valid census row can be rejected as `census_output`.

2. Local `parse_remote_output()` recognizes `CENSUS_BLOCKED=...` only when it is the only output line.
   Once the one-shot marker has been emitted, a legitimate:
   `CENSUS_MARKER=started`
   `CENSUS_BLOCKED=census_output`
   response is incorrectly collapsed to `malformed` instead of a consumed blocked stage.

P1R2R is LOCAL ONLY.

## Absolute scope guard

Do NOT:
- SSH;
- contact production host;
- call production HTTP;
- access production DB;
- call providers;
- move `origin/production`;
- migrate production;
- deploy;
- copy production data;
- consume or request another production census authorization.

If a test accidentally attempts network access, fail the task.

## Goal

Repair and prove the verifier protocol so a future separately-authorized census can:

- preserve the exact six aggregate integer facts on success;
- distinguish pre-marker failure from post-marker/consumed failure;
- never label a known consumed blocked stage as generic `malformed`;
- remain fail-closed on unexpected output;
- remain aggregate-only and read-only.

Do not produce or infer production Person counts in P1R2R.

## A. Reproduce the P1R2 failure locally

Add a focused regression proving the current failure mechanism.

Prefer one of:

1. disposable local PostgreSQL/psql integration test; or
2. deterministic mocked subprocess output that exactly matches real psql command tags.

At minimum prove that the old remote assumption fails on output shaped like:

`BEGIN`
`on|3|2|1|4|1|2`
`COMMIT`

and document whether the local installed psql/Postgres rehearsal actually emits command tags under the exact old flags.

Record this in tests/comments or a short section in `docs/people_p1_real_data_readiness.md`.

## B. Fix remote psql contract

Make `run_census()` deterministic.

Preferred design:

- invoke psql with no user startup file (`-X`);
- use quiet/tuples-only/unaligned flags as appropriate;
- preserve `ON_ERROR_STOP`;
- preserve an explicit read-only transaction;
- parse exactly ONE census data row, while handling only explicitly expected psql command-status lines if they can still occur.

Do not simply "take the middle line" or ignore arbitrary extra stdout.

Allowed outputs must be structurally enumerated.

The data row must still be exactly:

`on|<int>|<int>|<int>|<int>|<int>|<int>`

and `parse_census_row` must continue to verify transaction read-only state.

Unexpected lines remain failure.

## C. Fix local remote-output protocol

`parse_remote_output()` must distinguish these cases:

### Pre-marker blocked
Exactly:
`CENSUS_BLOCKED=<known stage>`

Result:
- raise known stage;
- `consumed == false`.

### Post-marker blocked
Exactly:
`CENSUS_MARKER=started`
`CENSUS_BLOCKED=<known stage>`

Result:
- raise that known stage;
- `consumed == true`.

### Success
Exactly:
- `CENSUS_MARKER=started`
- `CENSUS_PREFLIGHT=pass`
- `CENSUS_READ_ONLY=on`
- six known integer facts in canonical order.

### Anything else
`malformed`, preserving whether the exact marker occurred.

Do not accept duplicate facts, reordered facts, unknown keys, raw rows, titles, IDs, or arbitrary diagnostic text.

## D. Preserve privacy/output boundary

The verifier must still be structurally unable to print production row content.

Tests must prove:

- only the six fact keys can pass success parsing/formatting;
- a leaked extra line fails;
- a raw psql row is never emitted by the local success formatter;
- stderr/raw subprocess output is not echoed on failure;
- no Person names/IDs/provider details can flow through the parser API.

## E. Read-only guarantee

Keep the census SQL read-only.

Improve the static test if needed so it checks actual SQL/token boundaries rather than fragile substring accidents.

No write statement, migration, service mutation, provider call, or application endpoint mutation may be added.

## F. Local end-to-end rehearsal

Run the corrected remote helper census path against a disposable local PostgreSQL database if practical.

A representative local fixture can use synthetic counts only.

Prove:

- transaction reports read-only `on`;
- exactly six integers survive remote parsing;
- local parser accepts the helper protocol;
- `classify()` yields both decision branches on synthetic fixtures;
- malformed/additional output fails closed.

If Docker/Postgres is unavailable, document that and use a faithful subprocess/psql fixture. Do not substitute production.

## Tests

Run at minimum:

- `python3 -m unittest ops/production/tests/test_people_p1_person_census.py`;
- any new local integration/rehearsal test;
- `git diff --check`.

No Flutter build.
No backend product test suite is required unless product code is unexpectedly touched; product code should not be touched.

## Documentation

Append a concise P1R2 postmortem to:

`docs/people_p1_real_data_readiness.md`

State:

- P1R2 produced no usable counts;
- one-shot was consumed;
- exact verifier protocol defect;
- counts cannot be reconstructed from stored repo state;
- P1R2R repairs the verifier only;
- any second production census requires a new explicit authorization.

Do not speculate about actual production Person counts.

## Completion

Record in `PROJECT_STATE.md`:

- implementation SHA;
- exact root cause reproduced;
- exact protocol repair;
- local rehearsal/test results;
- explicit confirmation that production/SSH/network/providers were untouched;
- whether verifier is READY_FOR_NEW_AUTHORIZATION or still blocked.

Return `CURRENT_TASK.md` to HOLD.

Push to `origin/main` and STOP.

Do not rerun production.
Do not authorize yourself a second census.
Do not start DB copy, migration, P2, H2, or deploy.
