# Current task — Telegram MTProto C1AR: recipient integrity + canonical direction corrective

## Review status

C1A implementation:
`a48d6eba209dda946d203500775ee9ecaa00d812`

Independent review result: **REJECTED pending C1AR corrective**.

The overall C1A architecture is retained:
- existing generic `send_message` path;
- frozen `TelegramMtprotoSendRoute`;
- Pending Action Plan -> approval -> execution gateway;
- ExternalActionAttempt exactly-once/uncertain behavior;
- canonical MTProto materialization;
- AI quarantine remains intact.

Production remains untouched:
- runtime/ref `5cce4b57b14e0052a038acae1354a2821a2bb77b`
- Alembic `0041`
- M3 not authorized.

## C1AR blocker 1 — durable provider reference must match frozen peer BEFORE approval

Current C1A prepare path only:
- decrypts `provider_peer_reference_encrypted`;
- checks that the resulting string is non-empty.

That is insufficient.

The durable provider peer reference is a structured JSON reference used by `_input_peer_from_reference()`.
A malformed reference, or a valid reference pointing to a different peer than `selection.peer_id`, must fail closed **before a pending action plan is created**.

Required:

1. Introduce a reusable connector-level validator/helper for provider peer references.
2. It must:
   - parse exactly the currently supported user/chat/channel reference formats;
   - derive the canonical Telethon peer id from the parsed InputPeer;
   - compare it with the expected frozen/selection `peer_id`;
   - reject mismatch or malformed input with `TelegramMtprotoProviderReferenceInvalidError`.
3. `_validated_telegram_mtproto_route()` must call this after decrypting the durable reference.
4. No credential/reference content may appear in the ToolError or pending action payload.

The current C1A test fixture is itself invalid:
- selection.peer_id = 777
- provider reference identifies user id 12345

Correct the fixture so the provider reference canonically resolves to exactly the selection peer id.

Add explicit tests:
- malformed decrypted reference -> prepare fails before approval;
- structurally valid reference for a different peer -> prepare fails before approval;
- valid matching user/chat/channel references pass as appropriate.

## C1AR blocker 2 — revalidate peer/reference immediately before provider write

Even after approval, the durable selection/reference can change.

Execution must reload and revalidate:
- account ownership;
- selection exists and `scope_active=true`;
- decrypted provider reference is structurally valid;
- provider reference canonical peer id == frozen route.peer_id.

This validation must happen before `client.send_message()`.

Additionally, `TelethonMtprotoTransport.send_message()` itself must defensively validate the same reference/peer relationship before connecting/sending.

A malformed or mismatched reference detected before provider write is a **definite pre-write failure**, never `uncertain`.

Current behavior where `TelegramMtprotoProviderReferenceInvalidError` can fall into the broad catch and become uncertain is not acceptable.

Add tests proving:
- mismatched reference causes zero provider send calls;
- it records failed_definite at execution;
- it never records uncertain merely because reference parsing/matching failed;
- correct reference still sends exactly once.

## C1AR blocker 3 — outgoing direction must survive the next A3 history sync

C1A materializes successful outgoing MTProto messages with:

`metadata.direction = "outbound"`

But existing A3 history normalization does not populate direction.
The materializer replaces the full metadata dict on a later sync, so the same outgoing object loses its outbound marker.

This is a canonical-object drift bug. It also changes Inbox behavior because `RecentSourceService` intentionally excludes outbound Telegram/Teams chat messages.

Fix the A3 history representation so direction is canonical and stable.

Preferred design:
- extend `TelegramMtprotoHistoryEntry` with an explicit outgoing flag derived from Telethon message `out`;
- `_history_entry_from_message()` captures it;
- `_normalize_entry()` always writes
  - `direction="outbound"` when provider message is outgoing;
  - `direction="inbound"` otherwise;
- C1A immediate materialization and later A3 sync converge to the same direction semantics.

Do not infer direction solely from `sender_peer_id == account.telegram_user_id`; Telegram can have send-as/anonymous/channel cases. Prefer the provider's explicit outgoing flag.

Keep existing canonical external_id unchanged.

Add a regression test:
1. successful C1A send materializes object as outbound;
2. simulate/import the same provider message through A3 history normalization;
3. same object/external_id remains one object;
4. direction remains outbound after sync;
5. AI=false still creates/enqueues zero AI work.

Also test inbound history gets `direction="inbound"`.

## Preserve accepted C1A behavior

Do not redesign:
- generic send_message architecture;
- separate TelegramMtprotoSendRoute;
- frozen non-secret route payload;
- ExternalActionAttempt semantics;
- success replay no resend;
- uncertain write no automatic retry;
- legacy Bot/Business Telegram path;
- Q1 AI quarantine.

No edit/delete/mark-read yet.
No realtime update work.
No UI.
No migration.
No production.

## Test requirements

Run at minimum:
- focused C1A/C1AR tests;
- Telegram A1-A4/Q1 regressions;
- communication external-action / action-plan integrity suites;
- MTProto history tests;
- DomainToolService/execution gateway relevant suites;
- Ruff on changed Python files;
- git diff --check;
- Alembic head remains `0046`.

## Branch / deliverable

Continue existing branch:
`review/telegram-mtproto-c1a-send-reply`

Start from exact:
`C1A_BASE_SHA=a48d6eba209dda946d203500775ee9ecaa00d812`

Create a new corrective commit; do not rewrite/squash C1A.

Return:
- `C1A_BASE_SHA`
- `C1AR_SHA`
- changed files
- provider-reference validation rule
- execution-time pre-write validation rule
- direction/history convergence design
- focused/regression tests
- Ruff
- git diff --check
- Alembic head `0046`
- production untouched

Final marker:
`TELEGRAM_MTPROTO_C1AR_SEND_REPLY_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
