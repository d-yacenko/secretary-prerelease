# Current task — Await explicit replacement live Telegram E2E authorization

## Architect acceptance

Commit:

`8ae75dc9e2b6b05e8caa4b966caafc7bbcb63574`

is ACCEPTED.

The Telegram summary self-authorship correction is verified and the full self-authored Telegram acceptance path is architect-reviewed as LIVE-READY / NOT EXECUTED.

Verified local evidence on exact commit `8ae75dc9e2b6b05e8caa4b966caafc7bbcb63574`:

- focused pytest `tests/test_telegram_self_authored_e2e.py`: 29 passed;
- `py_compile`: passed;
- Ruff check: passed;
- Ruff format --check: both files already formatted;
- `git diff --check`: clean;
- working tree on the verified commit was clean.

Accepted privacy semantics:

- selected E2E Telegram messages must be canonical outbound MTProto objects for the selected account, authored by the connected Telegram user, and contain `TG_SELF_E2E_0922A`;
- covered summary neighbors may omit the marker only when they are canonical outbound MTProto objects for the same account and authored by the connected Telegram user;
- inbound, foreign sender, wrong account, unknown direction, missing identity, and legacy/noncanonical Telegram objects remain fail-closed;
- the accepted stdin-fed `docker compose exec -T -w /app ... api python3 -B -` remote path is unchanged;
- no run/create/up/build/pull/helper-filesystem-write path is accepted;
- long-running production API/worker Telegram AI must remain false.

Production runtime/ref remains:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Alembic remains:

`0046`

## Authorization state

NO live E2E is currently authorized.

All prior live authorizations were consumed by their respective attempts. Do not infer a new authorization from this acceptance or from the successful local verification.

Do not execute:

- production SSH;
- production Docker/Compose;
- the remote E2E wrapper;
- provider calls;
- Telegram transport/session access;
- production DB writes;
- deploy/restart/recreate;
- production env changes;
- production ref movement.

STOP and wait for explicit human authorization for exactly one new replacement live self-authored Telegram E2E.

If such authorization is received, Architect must replace this file with the exact one-shot invocation and complete success/failure contract before Executor may run anything.
