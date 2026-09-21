# Current task — Telegram MTProto M4BE2: repeat one-shot read-only post-deploy acceptance

## Status

M4BE1R corrective probe fix is architect-reviewed and ACCEPTED.

Approved corrective commit:
`1e29b64687e517e60aa8971be53ce1adb553285f`

Current production runtime/ref:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

Expected Alembic:
`0046`

Previous M4BE1 run already confirmed:
- account count 1;
- configured folder count 1;
- active scope 28;
- manual-active 0;
- folder-only active 28;
- latest cursor present 28;
- history complete 28;
- backfill cursor present 0;
- history cutoff present 0;
- Telegram network calls 0;
- DB writes 0.

The prior run failed only in the read-only peer-object aggregate due a probe SQL grouping defect, now corrected in M4BE1R.

## Authorization

Authorize exactly ONE repeated human-shell execution of:

`ops/production/manual_mtproto_postdeploy_acceptance_probe.sh`

Purpose: collect the object-count and AI-quarantine aggregates that were not reached in M4BE1.

This remains a read-only production acceptance probe.

Do NOT:
- click or call Apply Scope;
- click or call Sync;
- change folder configuration;
- login/re-login;
- run any Telegram/provider probe;
- run direct ad-hoc SSH outside the committed wrapper;
- mutate production DB or files;
- deploy/rollback/move refs;
- enable MTProto AI;
- alter Bot API.

## Interpretation

Expected scope remains 28 peers.

For acceptance:
- `ACTIVE_SCOPE_COUNT=28`;
- `MANUAL_ACTIVE_COUNT=0`;
- `FOLDER_ONLY_ACTIVE_COUNT=28`;
- `BACKFILL_CURSOR_PRESENT_COUNT=0`;
- `HISTORY_CUTOFF_PRESENT_COUNT=0`;
- `MTPROTO_OBJECTS_WITH_EMBEDDING=0`;
- `MTPROTO_OBJECTS_WITH_CURRENT_EMBEDDING_PROVENANCE=0`;
- `MTPROTO_PENDING_RUNNING_EMBED_JOBS=0`.

`ACTIVE_PEERS_WITH_OBJECTS_GT_20` is diagnostic only. A nonzero value requires interpretation because normal incremental sync after bootstrap may legitimately push a folder-only peer above 20; it is not by itself proof of deep backfill.

## Required run

From a clean canonical checkout containing the accepted correction:

```bash
bash ops/production/manual_mtproto_postdeploy_acceptance_probe.sh
```

Run exactly once.

## Failure handling

If wrapper/probe returns blocked or failure:
- do not retry;
- do not bypass;
- do not use direct SSH;
- return the complete sanitized output and STOP.

## Required report

Return the complete sanitized output including the terminal marker.

No further action after the probe.

`CURRENT_TASK.md` is the source of active authorization.
