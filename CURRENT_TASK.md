# Current task — Await explicit replacement live Telegram E2E authorization

## Architect acceptance

Commit:

`a4c5225550aa56b204043380a02280507f9a9976`

is ACCEPTED.

The self-authored Telegram production acceptance path is architect-reviewed as LIVE-READY / NOT EXECUTED.

Accepted contract:

- acceptance runs only as a separate `docker compose exec -T -w /app ... api python3 -B -` process inside the already-running production API container;
- there is no acceptance-path `run`, `create`, `up`, `build`, `pull`, restart, recreate, helper mount, or helper/bootstrap filesystem write;
- helper/bootstrap source is passed through stdin and compiled/executed in memory;
- helper top-level/import-time stdout and stderr are discarded on success and failure;
- only bootstrap-owned startup/fixed failure markers may appear before helper `main(["--live"])`;
- helper `main(["--live"])` is called exactly once;
- legitimate `SELF_E2E_BLOCKED=...`, `SELF_E2E_FAILED=...`, and success output containing exact `SELF_AUTHORED=PASS` remain terminal outcomes;
- nonterminal post-import results fail closed as `SELF_E2E_REMOTE_BLOCKED=harness_protocol`;
- checkout/ref/origin/host-key and long-running API/worker AI=false guards remain;
- raw stderr, traceback, exception messages, partial nonterminal helper output, credentials, provider responses, and Telegram content are not forwarded.

Production runtime remains:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Alembic remains:

`0046`

Long-running Telegram AI remains false.

## Authorization state

NO live E2E is currently authorized.

Both prior live authorizations were consumed by pre-harness startup failures. Do not infer a new authorization from this acceptance.

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
