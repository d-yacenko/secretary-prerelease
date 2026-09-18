# Current task — Telegram MTProto Q1: AI quarantine + future activation

## Status

- Telegram A1–A4.4: ACCEPTED in code / NOT production deployed.
- Production Migration Rollout M1 harness: ACCEPTED at exact SHA `917eebed4b0ffb6bf55f573a24d99d00dc1f8fbb`.
- M2 production readiness retry: READY.
- Production runtime/ref remains exact `5cce4b57b14e0052a038acae1354a2821a2bb77b`.
- Production Alembic remains exact `0041`.
- Telegram platform credentials are provisioned in production `/opt/secretary/.env`; values remain secret.
- The previous project-wide HOLD is lifted for the narrow Q1 implementation below.
- M3 production deployment remains NOT authorized.
- Telegram Bot API retirement remains NOT authorized.

## Product decision

Secretary will finish Telegram MTProto as a full non-AI communication transport even while Telegram's AI/API clarification is pending.

Until an affirmative clarification is accepted, MTProto Telegram objects may be synchronized, stored and shown to the user as ordinary Inbox/message data, but must not enter any ML/LLM processing path.

A single installation-level capability flag will later enable the AI path if permitted:

`TELEGRAM_MTPROTO_AI_ENABLED=false`

Default is fail-closed `false`.

The flag controls only AI/ML eligibility. It must NOT disable MTProto authentication, folder/scope reconciliation, history sync, ordinary storage, ordinary Inbox visibility, or future communication CRUD.

## Canonical MTProto object

The quarantine applies only when all are true:

- `provider == "telegram"`
- `kind == "chat_message"`
- `metadata.transport == "mtproto"`

Legacy/Bot API Telegram objects are not affected by Q1.

Existing A4.3 `scope_active` semantics remain unchanged and independent from AI eligibility.

## Q1 required implementation

### 1. Configuration

Add:

`telegram_mtproto_ai_enabled: bool = False`

to backend settings.

Expose `TELEGRAM_MTPROTO_AI_ENABLED` to both api and worker in `infra/compose.yaml` with default `false`.

No DB migration and no new table/column.

### 2. Separate AI eligibility policy

Do NOT overload or change the meaning of `telegram_mtproto_active_object_predicate`.

Create a separate, centrally reusable fail-closed Telegram MTProto AI eligibility policy/predicate.

It must have SQLAlchemy and raw-SQL equivalents where required by existing retrieval candidate paths, analogous to the current A4.3 visibility helpers.

When the flag is false:
- canonical MTProto objects are AI-ineligible;
- all other objects keep current behavior.

When true:
- canonical MTProto objects keep the existing A4.3 active-scope behavior.

Malformed metadata must fail closed for AI use.

### 3. No embedding or AI-derived enqueue while disabled

For canonical MTProto objects with the flag false:

- creation must not enqueue `embed_object`;
- semantic updates must not enqueue `embed_object`;
- no other Telegram-specific path may enqueue AI/ML-derived work for those objects.

Ordinary materialization must still succeed and report zero AI jobs enqueued.

Bot API Telegram and other providers retain existing enqueue behavior.

### 4. AI read-path quarantine

Inventory the current A4.3 surfaces and all assistant/AI callers before changing them.

When the flag is false, canonical MTProto objects must not be consumable by:

- embedding/vector candidate paths;
- semantic retrieval;
- LLM/assistant context construction;
- direct "Ask Secretary" object context;
- assistant object-query/tool paths;
- AI context/graph expansion;
- conversation-member discovery when used to construct assistant context;
- proactive AI processing, summarization, classification, correlation or other ML-derived processing if any such path can currently consume `chat_message` objects.

The implementation must be centralized enough that adding another assistant retrieval path cannot trivially bypass the quarantine.

### 5. Preserve non-AI user visibility

This is essential.

With the flag false and `scope_active=true`, MTProto messages MUST remain visible in ordinary non-AI product surfaces needed for a messenger, including the Inbox / `RecentSourceService`.

Do not hide an active MTProto object merely because AI is disabled.

Do not delete, tombstone, redact, mutate, or purge its body.

Existing A4.3 out-of-scope behavior still applies: `scope_active=false` hides it according to the accepted A4.3 contract.

If an existing Search surface mixes lexical and semantic behavior and cannot safely expose MTProto without invoking ML, fail closed for that Search path in Q1 and document the limitation. Do not add a new search architecture in Q1.

### 6. Future one-flag activation / bounded catch-up

Q1 must prepare the future `false -> true` transition so no redesign is needed.

When the flag becomes true, existing active MTProto objects accumulated while disabled must be able to receive their missing/current embeddings through an idempotent, bounded catch-up using the existing Postgres job queue and existing `embed_object` job type.

Requirements:
- no new daemon;
- no Redis/Celery/Rabbit/Kafka;
- no unbounded full-table enqueue in one transaction/run;
- reuse existing Telegram recurring/source-sync lane or another existing bounded recurring mechanism;
- only active, correctly owned canonical MTProto objects are eligible;
- existing current embeddings are not duplicated;
- pending/running equivalent embedding work is not duplicated;
- repeated runs converge safely.

The catch-up must do nothing while the flag is false.

### 7. Tests

Add focused tests proving at minimum:

- settings default false;
- compose exposes the flag identically to api and worker, default false;
- MTProto create/update stores data but enqueues zero embedding jobs when false;
- Bot API Telegram still enqueues as before;
- another provider is unaffected;
- active MTProto object remains in Inbox when false;
- inactive MTProto object remains hidden per A4.3;
- retrieval/assistant/context AI paths exclude active MTProto objects when false;
- direct Ask Secretary / exact-target context cannot bypass the gate;
- true restores the prior A4.3 AI-visible behavior;
- bounded catch-up is no-op when false;
- bounded catch-up enqueues only missing/stale active MTProto embeddings when true;
- catch-up is idempotent and bounded;
- malformed metadata fails closed;
- no schema migration is introduced.

Run focused Telegram/A4.3/Q1 tests plus relevant retrieval/context/assistant/embedding tests and Ruff on changed Python files.

## Explicitly out of scope for Q1

Do NOT implement yet:

- MTProto send/reply/edit/delete/read mutations;
- realtime Telegram update subscription;
- client Telegram composer/reply UI;
- mobile notifications;
- production deployment;
- production ref movement;
- production DB/schema mutation;
- production `.env` change;
- Bot API removal;
- D-Bus/Android fallback;
- migration `0047`.

## Deliverable

Return:

- exact starting SHA;
- exact implementation commit SHA;
- changed files;
- concise description of the central AI gate and catch-up mechanism;
- focused test commands/results;
- Ruff result;
- Alembic head proof remains `0046`;
- confirmation no production mutation occurred.

Final marker:

`TELEGRAM_MTPROTO_Q1_AI_QUARANTINE_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
