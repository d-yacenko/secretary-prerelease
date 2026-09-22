# Current task — Execute one production synthetic Telegram ML rehearsal

## Status

Production downstream code is deployed and healthy at:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Production Alembic:
`0046`

Long-running production API/worker Telegram AI must remain:
`false`

Reviewed live rehearsal wrapper/helper:
`23d2521bcd5a2e774be657cc47dd5625d840822f`

Human authorization for exactly one production synthetic ML rehearsal is already granted.

## Exact authorized run

Run id:

`tgprod0922a`

Execute exactly once:

```bash
cd ~/work/secretary-prerelease
git switch main
git pull --ff-only
git fetch --prune origin
python3 ops/production/telegram_production_rehearsal_remote.py --run-id tgprod0922a
```

The full fetch immediately before the wrapper is intentional: it refreshes local remote-tracking refs so the wrapper cannot repeat the historical stale-`origin/production` false blocker.

## Expected success

Sanitized success must include:

- `INBOX_ELIGIBLE=PASS`
- `STACK_GROUPED=PASS`
- `EMBEDDING=PASS`
- `AUTO_LABEL=PASS`
- `TEMPORAL=PASS`
- `TEMPORAL_PARTICIPATION=expected`
- `CORRELATION=PASS`
- `SUMMARY=PASS`
- `CONTEXT_VISIBLE=PASS`
- `IDEMPOTENT=PASS`
- `ENV_UNCHANGED=PASS`
- `PROCESS_LOCAL_AI=true`
- `LONG_RUNNING_API_AI=false`
- `LONG_RUNNING_WORKER_AI=false`
- `TELEGRAM_TRANSPORT_CALLS=0`
- `DANGLING_JOBS=0`
- `PROVIDERS=live`
- `LIVE_REHEARSAL_EXECUTED=1`

Synthetic artifacts are intentionally retained for audit.

## Hard constraints

- no real Telegram message/content;
- no Telegram transport call;
- no session decrypt;
- no production .env mutation;
- no global/service-level Telegram AI enablement;
- no API/worker restart/recreate;
- no deploy/ref movement;
- no migration;
- no cleanup.

## Failure handling

On ANY block/refusal/failure:
- do not retry;
- do not bypass;
- do not run ad-hoc SSH;
- return complete sanitized stdout and STOP.

Only the single run id above is authorized.

## Required human report

Return complete sanitized stdout exactly as produced.

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
