# Current task — Telegram MTProto C1A: send/reply through canonical communication action

## Status

Telegram MTProto Q1/Q1R/Q1R2 AI quarantine is **ACCEPTED and integrated to main**.

Accepted implementation chain:
- Q1 `b306b6d1ad1a4e7ae0d2dd3260bd5b746d2f2595`
- Q1R `39e3f2f24ca1bcd695e27d070bfde229c131c7cb`
- Q1R2 `8fa8f52dd81309f4530867852fe291038998148e`
- main integration merge `b50e1e62f825cff960f5a1a3a50711fd25863697`

Production remains:
- ref/runtime `5cce4b57b14e0052a038acae1354a2821a2bb77b`
- Alembic `0041`
- M3 NOT authorized
- Bot API retirement NOT authorized

Canonical Telegram MTProto AI setting remains:
`TELEGRAM_MTPROTO_AI_ENABLED=false` by default.

## C1A goal

Add Telegram MTProto **compose/send and reply** support to the existing generic communication action path.

Do not create a parallel Telegram mutation API or bypass the existing architecture.

Canonical mutation path remains:

User/UI/Assistant
-> DomainToolService.prepare_send_message
-> frozen SendMessageCanonicalInput
-> pending action plan
-> explicit approval
-> execution gateway
-> DomainToolService.send_message
-> CommunicationExternalActionService
-> MTProto transport

The legacy Telegram Bot API send path must continue to work unchanged.

## Routing distinction

Telegram provider now has two transports:

1. legacy Bot/Business path
   - existing behavior
   - metadata does NOT identify canonical MTProto transport

2. canonical MTProto path
   - `provider == "telegram"`
   - `kind == "chat_message"`
   - `metadata.transport == "mtproto"`

Do not infer MTProto merely from provider == telegram.

## Canonical MTProto route validation

For a MTProto anchor, validate/freeze at prepare time:

- Secretary object ownership;
- object is active under accepted A4.3 transport visibility;
- canonical MTProto metadata;
- `account_id` is a valid UUID and belongs to current Secretary user;
- connected MTProto account exists;
- `peer_id` is signed 64-bit nonzero;
- `message_id` is positive integer for reply anchors;
- matching durable `TelegramMtprotoChatSelection` exists for account+peer;
- selection `scope_active == true`;
- provider peer reference is available/decryptable;
- route identity/account/peer cannot be guessed or substituted.

Do not use `manual_selected` to grant current scope.

If scope/account/reference is missing or malformed: fail closed before approval.

### Compose semantics

Existing generic `SendMessageInput.conversation_object_id` remains compose mode.

For a canonical MTProto anchor:
- destination is the frozen account+peer of the anchor;
- do not reply to the anchor message;
- no recipient guessing.

### Reply semantics

Existing generic `SendMessageInput.reply_to_object_id` remains reply mode.

For canonical MTProto:
- destination is frozen account+peer;
- reply target is frozen source Telegram `message_id`.

## Frozen canonical payload

Extend the existing send-message canonical route model cleanly for MTProto.

Do not overload the Bot/Business `TelegramSendRoute` with mutually incompatible fields if that makes validation ambiguous.

A separate `TelegramMtprotoSendRoute` (or equivalent discriminated route) is preferred.

Frozen route must contain only non-secret routing facts required for execution, such as:
- account_id;
- peer_id;
- source_message_id;
- reply_to_message_id if reply;
- safe display metadata if needed.

Do NOT put:
- session strings;
- api_hash;
- encrypted provider references;
- credential material

into pending plans/audit payloads.

Execution must reload/decrypt credentials and provider reference from durable stores after approval.

## MTProto transport

Extend `TelegramMtprotoTransport` / `TelethonMtprotoTransport` with a bounded send method supporting:

- compose message;
- reply to provider message id;
- existing max Telegram message-body constraint;
- user session from the connected MTProto account;
- durable provider peer reference rather than guessed username/title.

