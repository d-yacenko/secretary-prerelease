# Current task — Telegram MTProto C2A: bounded near-realtime reconciliation

## Status

Telegram MTProto C1B/C1BR/C1BR2 edit/delete/mark-read is **ACCEPTED and integrated to main**.

Accepted chain:
- C1B `4d61ebeb2d96e5bfb6393ef3e39d214cd814fc51`
- C1BR `a7c36d8d7053ad62371207773a7aa142a9fe3407`
- C1BR2 `0174b82375837b428f9e0b09c811394dc0f1d884`
- integration merge `37d2106fedc3d6cd3a9b5fd15dc70ded48d00caf`

Production remains untouched:
- production runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`
- production Alembic `0041`
- M3 NOT authorized
- Bot API retirement NOT authorized

Q1 AI quarantine remains mandatory:
`TELEGRAM_MTPROTO_AI_ENABLED=false` by default.

## C2A goal

Make Telegram MTProto behave like a practical continuously updated messenger without introducing a new daemon, queue, service, or long-lived Telethon listener.

Use the existing:
- `SourceSyncScheduler`
- Postgres-backed recurring queue
- `JOB_TYPE_SYNC_TELEGRAM_MTPROTO`
- `TelegramMtprotoRecurringSyncService`
- A3 history/materializer
- C1B exact-message provider fetch capability

C2A covers:
1. faster bounded polling for new messages;
2. bounded reconciliation of recent known messages for remote edits/deletes;
3. deterministic convergence into the existing canonical Object format;
4. fairness and failure isolation.

C2A does NOT add user-facing notification UI yet. That is C2B.

## 1. Telegram recurring cadence

Change the installation default:

`source_sync_telegram_mtproto_interval_seconds: 300 -> 60`

Requirements:
- Telegram only;
- do not change Gmail/Yandex/Mattermost/Teams defaults;
- keep existing recurring queue scheduling architecture;
- no busy loop;
- no long-lived Telegram connection;
- no new worker/daemon;
- existing retry/failure cooldown semantics stay intact.

Expose/retain the existing env override through normal Settings env parsing; do not add a second interval setting.

Tests:
- default Telegram recurring interval is 60;
- explicit env override still works;
- other providers unchanged;
- recurring success re-arms at the configured Telegram interval.

## 2. New-message ingestion remains A3/A4 history based

Do not replace the accepted A3 history sync.

Each recurring Telegram account run still:
1. reconciles folder/scope;
2. performs Q1 embedding catch-up only if AI=true;
3. fairly syncs bounded active peers;
4. advances peer cursor.

New messages continue to materialize through the same canonical history normalization/materializer.

Do not create a second message-ingestion representation.

## 3. Recent-message reconciliation for remote edits/deletes

The existing incremental history pass is insufficient for:
- an older message edited after its message_id is already behind the history cursor;
- a provider-deleted message that disappears from normal history results.

Add a bounded reconciliation pass over recently known canonical MTProto Objects.

### Candidate selection

For the current connected account only:
- current user;
- provider=telegram;
- kind=chat_message;
- metadata.transport=mtproto;
- metadata.account_id == current account;
- active A4.3 scope only;
- non-tombstoned local objects;
- positive message_id;
- exact durable selection exists and scope_active=true.

Prefer recently occurred/updated objects.

Bound the work:
- at most 20 exact-message provider checks per recurring account run;
- at most 5 per peer per run;
- preserve fairness across peers with a durable cursor in the existing recurring job payload;
- no unbounded table scan;
- no new DB state/table/migration.

A different bounded number is acceptable only if clearly justified in code/tests; do not exceed 50 provider message lookups per account run.

### Provider lookup

Reuse/extend the C1B exact-message fetch primitive.

The fetch result must be rich enough to reconcile canonical state, including where available:
- exact peer id;
- exact message id;
- text/body;
- occurred_at;
- edit_date / edited_at;
- reply_to_message_id;
- sender_peer_id;
- outgoing flag;
- topic_id;
- service-message marker.

Never trust a result whose returned peer/message id does not match the frozen/local object route.

Malformed/mismatched result:
- peer-local failure;
- do not mutate local object;
- continue other candidates.

### Remote edit

If exact provider message exists:
- normalize through the same A3 canonical normalization function/path;
- upsert through `TelegramObjectMaterializer`;
- preserve same Object id/external_id;
- update body/title/edited_at/direction/reply metadata consistently;
- AI=false => zero AI jobs;
- AI=true => normal signature-aware semantic update enqueue.

Do not manually maintain a divergent metadata format.

### Remote delete

If an exact provider lookup returns a trustworthy "not found/deleted" result for an object that previously existed:
- tombstone the existing Object;
- retain DB row;
- do not purge;
- do not create a deletion shadow object;
- normal active Inbox/retrieval visibility must hide it via existing tombstone semantics.

Be conservative:
- timeout/server/network/auth/reference failure is NOT evidence of deletion;
- only provider-confirmed absence for the exact peer/message may tombstone;
- failure to verify leaves the local object unchanged.

### Locally deleted messages

Do not waste reconciliation budget repeatedly checking already tombstoned local objects.
Passive A3 sync must still not resurrect them.

## 4. Fairness / payload cursor

Store reconciliation progress only in the existing recurring job payload.

Requirements:
- cursor identifies the last actually inspected reconciliation candidate;
- advance across unchanged/edited/deleted candidates;
- do not advance past uninspected candidates;
- safe wrap at end;
- repeated runs eventually revisit all eligible recent candidates;
- scope changes must not strand the cursor;
- payload remains non-secret.

Do not add another recurring job per peer/message.

## 5. Failure model

Provider-wide/auth/config failure:
- preserve existing source-sync retry/failure behavior;
- do not convert a provider outage into mass local deletions.

Peer/message-local mismatch/not-found:
- mismatch => local failure/no mutation;
- confirmed absence => tombstone exact object;
- continue other peers/candidates where safe.

FloodWait / retry-after:
- honor existing Telegram recurring retry semantics;
- do not hammer provider;
- do not create parallel retries.

## 6. Normalization debt cleanup

C1A/C1B immediate MTProto send/edit currently build presentation titles with a 240-char slice, while A3 canonical history normalization uses the canonical 200-char bounded title with ellipsis.

Unify this now so immediate mutation materialization and later history reconciliation produce the same title/signature.

Preferred:
- extract/reuse one canonical MTProto presentation-title helper;
- C1A immediate send, C1B edit convergence, and A3 normalization use the same helper/limit;
- no duplicate semantic re-embed merely because history later canonicalizes a long title.

This is a compatibility cleanup, not a schema change.

## 7. AI quarantine

C2A must preserve Q1 exactly.

With `TELEGRAM_MTPROTO_AI_ENABLED=false`:
- new messages materialize;
- remote edits materialize;
- remote deletes tombstone;
- Inbox/non-AI reads update;
- zero embedding/summary/classification/correlation/LLM work.

With flag=true:
- normal existing AI semantic update behavior applies.

## 8. Tests

Add focused tests proving at minimum:

### Cadence
- Telegram default recurring interval=60;
- env override respected;
- other source defaults unaffected.

### New message
- recurring sync still imports newly arrived active-scope messages through A3.

### Remote edit
- object with old message_id behind latest history cursor is changed provider-side;
- reconciliation detects it;
- same object/external_id updated;
- canonical title/body/edited_at/direction converge;
- AI=false zero jobs;
- AI=true current-signature embedding work exactly as existing pipeline allows.

### Remote delete
- confirmed exact-message absence tombstones same Object;
- row retained;
- active reads hide it;
- transient fetch error does NOT tombstone;
- peer mismatch does NOT tombstone;
- tombstoned objects are not repeatedly reconciled/resurrected.

### Bounds/fairness
- <=20 provider lookups/account run;
- <=5/peer run;
- cursor equals last actually inspected candidate;
- repeated runs cover >one-window candidates;
- scope deactivation excludes candidates immediately;
- one peer-local failure does not block others.

### Regression
- A3/A4 recurring sync still works;
- Q1 AI quarantine green;
- C1A send/reply green;
- C1B edit/delete/mark-read green;
- canonical title is identical between immediate send/edit and later A3 normalization for long first lines;
- Alembic head remains `0046`.

Run Ruff on changed Python files and `git diff --check`.

## Explicitly out of scope C2A

Do NOT implement:
- long-lived Telethon event listener;
- new daemon/microservice;
- Redis/Celery/Rabbit/Kafka;
- websocket push to clients;
- OS/mobile notifications;
- client UI;
- production deploy/ref move;
- production DB/env mutation;
- migration `0047`;
- Bot API retirement;
- D-Bus/Android fallback.

## Branch / deliverable

Start from latest `origin/main`.

Create/use:
`review/telegram-mtproto-c2a-reconciliation`

Return:
- `STARTING_SHA`
- `C2A_SHA`
- changed files
- polling/cadence design
- reconciliation candidate/cursor design
- confirmed-delete rule
- canonical title normalization design
- focused/regression test results
- Ruff
- git diff --check
- Alembic head `0046`
- production untouched

Final marker:
`TELEGRAM_MTPROTO_C2A_RECONCILIATION_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
