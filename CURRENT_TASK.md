# Current task — Telegram MTProto M4BE1: one-shot read-only post-deploy acceptance

## Status

M4BD1 acceptance probe is architect-reviewed and accepted for one live run.

Approved probe commit:
`5ebc22e9ab14582177b3ee1ace49eeea86894048`

Current production runtime/ref:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

Expected Alembic:
`0046`

## Authorization

Authorize exactly ONE human-shell execution of:

`ops/production/manual_mtproto_postdeploy_acceptance_probe.sh`

This is a read-only production acceptance probe.

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

Expected scope breadth from the prior complete M4BB3 preview is 28 peers.

The probe may run after natural recurring worker cycles. Therefore:
- `ACTIVE_SCOPE_COUNT=28` is the expected reconciled scope;
- fewer than 28 peers with history cursors/completion may simply mean the recurring worker has not visited all peers yet;
- the legacy manual-selected peer may legitimately have more than 20 stored historical objects;
- `ACTIVE_PEERS_WITH_OBJECTS_GT_20` excludes that manual-selected peer and applies to folder-only peers;
- a nonzero folder-only >20 count is a diagnostic signal, not automatically proof of deep backfill, because incremental post-bootstrap messages may legitimately raise a peer above 20;
- zero MTProto embeddings/current embedding provenance/pending-running embed jobs is the expected Q1-quarantine result; any nonzero AI-related aggregate requires review before acceptance.

## Required run

From a clean canonical checkout containing the approved probe:

```bash
bash ops/production/manual_mtproto_postdeploy_acceptance_probe.sh
```

Run exactly once.

## Failure handling

If the wrapper blocks before remote execution or the probe returns failure:
- do not retry;
- do not bypass;
- do not use direct SSH;
- return the sanitized output and STOP.

## Required report

Return the complete sanitized probe output, including all aggregate fields and terminal marker.

No further actions after the probe.

`CURRENT_TASK.md` is the source of active authorization.