Return enough normalized provider facts to validate and materialize the created message:
- message id;
- peer identity/reference consistency;
- text/body;
- timestamp;
- reply target where applicable;
- sender/account identity when available.

Do not expose credentials in logs/errors/results.

## Write safety / exactly-once

Reuse existing `ExternalActionAttempt` operation claim semantics used by generic `send_message`.

Required:
- one frozen `operation_id`;
- no transparent resend after an uncertain write;
- repeated execution of succeeded operation returns already-sent result;
- definite pre-write/provider rejection may become failed_definite;
- timeout/network/provider ambiguity after a possible send becomes uncertain;
- uncertain operation must NOT be retried automatically.

If MTProto/Telethon errors need explicit definite-vs-uncertain write classes, add narrowly scoped errors under the Telegram MTProto connector.

FloodWait/RetryAfter during an approved external write must not cause an automatic duplicate send.

## Materialization

On confirmed successful MTProto send/reply:

- materialize the created outgoing message through the canonical Telegram materializer;
- metadata must remain canonical MTProto:
  - transport=mtproto
  - account_id
  - peer_id
  - message_id
  - reply_to_message_id when applicable
  - sender/direction fields consistent with existing A3 normalization
- external_id must use the same canonical MTProto external-id scheme as imported history;
- repeated successful-operation resume must resolve to the already materialized object where possible;
- with `TELEGRAM_MTPROTO_AI_ENABLED=false`, materialization must still create/update the object but enqueue zero AI embedding jobs per accepted Q1.

Do not invent a second MTProto object format.

## AI quarantine interaction

C1A MUST NOT weaken Q1.

Sending via MTProto is allowed while AI=false because this is ordinary messenger functionality.

The newly created outgoing MTProto object:
- appears in ordinary Inbox/messenger data according to transport visibility;
- remains AI-ineligible while flag=false;
- must not trigger embedding/summarization/correlation/classification paths while disabled.

## Tests

Add focused tests proving at minimum:

1. prepare compose from active MTProto anchor produces frozen MTProto route;
2. prepare reply freezes exact source message id;
3. inactive scope fails closed;
4. wrong user/account fails closed;
5. malformed account/peer/message metadata fails closed;
6. Bot/Business Telegram prepare/send regression unchanged;
7. compose calls MTProto transport exactly once with expected peer and no reply target;
8. reply calls exactly once with frozen reply message id;
9. successful MTProto send materializes canonical outgoing object;
10. AI=false successful send materializes but enqueues zero AI work;
11. succeeded operation replay does not resend;
12. uncertain write records uncertain and replay does not resend;
13. definite failure records failed_definite;
14. provider/session/reference credentials never appear in canonical pending payload/output;
15. body length bound preserved;
16. no migration; Alembic head remains `0046`.

Run:
- focused C1A tests;
- Telegram A1-A4/Q1 regressions;
- communication external-action / pending-action-plan integrity suites;
- relevant DomainToolService/execution gateway tests;
- Ruff changed Python files;
- git diff --check.

## Explicitly out of scope C1A

Do NOT implement yet:
- edit sent message;
- delete/revoke message;
- mark-read/read receipts;
- realtime update subscription;
- client composer UI;
- Android notifications;
- production deploy/ref move;
- production DB/env mutation;
- Bot API removal;
- D-Bus fallback;
- migration `0047`.

Those are later phases.

## Branch / deliverable

Start from latest `origin/main`.

Create/use review branch:
`review/telegram-mtproto-c1a-send-reply`

Return:
- `STARTING_SHA`;
- `C1A_SHA`;
- changed files;
- canonical MTProto route design;
- exact uncertain-write behavior;
- materialization behavior with AI=false;
- focused/regression test results;
- Ruff;
- git diff --check;
- Alembic head `0046`;
- production untouched.

Final marker:
`TELEGRAM_MTPROTO_C1A_SEND_REPLY_READY`

Then STOP for Architect review.

`CURRENT_TASK.md` is the source of active authorization.
