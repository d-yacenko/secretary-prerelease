# Current task — Telegram MTProto C1B: edit / delete / mark-read mutations

## Status

Telegram MTProto C1A + C1AR send/reply is **ACCEPTED and integrated to main**.

Accepted implementation:
- C1A `a48d6eba209dda946d203500775ee9ecaa00d812`
- C1AR `49a219d6a91349d0037c7ae7362974b496490bc2`
- integration merge `311682ad7b245398835b585d67deec4f6074e020`

Previously accepted Q1 AI quarantine remains mandatory:
`TELEGRAM_MTPROTO_AI_ENABLED=false` by default.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`
- production Alembic `0041`
- M3 NOT authorized
- Bot API retirement NOT authorized

## C1B goal

Complete the backend MTProto communication mutation set needed for a usable messenger:

1. edit an eligible own sent MTProto message;
2. delete/revoke an eligible MTProto message where Telegram permits it;
3. mark a peer/dialog read up to an exact message id.

Do not add UI in C1B.

Do not create direct Telegram mutation endpoints that bypass the existing tool/policy/execution architecture.

## Canonical mutation path

Assistant-triggered external mutations must continue through:

User
-> Assistant / tool request
-> Policy Gateway
-> frozen Pending Action Plan
-> explicit approval
-> Execution Gateway
-> DomainToolService
-> MTProto mutation service/transport

Reuse existing mutation/tool conventions and `ExternalActionAttempt` or equivalent existing external-write idempotency mechanism.

Do not build a second Telegram-specific approval framework.

## Shared routing / recipient integrity

Reuse the accepted C1AR route integrity contract.

Every MTProto mutation must validate/freeze:
- current Secretary user owns the object/account;
- canonical MTProto object:
  - provider=telegram
  - kind=chat_message
  - metadata.transport=mtproto
- valid account_id;
- signed nonzero 64-bit peer_id;
- positive message_id where required;
- account belongs to current user;
- durable selection exists;
- selection.scope_active=true;
- decrypted provider peer reference is structurally valid;
- canonical peer id derived from reference exactly equals frozen peer_id.

Do this before approval and revalidate immediately before provider write.

No username/title guessing.
No manual_selected grant.
No credential/reference material in frozen plan or outputs.

If route/reference/account/scope is invalid before provider call => definite failure / zero provider write.

## C1B-A — Edit own sent message

### Eligibility

Edit only when all are true:
- canonical MTProto object;
- metadata.direction == "outbound";
- current active scope;
- provider message id is valid;
- message has not been tombstoned/deleted locally;
- body is non-empty and within Telegram max length.

Do not allow editing an inbound message.

Do not assume Telegram will permit every historical outgoing edit; provider rejection is a definite failure.

### Frozen plan

Freeze at minimum:
- account_id
- peer_id
- message_id
- new body
- safe display metadata only
- operation_id

Do not freeze session/reference/credentials.

### Write safety

Transport must support edit against exact peer+message_id.

Revalidate route/reference before write.

Classify:
- malformed/unauthorized/not-owned/precondition/provider definite rejection => failed_definite;
- timeout/network ambiguity after possible provider write => uncertain;
- uncertain => no automatic retry.

Repeated succeeded operation => no second provider edit.

### Local convergence

After confirmed edit:
- update the same canonical Object;
- keep external_id/object_id stable;
- update body/title;
- preserve transport/account/peer/message/direction metadata;
- set edited_at consistently;
- with AI=false enqueue zero AI work;
- with AI=true existing semantic-update embedding behavior may apply.

Later A3 history sync of the same edited message must converge to the same body/edited_at, not create a second object.

## C1B-B — Delete/revoke message

### Eligibility

Deletion must address exact account+peer+message_id.

Do not guess whether Telegram permits revoke-for-all; use an explicit provider operation with a clearly defined mode.

For C1B, prefer one conservative canonical behavior:
- delete/revoke the exact Telegram message using the provider's normal message deletion semantics for the authenticated user;
- if Telegram rejects due to rights/age/type/etc., treat as definite failure.

Do not silently downgrade to local-only hide.

### Write safety

Freeze account_id, peer_id, message_id and operation_id.

Revalidate route/reference immediately before provider write.

Provider ambiguity after possible delete => uncertain; never auto-retry uncertain deletion.

Repeated succeeded delete => no second provider delete.

### Local state

After confirmed provider deletion:
- retain canonical Object record for provenance/audit;
- tombstone/hide it using existing object deletion/tombstone semantics;
- do not purge DB row;
- do not create a second deletion representation;
- later passive history sync must not resurrect it if existing accepted skip-hidden/tombstone semantics already prevent that.

AI quarantine remains respected.

## C1B-C — Mark read

### Semantics

Mark the exact active peer read up to a frozen positive `max_message_id`.

Preferred source for the target:
- a canonical MTProto message object in that peer;
- freeze its account_id, peer_id and message_id as `max_message_id`.

Do not use "latest" or a mutable implicit target in the approved plan.

Transport must invoke the provider read acknowledgement against the exact durable peer reference and frozen max_message_id.

### Safety / idempotency

Mark-read is idempotent but still an external mutation.

Revalidate account/scope/reference before provider write.

A repeated succeeded operation must not require another provider call under the approved execution replay semantics.

Provider definite rejection => failed_definite.
Network ambiguity may be uncertain; do not invent success.

Do not modify message body/content.
If there is an existing local deterministic unread/read representation that is canonical, update it consistently; otherwise do not invent a new DB schema in C1B merely to cache read state.

No migration is authorized.

## Tool / schema design

Use narrow canonical input/output schemas.

Preferred tool names should be explicit and provider-neutral enough to fit the existing registry if possible, for example:
- `edit_message`
- `delete_message`
- `mark_message_read` or `mark_conversation_read`

But do not broaden other providers in C1B unless required by existing registry invariants.

If existing policy/tool infrastructure requires provider-specific internal routes, keep public semantics generic and route internally by frozen provider data.

All irreversible external writes must remain single-action pending plans according to existing action-plan policy.

## Telethon transport

Extend `TelegramMtprotoTransport` and `TelethonMtprotoTransport` with narrowly typed methods for:
- edit exact message;
- delete exact message;
- mark read up to exact message id.

Each method must:
- validate durable provider reference vs expected peer id before client/provider write;
- authenticate using stored user session;
- sanitize errors;
- never log/reference credentials;
- distinguish definite pre-write/provider rejection from uncertain outcome after possible write.

Do not add retries that could duplicate or repeat destructive actions.

## Tests

Add focused tests at minimum for:

### Edit
- outbound own MTProto object can prepare edit plan;
- inbound object cannot;
- inactive scope cannot;
- malformed/mismatched reference fails before plan;
- frozen plan contains no credentials/reference;
- exact peer+message id sent once;
- confirmed edit updates same object id/external_id;
- success replay does not call provider again;
- uncertain edit not retried;
- definite edit failure recorded;
- AI=false edit does not enqueue embedding/AI work;
- later A3 edited history converges to same object/body.

### Delete
- exact active MTProto object can prepare delete plan;
- mismatched/invalid route fails before plan;
- exact provider deletion called once;
- confirmed delete tombstones/hides same object without purge;
- passive history re-import does not resurrect tombstoned object;
- replay does not call provider again;
- uncertain delete not retried;
- definite rejection recorded.

### Mark read
- exact message freezes max_message_id;
- inactive/wrong-account/malformed route fails;
- exact peer + max_message_id provider call;
- success replay no second call;
- definite/uncertain classifications;
- no content mutation;
- no migration.

### Regression
- C1A send/reply still passes;
- C1AR recipient integrity still passes;
- Bot/Business Telegram unchanged;
- Telegram A1-A4/Q1 regressions pass;
- action-plan integrity / execution gateway relevant tests pass;
- Alembic head remains `0046`.

Run Ruff on changed Python files and `git diff --check`.

## Explicitly out of scope C1B

Do NOT implement:
- realtime MTProto update subscription;
- client composer/edit/delete/read UI;
- Android notifications;
- production deploy/ref move;
- production DB/env changes;
- migration `0047`;
- Bot API retirement;
- D-Bus/Android fallback.

Those come later.

## Branch / deliverable

Start from latest `origin/main`.

Create/use:
`review/telegram-mtproto-c1b-mutations`

Return:
- `STARTING_SHA`
- `C1B_SHA`
- changed files
- tool/schema design
- write-attempt/idempotency design
- exact edit/delete/mark-read provider semantics
- local convergence behavior
- focused/regression tests
- Ruff
- git diff --check
- Alembic head `0046`
- production untouched

Final marker:
`TELEGRAM_MTPROTO_C1B_MUTATIONS_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
