# Current task — Execute the actual production synthetic Telegram ML rehearsal

## Status

Remote-program fix is ARCHITECT ACCEPTED at:

`700ec26a22485b52fb5cafab0f2de8b35d45e3e9`

Production remains:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Alembic:

`0046`

Long-running API/worker Telegram AI must remain false.

The prior invocation of `tgprod0922a` crashed in the streamed wrapper program before helper write and before `docker compose run`. It created no rehearsal data and made no ML/LLM/Telegram calls. It therefore did not consume the already-granted authorization for one actual synthetic rehearsal.

## Authorized execution

Run exactly once:

```bash
cd ~/work/secretary-prerelease
git switch main
git pull --ff-only
git fetch --prune origin
python3 ops/production/telegram_production_rehearsal_remote.py --run-id tgprod0922a
```

Do not add shell wrappers or ad-hoc SSH.

## Expected successful protocol

Expect non-empty sanitized stdout including:

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

## Failure handling

On any `REHEARSAL_REMOTE_BLOCKED`, `REHEARSAL_REFUSED`, or `REHEARSAL_FAILED`:
- do not retry;
- do not inspect via ad-hoc SSH;
- return complete sanitized stdout;
- STOP.

No deploy, migration, service restart/recreate, global AI enablement, Telegram transport call, or cleanup is authorized.

`CURRENT_TASK.md` is the source of active authorization.
