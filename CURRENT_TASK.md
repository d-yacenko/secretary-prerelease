# Current task — Await human authorization for one live self-authored Telegram E2E

## Architect acceptance

Live-ready harness accepted at:

`00a653a11f44f4122fb2689cbbffb06c133049e3`

Production remains:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Alembic:

`0046`

Long-running production API/worker Telegram AI must remain false.

## Accepted safety contract

The live E2E:
- reads only already-synced canonical marker objects;
- uses exact marker `TG_SELF_E2E_0922A`;
- proves active scope, outbound direction, and `sender_peer_id == TelegramMtprotoAccount.telegram_user_id`;
- blocks any unverifiable Telegram message before provider calls;
- blocks every correlation candidate with `provider=telegram` unless its id belongs to the approved self-authored Telegram set;
- does not use Telegram transport or decrypt the MTProto session;
- does not run catch-up/backlog;
- keeps global/service-level Telegram AI=false;
- sets process-local AI=true only after privacy checks;
- uses real production ML/LLM providers;
- proves embedding, cohort-scoped auto-label execution, temporal result, correlation to the exact marker task, conversation summary, context/retrieval visibility, idempotency, and zero selected dangling jobs;
- uses the canonical pinned-host remote wrapper;
- does not deploy/restart/recreate/migrate or modify production .env.

## Authorization status

LIVE PRODUCTION E2E IS NOT YET AUTHORIZED.

Do not run:
- `ops/production/telegram_self_authored_e2e_remote.py`;
- direct SSH;
- provider calls for this E2E;
- production DB mutation caused by the acceptance handlers.

Wait for explicit human authorization for exactly one live production E2E invocation.

After explicit authorization, Architect will replace this task with the exact one-run execution instruction.

`CURRENT_TASK.md` is the source of active authorization.
