# Current task — Await human normal Telegram message for live pipeline verification

## Deployment status

Accepted release:

`681c0e04df5881124ab8d72a4c05e5a2c7977296`

is DEPLOYED successfully in production.

Canonical `production` ref is the same exact SHA.

Deployment evidence:

- `RELEASE_HEAD=681c0e04df5881124ab8d72a4c05e5a2c7977296`
- `HEALTH=PASS`
- `ALEMBIC=0046`
- `DB_CONTAINER_UNCHANGED=true`
- `DB_VOLUME_UNCHANGED=true`
- `ENV_FILE_UNCHANGED=true`
- `API_RECREATED=true`
- `WORKER_RECREATED=true`
- `DEPLOYMENT=PASS`
- exit status 0;
- rollback was not used.

## Intended live acceptance

The live acceptance is the ordinary production backend pipeline, not an E2E harness.

The human must send a brand-new ordinary Telegram message from the connected Telegram account in a chat that is already `scope_active=true`.

No special marker is required by production policy.

A unique harmless message body may be used only to make later read-only evidence correlation easier; it is not an eligibility condition.

Expected normal path:

1. normal MTProto recurring sync/history materializes the real Telegram object;
2. the object is canonical MTProto, outbound, self-authored, owned-account, active-scope;
3. `TelegramObjectMaterializer` naturally enqueues the ordinary embedding entrypoint;
4. the normal worker processes embedding and downstream correlation/auto-label/temporal/summary jobs according to existing configuration and budgets;
5. the object becomes visible to AI-only context/retrieval surfaces;
6. inbound/foreign Telegram remains excluded while global `TELEGRAM_MTPROTO_AI_ENABLED=false`;
7. global-false historical catch-up remains disabled.

## Current authorization state

No Executor production inspection is currently authorized.

Do not:
- run the old E2E harness;
- manually trigger Telegram sync;
- manually enqueue any AI job;
- enable global Telegram AI;
- run direct SSH;
- run manual Docker/Compose;
- perform provider calls/diagnostics;
- mutate production DB/env/ref/services;
- send a Telegram message on behalf of the human.

STOP and wait until the human reports that a new ordinary Telegram message has been sent.

After that, Architect must issue a separate narrowly scoped read-only production verification task to inspect normal DB/job/audit/result evidence for that new message without triggering pipeline work.
