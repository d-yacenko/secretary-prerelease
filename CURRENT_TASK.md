# Current task — Telegram MTProto C1BR: mutation write-safety corrective

## Review status

C1B implementation:
`4d61ebeb2d96e5bfb6393ef3e39d214cd814fc51`

Independent review result: **REJECTED pending C1BR corrective**.

The following C1B architecture is retained:
- public tools `edit_message`, `delete_message`, `mark_message_read`;
- `ToolPermission.COMMUNICATE`;
- prepare -> frozen canonical action -> explicit approval -> execution gateway;
- C1AR account/scope/provider-reference integrity;
- `ExternalActionAttempt` operation claims;
- no migration;
- Q1 AI quarantine remains mandatory.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`;
- production Alembic `0041`;
- M3 NOT authorized.

## C1BR blocker 1 — definite Telegram RPC rejection is currently misclassified as uncertain

Current Telethon mutation methods only classify a narrow auth/invalid-peer set as definite.
Other normal Telegram RPC rejections fall through the broad `Exception` branch and become `TelegramMtprotoWriteUncertainError`.

That violates the C1B contract.

For example, edit can be rejected because:
- message is not authored/editable by the account;
- edit time/permissions do not allow it;
- message id is invalid/non-editable;
- content is not modified or otherwise rejected by Telegram.

These are provider-known outcomes, not ambiguous writes.

### Required

Refine MTProto mutation error classification.

At minimum:
- known Telegram/Telethon client-side/precondition failures before a provider write -> definite;
- auth/session invalid -> definite;
- Telegram RPC 400/403/404-style deterministic rejection classes relevant to edit/delete/read -> definite;
- malformed/mismatched provider reference -> definite;
- timeout/network/server ambiguity after a write may have reached Telegram -> uncertain;
- no automatic retry for uncertain;
- do not leak raw provider details/credentials.

Do NOT simply classify every possible `RPCError` as definite if the base class can represent server-side/transient ambiguity. Use the installed Telethon hierarchy deliberately.

Keep C1A send/reply behavior unchanged unless a shared helper can be introduced without changing its accepted semantics.

### Tests

Use representative real Telethon error classes (not only the custom fake definite error) and prove:
- deterministic edit rejection -> `failed_definite`, not uncertain;
- deterministic delete rejection -> `failed_definite`;
- deterministic mark-read rejection -> `failed_definite`;
- network/timeout ambiguity remains uncertain;
- replay never repeats either uncertain or failed-definite operations.

## C1BR blocker 2 — delete must verify message belongs to frozen peer before destructive provider call

Telethon `delete_messages(entity, ids)` does not itself guarantee that the supplied message ids belong to the supplied private/small-group peer.

The C1B contract requires exact frozen `account_id + peer_id + message_id`.

### Required

Before the destructive delete request:
1. validate durable provider reference vs frozen peer as already done;
2. perform a provider-side read/preflight for the exact frozen message id;
3. verify:
   - returned message id == frozen message_id;
   - returned message peer canonically resolves to frozen peer_id;
4. only then call the destructive delete.

If the preflight says the message is absent, malformed, or belongs to another peer:
- zero delete calls;
- treat as definite pre-write failure;
- never silently delete another message;
- never fall back to local-only hide.

If the preflight itself fails before any destructive request is issued, the operation is known not to have deleted anything. Classify safely as a pre-write failure; do not call it an ambiguous post-delete outcome.

The transport should expose/test this exact-peer invariant, not rely only on the local Object metadata.

### Tests

Prove:
- private/user peer: provider preflight returns same message id but different peer -> delete not invoked;
- group/channel equivalent mismatch -> delete not invoked;
- exact matching peer+message -> delete called once;
- no provider-reference/session secrets are surfaced.

## C1BR blocker 3 — provider success must be replayable into local convergence without repeating the external write

Current edit/delete flow performs the provider mutation and local Object mutation inside the request session, while `ExternalActionAttempt` is persisted independently.

A request/outer DB transaction can fail or roll back after Telegram already succeeded.
On replay, current `_resume()` returns `already_succeeded` without repairing the local Object.

For delete this can leave a provider-deleted message permanently visible locally, because passive history sync cannot infer a deletion merely from absence.

### Required

For confirmed provider success, make local convergence replay-safe.

Preferred design:
1. validate provider success;
2. persist `ExternalActionAttempt=SUCCEEDED` in the durable attempt session with only safe non-secret result metadata required for local convergence;
3. apply local Object convergence idempotently in the caller/main session;
4. if local convergence or the outer transaction later fails, re-executing the same frozen action:
   - MUST NOT call Telegram again;
   - MUST re-apply the local convergence idempotently.

For edit:
- frozen body is already available;
- preserve same object_id/external_id;
- preserve canonical route/direction metadata;
- use persisted safe `edited_at` if useful;
- AI=false => no embedding/AI enqueue;
- AI=true => existing semantic update behavior remains.

For delete:
- a succeeded replay must ensure the same Object is tombstoned even if its local tombstone was rolled back/lost;
- never reissue provider delete.

For mark-read:
- no local message-content state is required; replay remains provider-no-op.

Do not put credentials/provider references/sessions in `ExternalActionAttempt.result_metadata`.

### Tests

Simulate local state loss after provider success while retaining the succeeded attempt:
- edit replay restores the frozen edited body/metadata and makes zero additional provider calls;
- delete replay restores tombstone and makes zero additional provider calls.

## C1BR blocker 4 — first successful mark-read is not a no-op

Current first successful `mark_read()` returns:
`status="succeeded", changed=False`

The action-plan effect layer therefore reports it as a no-op / already completed even though a provider read acknowledgement was just executed.

### Required

Make mutation output/effect semantics truthful:
- first confirmed mark-read provider mutation -> changed/effect indicates a real external mutation occurred;
- replay of already-succeeded operation -> no new external mutation / changed=false.

Also make execution-effect descriptions semantically correct:
- edit = changed/edited;
- delete = removed/deleted/tombstoned;
- mark-read = changed/marked read;
- replay = already completed/no new provider mutation.

Do not label edit/delete/mark-read as newly "created" objects/actions.

## Missing C1B acceptance coverage to add

The original C1B task required tests that are not present in the current focused file.

Add focused coverage for all of these:

### Edit
- AI=false semantic edit creates zero embed/AI jobs;
- A3 import of the same provider edited message converges to the same object/body/edited_at;
- success replay local-convergence repair as described above;
- real deterministic Telethon RPC rejection is failed_definite.

### Delete
- passive A3/history re-import of the same message does not resurrect a tombstoned Object;
- provider-side exact-peer preflight before delete;
- success replay repairs a lost local tombstone without provider resend;
- deterministic provider rejection is failed_definite.

### Mark read
- definite provider rejection;
- uncertain/network outcome;
- first confirmed success has truthful changed/effect semantics;
- replay has no second provider call and changed=false.

### Shared
- C1AR malformed/mismatched durable reference remains pre-write definite;
- action-plan single-action approval policy remains intact;
- frozen payloads contain no session/reference/credential material;
- C1A send/reply regressions remain green;
- Bot/Business Telegram unchanged;
- Q1 AI quarantine remains green;
- Alembic head remains `0046`.

## Scope

Continue existing branch:
`review/telegram-mtproto-c1b-mutations`

Start from exact:
`C1B_BASE_SHA=4d61ebeb2d96e5bfb6393ef3e39d214cd814fc51`

Create one corrective commit on top. Do not rewrite/squash C1B.

Do NOT implement:
- realtime MTProto updates;
- client UI;
- Android notifications;
- production deploy/ref move;
- production DB/env changes;
- migration `0047`;
- Bot API retirement;
- D-Bus fallback.

## Required checks

Run:
- focused C1B/C1BR tests;
- C1A/C1AR regressions;
- Telegram A1-A4.4/Q1 regressions;
- MTProto history tests;
- action-plan/tool-gateway integrity;
- relevant external-action tests;
- Ruff changed Python files;
- `git diff --check`;
- Alembic head proof `0046`.

## Deliverable

Return:
- `C1B_BASE_SHA=4d61ebeb2d96e5bfb6393ef3e39d214cd814fc51`
- `C1BR_SHA=<exact sha>`
- changed files
- exact definite-vs-uncertain classification rule
- exact delete peer/message preflight rule
- local convergence replay mechanism
- mark-read output/effect semantics
- focused/regression test results
- Ruff
- git diff --check
- Alembic head `0046`
- production untouched

Final marker:
`TELEGRAM_MTPROTO_C1BR_MUTATIONS_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
