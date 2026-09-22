# Current task — Telegram final closure: deploy accepted downstream code, then production synthetic ML rehearsal

## Status

Telegram downstream development is ARCHITECT ACCEPTED through:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Current production:

`f31f8f5b704159b7ec903da4c26a590d23f86e78`

Expected Alembic:

`0046`

Production currently remains:

`TELEGRAM_MTPROTO_AI_ENABLED=false`

Production->candidate is fast-forward and contains no migration/Alembic or infra changes.

## Why this final step exists

The local synthetic false->true suite proves the domain pipeline with fake providers.

The final acceptance should additionally prove the accepted Telegram-shaped object can traverse the actual production backend configuration and real ML/LLM adapters, while still preventing any real Telegram content from entering AI processing.

## Authorization state

NOT YET AUTHORIZED:
- production deploy of `8ad52f06...`;
- production synthetic object creation;
- real production LLM/embedding calls for the rehearsal.

Do not execute production actions until explicit human authorization.

Suggested explicit authorization:

`Разрешаю deploy 8ad52f06 при Telegram AI=false и один production synthetic ML rehearsal с реальными ML/LLM, без Telegram transport calls`

## Phase A — schema-neutral deploy after authorization

Fast-forward canonical `production` to exact:

`8ad52f0653f9f90e1932c49532dc4f993ea1a9cc`

Deploy only through canonical `ops/production/deploy.py`.

Rollback:

`f31f8f5b704159b7ec903da4c26a590d23f86e78`

Expected Alembic remains `0046`.

Hard requirement after deploy:
- production API environment: `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- production worker environment: `TELEGRAM_MTPROTO_AI_ENABLED=false`.

No global/process-service AI enablement.

## Phase B — production synthetic ML rehearsal design

Use a dedicated, reviewable one-shot backend helper rather than an ad-hoc shell Python blob.

The helper must be implemented/tested locally before any live execution if it does not already exist.

### Process isolation

The rehearsal process alone may run with:

`TELEGRAM_MTPROTO_AI_ENABLED=true`

The long-running production API and worker MUST remain false for the entire rehearsal.

Do not restart/recreate them with true.

### Data policy

Use only clearly synthetic content, with a unique marker such as:

`TG_REHEARSAL_<run-id>`

No real Telegram message body/title is passed to an ML/LLM provider.

No Telegram session/provider transport operation is allowed.

Synthetic records may use a dedicated synthetic MTProto account/selection if safe; otherwise use only the minimum existing identity metadata necessary for AI eligibility. Never decrypt or call the Telegram session.

All created records must be attributable to the rehearsal run through explicit synthetic metadata/marker.

### Rehearsal content

Create at minimum:
- two synthetic inbound canonical MTProto chat messages in the same synthetic conversation burst;
- one synthetic task/object with matching subject matter;
- any deterministic supporting label/config needed to observe normal auto-label behavior.

Example semantic content may express:
- meeting tomorrow at 11 about synthetic project budget;
- prepare a synthetic estimate before that meeting.

### Real production pipeline proof

Use production DB/config and the normal backend services.

Use REAL configured production adapters for:
- embedding;
- auto-label/classification;
- temporal extraction/judging;
- correlation/judging;
- conversation summarization.

No real Telegram provider call.

Prove, with synthetic objects only:
1. canonical Inbox eligibility;
2. conversation stack grouping;
3. real embedding is produced;
4. normal label edge/result is produced;
5. temporal hint/evidence is produced with correct participation semantics;
6. proposed task/object correlation edge is produced;
7. conversation-stack semantic summary is produced;
8. AI-only context/retrieval can expose the synthetic MTProto object;
9. repeated/idempotent processing does not create duplicate semantic artifacts beyond normal contract.

### Queue safety

The normal production worker remains AI=false and must not accidentally consume the rehearsal's Telegram AI work.

Therefore do NOT rely on leaving normal pending jobs for the production worker.

The rehearsal helper should exercise normal enqueue/signature logic in a transaction/process-safe way, but execute the relevant handler/service work inside the isolated AI=true process, or otherwise ensure the false worker cannot race and consume the rehearsal jobs.

Do not pause/reconfigure the production worker merely to make the rehearsal work.

### Output

Emit only a sanitized summary:
- run id;
- object count created;
- stack PASS;
- embedding PASS;
- label PASS;
- temporal PASS + participation class;
- correlation PASS;
- summary PASS;
- context/retrieval PASS;
- idempotency PASS;
- TELEGRAM_TRANSPORT_CALLS=0;
- long-running API/worker AI flag remains false.

Do not print message bodies, credentials, Telegram ids, session material, raw prompts/responses, embeddings, or secret env values.

## Cleanup

Automatic destructive cleanup is NOT required.

Prefer retaining the clearly marked synthetic rehearsal artifacts until human review. Any later cleanup must be separately authorized.

## Acceptance result

If deploy and rehearsal pass, Telegram development is considered CLOSED:

- transport/CRUD production-ready;
- ordinary Inbox production-ready;
- downstream AI/ML pipeline deployed but globally quarantined;
- production flag remains false;
- future activation requires only explicitly authorized:
  1. `TELEGRAM_MTPROTO_AI_ENABLED=true`;
  2. API/worker environment reload/recreate;
  3. existing bounded recurring catch-up.

No migration, relogin, folder reconfiguration, metadata rewrite, or product redesign should be required.

## Failure handling

On any deploy/rehearsal failure:
- no automatic retry;
- do not globally enable Telegram AI;
- do not call Telegram;
- return sanitized output and STOP.

`CURRENT_TASK.md` is the source of active authorization.
