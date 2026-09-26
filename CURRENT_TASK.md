# Current task — People P1R3: repaired one-shot production Person census

People P1R2R is accepted.

This task grants a NEW, separate authorization for exactly ONE read-only production Person census using the repaired verifier accepted at:

`38d71caded818b79398f7b5848d0d6ec07c1c2d6`

This is not a continuation/retry authorization from P1R2. P1R2 was consumed and inconclusive. P1R3 is a fresh explicit authorization after local verifier repair.

Production must remain:
- runtime/HEAD: `296b4735f9473ea60ef22f1827ed94260603128e`;
- `origin/production`: exact same SHA;
- Alembic: `0047 / 0047`.

## Freeze the verifier

Before any production connection, prove that the following files in the current checkout are byte-for-byte unchanged from accepted implementation `38d71caded818b79398f7b5848d0d6ec07c1c2d6`:

- `ops/production/people_p1_person_census.py`
- `ops/production/remote_people_p1_person_census.py`
- `ops/production/tests/test_people_p1_person_census.py`

Use Git comparison/hash evidence.

If any differ:
- do not edit them in P1R3;
- do not connect to production;
- report `P1R3_BLOCKED=verifier_changed`;
- return HOLD and STOP.

No verifier implementation changes are authorized in P1R3.

## Local preflight

Follow `docs/executor_bootstrap.md`.

Before the live census:

1. canonical repository / clean suitable checkout;
2. exact production ref available;
3. `origin/production == 296b4735f9473ea60ef22f1827ed94260603128e`;
4. run:
   `python3 -m unittest ops/production/tests/test_people_p1_person_census.py`
5. `git diff --check`.

The disposable rehearsal does not need to be repeated; P1R2R already passed it.

## Authorized production action

Run exactly the committed local entrypoint:

`ops/production/people_p1_person_census.py`

with exact release SHA:

`296b4735f9473ea60ef22f1827ed94260603128e`

Use only:
- committed `ops/production/target.json`;
- pinned host key;
- public-key-only SSH;
- existing Executor/workstation credential integration.

Do not manually reproduce the SQL through SSH.
Do not call psql separately.
Do not modify the remote helper.
Do not run a second copy of the verifier.

## One-shot rule

The NEW P1R3 authorization is consumed only after the remote helper emits:

`CENSUS_MARKER=started`

If bootstrap/SSH/preflight fails before that marker:
- the P1R3 one-shot remains unused;
- do not improvise alternate credentials/hosts;
- record one sanitized blocker;
- STOP.

Once `CENSUS_MARKER=started` occurs:
- the authorization is consumed;
- never rerun P1R3, even if blocked/malformed afterward;
- record the exact sanitized verifier outcome;
- STOP after bookkeeping.

## Expected success output

On success, the local entrypoint may output only these six integer facts:

- `PERSON_TOTAL`
- `PERSON_VISIBLE`
- `PERSON_WITH_EDGES`
- `PERSON_INCIDENT_EDGES`
- `PERSON_TASK_EDGES`
- `PERSON_FLOW_EDGES`

No titles, UUIDs, emails, handles, providers, edge types, timestamps, user/account identifiers, message content, raw rows, SQL output, stderr, or secrets may be recorded.

## Classification

If the six counts are obtained, assign exactly one:

### `P1_REAL_DATA_NOT_USEFUL_YET`

when:
- `PERSON_VISIBLE == 0`; OR
- `PERSON_TASK_EDGES == 0` AND `PERSON_FLOW_EDGES == 0`.

### `P1_REAL_DATA_CANDIDATE_EXISTS`

when:
- `PERSON_VISIBLE > 0`; AND
- at least one of `PERSON_TASK_EDGES` or `PERSON_FLOW_EDGES` is > 0.

Do not infer anything beyond those aggregate facts.

## Absolute prohibitions

P1R3 authorizes NO:

- DB write;
- migration;
- DB copy/snapshot;
- identity enrichment/backfill;
- provider call;
- worker/job action;
- service restart/recreate/pause;
- application write endpoint;
- production ref move;
- deploy;
- P2;
- H2.

The census remains inside an explicit read-only transaction.

## Completion on success

Record in `PROJECT_STATE.md`:

- verifier accepted implementation SHA `38d71caded818b79398f7b5848d0d6ec07c1c2d6`;
- production ref/Alembic verified;
- the six aggregate integer facts;
- classification;
- local verifier test result;
- confirmation that no DB write/migration/provider/service/ref/deploy action occurred.

Return `CURRENT_TASK.md` to HOLD.

Push bookkeeping to `origin/main` and STOP.

## Completion on pre-marker blocker

Record only:
- sanitized blocker;
- confirmation `P1R3_AUTHORIZATION_CONSUMED=false`;
- no production-data conclusion.

Return HOLD and STOP.

## Completion on post-marker failure

Record:
- sanitized known stage/outcome;
- confirmation `P1R3_AUTHORIZATION_CONSUMED=true`;
- no invented counts/classification.

Return HOLD and STOP.

Do not run P1R3 twice.
Do not start the next phase automatically.
