# Current task — HOLD after bidirectional feed parity deployment

## Production status

Production runtime/ref:

`d22c6cf78945c8f92934a46431b2bcc1887fd8c8`

Deployment status:

PASS.

Deployment evidence:
- `RELEASE_HEAD=d22c6cf78945c8f92934a46431b2bcc1887fd8c8`
- `HEALTH=PASS`
- `ALEMBIC=0046`
- `DB_CONTAINER_UNCHANGED=true`
- `DB_VOLUME_UNCHANGED=true`
- `ENV_FILE_UNCHANGED=true`
- `API_RECREATED=true`
- `WORKER_RECREATED=true`
- `DEPLOYMENT=PASS`
- exit status 0;
- stderr empty;
- rollback `681c0e04df5881124ab8d72a4c05e5a2c7977296` not used.

## Deployed behavior

The deployed parity release:
- removes outbound suppression from ordinary Inbox/feed presentation for Telegram and Teams;
- keeps both inbound and outbound conversation members visible in detail/history;
- preserves Mattermost/Gmail/Yandex feed behavior;
- preserves rejected/deleted/noise/attachment filtering;
- does not turn visible outbound messages into attention/unread;
- does not change Telegram AI eligibility.

Production `TELEGRAM_MTPROTO_AI_ENABLED` remains false.

The previously verified self-authored false-mode exception remains active:
- proven self-authored canonical outbound active-scope Telegram may pass the normal AI pipeline;
- inbound/foreign Telegram remains AI-ineligible while the flag is false.

The codebase contains regression coverage proving that a future test/runtime switch to true uses the existing active-scope policy for both directions and is not constrained by the false-mode self-authored branch. This does not itself authorize a production flag change.

## Authorization state

No further production work is currently authorized.

Do not:
- set `TELEGRAM_MTPROTO_AI_ENABLED=true`;
- move refs;
- deploy/restart/recreate;
- change env;
- run direct SSH/manual Docker/Compose;
- manually trigger Telegram sync;
- manually enqueue AI jobs;
- process historical Telegram backlog;
- run provider diagnostics;
- run the old E2E harness;
- perform production DB writes.

STOP and await a new explicit human authorization/task.

Any future production activation of full Telegram AI (`false -> true`) is a separate rollout decision and requires its own explicit authorization and preflight/rollback plan.
