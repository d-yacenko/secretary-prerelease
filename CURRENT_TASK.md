# Current task — Execute exactly one new live self-authored Telegram E2E

## Human authorization

Explicit human authorization received for exactly one new live production self-authored Telegram E2E to verify the complete Telegram downstream pipeline.

Use the existing real production marker:

`TG_SELF_E2E_0922A`

Use real production ML/LLM providers.

Long-running Telegram AI for the production API and worker must remain false.

This authorization permits exactly one invocation of the canonical remote wrapper.

## Accepted acceptance path

Architect-accepted live-ready wrapper/privacy baseline:

`a4c5225550aa56b204043380a02280507f9a9976`

Accepted execution contract:

- acceptance runs only as a separate `docker compose exec -T -w /app ... api python3 -B -` process inside the already-running production API container;
- helper/bootstrap are passed through stdin and executed in memory;
- no acceptance-path run/create/up/build/pull/restart/recreate;
- no helper/bootstrap filesystem writes;
- helper import-time stdout/stderr are discarded;
- terminal harness protocol remains fail-closed.

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

No alternate command.
No direct SSH.
No manual Docker/Compose command.
No second invocation.

## Required success report

A successful run must exit 0 and include at least:

- `SELF_E2E_STARTUP=bootstrap`
- `SELF_E2E_STARTUP=compiled`
- `SELF_E2E_STARTUP=imported`
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

Accepted temporal result forms remain:

- `temporal_hint`
- `calendar_match`
- `hint_merged`
- `already_evidenced`

## Failure handling

On any of:

- any `SELF_E2E_REMOTE_BLOCKED=...`;
- any `SELF_E2E_BLOCKED=...`;
- any `SELF_E2E_FAILED=...`;
- nonzero exit;
- zero exit without the complete required PASS report;

STOP.

Do not retry.
Do not repair production.
Do not run direct SSH.
Do not run manual Docker/Compose.
Do not bypass provider/privacy guards.
Do not deploy/restart/recreate.
Do not change production env.
Do not move production refs.

Return to Architect:

- complete sanitized stdout;
- exact exit status.

## Hard constraints

- long-running API Telegram AI=false;
- long-running worker Telegram AI=false;
- no Telegram transport calls;
- no session decrypt;
- no catch-up/backlog;
- no synthetic object insertion;
- no deploy/ref movement;
- no migration;
- no production .env change.

This task authorizes exactly one invocation only.

`CURRENT_TASK.md` is the source of active authorization.
