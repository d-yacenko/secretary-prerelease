# Current task — Await explicit replacement live Telegram E2E authorization

## Architect acceptance

Post-import protocol correction:

`4fc6ff3b12f5e393be2ce3a46ab9b78b4280d86c`

is ACCEPTED.

The self-authored Telegram E2E acceptance harness and remote one-shot path are now architect-reviewed as live-ready again.

Accepted behavior:

- `SELF_E2E_STARTUP=...` lines are progress evidence only, never terminal harness outcomes;
- compile and import failures remain fixed sanitized blockers;
- after import, an exception or exit without a terminal harness outcome fails closed as `SELF_E2E_REMOTE_BLOCKED=harness_protocol`;
- legitimate `SELF_E2E_BLOCKED=...`, `SELF_E2E_FAILED=...`, and success output containing the exact `SELF_AUTHORED=PASS` line are propagated with the child exit code;
- raw stderr, traceback, exception text, partial nonterminal helper output, credentials, and provider responses are not forwarded;
- checkout/ref/origin/host-key/long-running-AI guards remain in place;
- production runtime remains `8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`;
- Alembic remains `0046`;
- long-running Telegram AI remains false.

## Authorization state

NO replacement live E2E is currently authorized.

The previous one-shot authorization was consumed by the earlier `oneshot_failed` attempt.

Do not execute:

- production SSH;
- production Docker;
- the remote E2E wrapper;
- provider calls;
- Telegram transport/session access;
- production DB writes;
- deploy/restart/recreate;
- production env changes;
- production ref movement.

STOP and wait for explicit human authorization for exactly one replacement live self-authored Telegram E2E.

If such authorization is received, Architect must first replace this file with the exact one-shot invocation and success/failure contract. Do not infer authorization from this acceptance entry.
