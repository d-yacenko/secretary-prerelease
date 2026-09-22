# Current task — Execute exactly one live self-authored Telegram E2E

## Human authorization

Explicit authorization received for exactly one live production self-authored Telegram E2E using:

`TG_SELF_E2E_0922A`

with real production ML/LLM providers while long-running Telegram AI remains false.

## Accepted harness

Live-ready harness:

`00a653a11f44f4122fb2689cbbffb06c133049e3`

Current canonical main contains that accepted harness plus architect state/task commits.

Production runtime/ref remains:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Alembic:

`0046`

## Exact authorized invocation

Execute exactly once from the canonical local checkout:

```bash
cd ~/work/secretary-prerelease
git switch main
git pull --ff-only
git fetch --prune origin
python3 ops/production/telegram_self_authored_e2e_remote.py
```

No alternate run, no direct SSH, no manual container command, no second invocation without architect review.

## Expected success report

A successful run must be non-empty and include at least:

- `SELF_AUTHORED=PASS`
- `SUMMARY_COHORT_SELF_AUTHORED=PASS`
- `EMBEDDING=PASS`
- `AUTO_LABEL_EXECUTED=PASS`
- `TEMPORAL=PASS`
- `CORRELATION=PASS`
- `SUMMARY=PASS`
- `CONTEXT_VISIBLE=PASS`
- `RETRIEVAL_VISIBLE=PASS`
- `IDEMPOTENT=PASS`
- `DANGLING_SELECTED_JOBS=0`
- `TELEGRAM_TRANSPORT_CALLS=0`
- `PROCESS_LOCAL_AI=true`
- `ENV_UNCHANGED=PASS`
- `LONG_RUNNING_API_AI=false`
- `LONG_RUNNING_WORKER_AI=false`
- `PROVIDERS=live`
- `LIVE_EXECUTION=1`

`AUTO_LABEL_ASSIGNMENTS=0` is allowed.

Temporal result may be one of the accepted canonical successful forms:
- `temporal_hint`
- `calendar_match`
- `hint_merged`
- `already_evidenced`

## Failure handling

On any:
- `SELF_E2E_REMOTE_BLOCKED=...`
- `SELF_E2E_BLOCKED=...`
- `SELF_E2E_FAILED=...`
- nonzero exit with incomplete report

STOP.

Do not retry.
Do not run direct SSH.
Do not inspect or bypass provider/privacy guards.
Do not deploy/restart/recreate services.
Do not change production env.
Return the complete sanitized stdout to Architect.

## Hard constraints

- long-running API/worker Telegram AI=false;
- no Telegram transport calls;
- no session decrypt;
- no catch-up/backlog;
- no synthetic object insertion;
- no deploy/ref movement;
- no migration;
- no production .env change.

This task authorizes exactly one invocation only.

`CURRENT_TASK.md` is the source of active authorization.
