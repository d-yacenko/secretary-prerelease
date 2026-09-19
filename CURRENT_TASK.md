# Current task — Telegram MTProto M4AF: local stored-session/reference structural probe

## Status

M4AE human provider-backed discovery probe: PASS.

Observed:
- first reopen showed only Secretary-server connectivity failure;
- subsequent repeated reopens loaded connected MTProto identity, folders, and groups normally;
- no Telegram authorization-invalid error appeared.

Therefore the currently stored MTProto session can reconnect and perform Telegram discovery calls.

Earlier manual group sync still returned HTTP 409 surfaced as:
`Telegram MTProto authorization is no longer valid`.

Exact release code fact:
`TelethonMtprotoTransport.fetch_history()` maps both real auth-loss exceptions AND generic
`ValueError` / `TypeError` to `TelegramMtprotoAuthorizationInvalidError`.

Before making any new Telegram history/provider call, this task authorizes only a **local structural validation of the already-stored session and selected-group provider reference**.

## Goal

Determine whether the failure can already be reproduced locally before any Telegram network call.

Classify independently:

1. encrypted session can be decrypted in memory;
2. decrypted session can initialize Telethon `StringSession`;
3. encrypted selected-group provider reference can be decrypted in memory;
4. provider reference JSON/shape can be parsed by the exact release helper;
5. `validate_provider_peer_reference(..., expected_peer_id=...)` passes;
6. constructing `TelegramClient(StringSession(session), api_id, api_hash)` succeeds WITHOUT calling `connect()`.

No Telegram network call is authorized.

## Production / transport

Use the already-reviewed strict pinned SSH pattern.

Production expected:
- release `8091736337689b68b4510126e74d9e409397f696`;
- Alembic `0046`.

Read-only production access only.

## Authorized actions

- strict pinned SSH;
- read-only DB SELECTs needed to identify the single MTProto account and single manual-selected group;
- execute a short Python diagnostic inside the existing backend runtime/container;
- use existing application `CredentialEncryption`;
- decrypt session/reference **only in process memory**;
- instantiate `StringSession`;
- call exact release local reference parser/validator;
- instantiate `TelegramClient` object without connecting;
- emit only sanitized booleans/stage/class names.

## Strictly forbidden

Do NOT:
- call `client.connect()`;
- call `is_user_authorized()`;
- call `iter_dialogs()`, `iter_messages()`, `get_messages()`, `get_me()`, or any Telegram API;
- make any Telegram/provider network call;
- print decrypted session/reference;
- print encrypted session/reference;
- print account/user/Telegram/peer IDs;
- print phone, username, title, provider ref, access hash, API hash, API ID, credential key, tokens;
- mutate DB;
- retry login;
- retry Sync;
- Apply Scope;
- restart/recreate services;
- edit env/files;
- run Alembic writes;
- change Git refs;
- change Bot API or MTProto AI flags.

## Required sanitized output

Return only:

- production release/ref match: true/false;
- Alembic 0046: true/false;
- exactly one MTProto account: true/false;
- exactly one manual-selected group: true/false;

Structural stages:
- `SESSION_DECRYPT_PASS=true/false`
- `STRING_SESSION_PARSE_PASS=true/false`
- `REFERENCE_DECRYPT_PASS=true/false`
- `REFERENCE_PARSE_PASS=true/false`
- `REFERENCE_PEER_MATCH_PASS=true/false`
- `TELEGRAM_CLIENT_CONSTRUCT_PASS=true/false`

If a stage fails:
- emit only `FAILURE_STAGE=<stage>`
- emit only the Python exception class name, e.g. `ValueError`, `TypeError`, or application exception class;
- do NOT emit exception message if it may contain sensitive values.

Also confirm:
- `TELEGRAM_NETWORK_CALLS=0`
- `SESSION_OR_REFERENCE_PRINTED=false`
- `PRODUCTION_MUTATION=false`

## Interpretation

A. Local session parse fails
=> stored-session persistence/serialization defect is strongly indicated.

B. Local provider-reference parse/peer-match fails
=> stored selected-group provider-reference defect is strongly indicated.

C. All local structural stages pass
=> stored session/reference are structurally valid; next step may be a separately-authorized one-shot live `fetch_history` stage probe with sanitized exception-class telemetry.

Do not perform that live provider probe during M4AF.

## Completion

Final marker:
`TELEGRAM_MTPROTO_M4AF_STRUCTURAL_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
