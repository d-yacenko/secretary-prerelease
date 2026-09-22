# Current task — Execute one actual production synthetic Telegram ML rehearsal

## Accepted implementation

One-shot startup fix accepted at:

`659d49d16c36370f4fab1884b4805a6cedb1a8e4`

Production runtime/ref remains:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Alembic:

`0046`

Long-running production API/worker Telegram AI must remain false.

The previous wrapper failures occurred before helper business execution and created no rehearsal synthetic state.

## Authorized run

Exactly one actual live rehearsal remains authorized with run id:

`tgprod0922a`

Execute exactly once:

```bash
cd ~/work/secretary-prerelease
git switch main
git pull --ff-only
git fetch --prune origin
python3 ops/production/telegram_production_rehearsal_remote.py --run-id tgprod0922a
```

No deploy, direct SSH, retry wrapper, or alternate run id.

## Expected startup

The live child must first emit:

`REHEARSAL_STARTUP=PASS`

If deployment OpenAI fallback is absent, expected terminal output is:

`REHEARSAL_REMOTE_BLOCKED=provider_config`

before any synthetic fixture creation.

## Expected successful report

A successful live rehearsal must include:

- `REHEARSAL_STARTUP=PASS`
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

## Failure handling

On any:
- `REHEARSAL_REMOTE_BLOCKED=...`
- `REHEARSAL_REFUSED=...`
- `REHEARSAL_FAILED=...`

do not retry, do not use ad-hoc SSH, do not alter production, and return the complete sanitized stdout.

## Hard constraints

- no real Telegram content;
- no Telegram transport/session decrypt;
- no production .env mutation;
- no global/service AI=true;
- no API/worker restart/recreate;
- no deploy/ref movement;
- no migration;
- no cleanup.

`CURRENT_TASK.md` is the source of active authorization.
