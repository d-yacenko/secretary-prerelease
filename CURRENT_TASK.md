# Current task — Telegram MTProto M4BD1: build read-only post-deploy acceptance probe

## Status

M4BC1 schema-neutral production deploy is COMPLETE / PASS.

Production runtime/ref:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

Alembic:
`0046`

Deployment evidence:
- `HEALTH=PASS`
- `DB_CONTAINER_UNCHANGED=true`
- `DB_VOLUME_UNCHANGED=true`
- `ENV_FILE_UNCHANGED=true`
- `API_RECREATED=true`
- `WORKER_RECREATED=true`
- `DEPLOYMENT=PASS`

No manual Telegram/provider action was part of the deploy.

## Goal

Build, test, and commit a production-compatible read-only acceptance probe for the post-M4BB1 state.

The probe is for a later separately-authorized human-shell live run. DO NOT run it against production in this task.

The probe must establish, without Telegram/provider calls and without DB writes:

1. exact production runtime/ref and Alembic;
2. exactly one MTProto account and exactly one configured sync folder;
3. current count of `scope_active=true` chat selections;
4. count of active selections that were manually selected vs folder-only;
5. aggregate shallow-bootstrap state across active selections:
   - count with `history_latest_message_id IS NOT NULL`;
   - count with `history_complete=true`;
   - count with `history_backfill_before_message_id IS NULL`;
   - count with `history_cutoff_at IS NULL`;
6. per-peer canonical MTProto object counts only as sanitized aggregate distribution, sufficient to detect any peer exceeding the shallow-bootstrap bound of 20 without printing peer IDs/titles/messages/account IDs;
7. total MTProto object count for current account and total inbound/outbound counts;
8. whether any MTProto object has an embedding or current embedding provenance / whether any pending/running embed job targets MTProto objects, reported only as aggregate counts;
9. no Inbox mutation, no reconciliation, no history fetch, no provider access.

## Acceptance-oriented output

Output only sanitized aggregate facts. Do not print:
- account IDs;
- peer IDs;
- usernames/titles;
- message IDs;
- bodies;
- external IDs;
- provider references;
- encrypted session material;
- credentials or hashes.

At minimum include fields equivalent to:

```text
PRODUCTION_RELEASE=...
ALEMBIC=0046
ACCOUNT_COUNT=1
CONFIGURED_FOLDER_COUNT=1
ACTIVE_SCOPE_COUNT=...
MANUAL_ACTIVE_COUNT=...
FOLDER_ONLY_ACTIVE_COUNT=...
LATEST_CURSOR_PRESENT_COUNT=...
HISTORY_COMPLETE_COUNT=...
BACKFILL_CURSOR_PRESENT_COUNT=...
HISTORY_CUTOFF_PRESENT_COUNT=...
ACTIVE_PEERS_WITH_OBJECTS_GT_20=...
ACTIVE_PEER_OBJECT_COUNT_MAX=...
MTPROTO_OBJECT_COUNT=...
MTPROTO_INBOUND_COUNT=...
MTPROTO_OUTBOUND_COUNT=...
MTPROTO_OBJECTS_WITH_EMBEDDING=...
MTPROTO_PENDING_RUNNING_EMBED_JOBS=...
TELEGRAM_NETWORK_CALLS=0
DB_WRITES=0
```

If a safe aggregate cannot be proven without exposing identifiers or mutating state, omit it and document that limitation in `PROJECT_STATE.md`.

## Important interpretation boundary

This probe may run after one or more natural recurring worker cycles. Therefore:
- it must not assume all 28 active peers have already been visited by history sync;
- it must distinguish scope activation from bootstrap completion;
- it must not treat fewer-than-28 bootstrapped peers as failure by itself;
- it must detect any evidence of deep backfill (for example active folder-only peers with object count >20 attributable to the new scope path) without overclaiming where pre-existing manual history makes attribution ambiguous.

The one legacy manually-selected peer may legitimately have more than 20 historical objects. Do not count that peer as evidence of deep folder bootstrap. The critical deep-backfill check applies to folder-only active peers.

## Implementation constraints

Prefer the established production probe pattern under `ops/production/`:
- committed target/pinned host-key contract;
- bundled Python child helper;
- exact production-release guard;
- exact Alembic 0046 guard;
- read-only SQL/service inspection;
- strict sanitized protocol parsing;
- no direct ad-hoc SSH outside the probe wrapper;
- no Telegram imports that initiate provider activity;
- no network/provider SDK calls;
- no writes/flush/commit that can mutate DB state.

Add focused protocol/static/unit tests under `ops/production/tests/`.

## Required local validation

Run:
- focused probe tests;
- helper Python compile;
- bundled helper compile if applicable;
- Bash syntax if shell wrapper added/changed;
- Ruff on changed Python;
- `git diff --check`.

DB-backed local tests are optional only if unavailable due the known local DB hostname limitation; report that fact rather than broadening scope.

## Authorization

AUTHORIZED:
- local code changes needed only for this read-only probe;
- local tests;
- update `PROJECT_STATE.md`;
- commit and push to canonical `main`.

NOT AUTHORIZED:
- production SSH;
- live probe execution;
- Telegram/provider calls;
- Apply Scope;
- Sync;
- reconciliation;
- DB mutation;
- folder/account/login changes;
- production ref change/deploy/rollback;
- enabling MTProto AI;
- Bot API changes.

## Required report

Return:
- commit SHA;
- files changed;
- exact probe protocol/output fields;
- test/compile/Ruff/diff-check results;
- confirmation production SSH=0;
- Telegram/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_MTPROTO_M4BD1_ACCEPTANCE_PROBE_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
