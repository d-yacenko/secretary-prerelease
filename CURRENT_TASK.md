# Current task — Telegram MTProto M4AG1: implement deterministic one-shot history-stage probe

## Status

M4AF ad-hoc structural probe was blocked before remote runtime by another strict SSH host-key failure.

Do not repeat M4AF manually.

M4AE already proved the currently stored MTProto session can:
- decrypt successfully through the application path;
- initialize Telethon StringSession/TelegramClient;
- connect to Telegram;
- remain authorized;
- perform provider-backed folders/groups discovery repeatedly without auth-invalid.

Therefore the remaining unknown is specifically the selected-group provider reference and the raw Telethon history-read stage.

Exact release fact:
`TelethonMtprotoTransport.fetch_history()` maps broad `ValueError` / `TypeError` failures to
`TelegramMtprotoAuthorizationInvalidError`, which can make a non-auth history failure look like a revoked session.

This task authorizes only **implementation + local tests + review-branch push** for a deterministic, one-shot history-stage probe.

NO production execution is authorized yet.

## Base / branch

Create a new review branch from exact reviewed diagnostic SHA:
`ec4f51be6882433210d62ec6dbcfcdb19563be83`

Preferred branch:
`review/telegram-mtproto-m4ag`

Do not modify main or production.

## Deliverable

Preferred new script:
`ops/production/diagnose_mtproto_history_stage.py`

It may reuse/import the already-reviewed deterministic SSH transport helpers from:
`ops/production/diagnose_mtproto_auth_readonly.py`

Do not weaken or duplicate trust logic unnecessarily.

## Local SSH transport requirements

Reuse exact reviewed behavior:

- canonical `deploy.py::_verified_known_hosts()`;
- target `root@web-itx.duckdns.org`;
- port 22;
- pinned fingerprint `SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs`;
- fresh temp known_hosts per transport attempt;
- temp file alive through subprocess completion;
- direct argv, no local `sh -c`;
- `BatchMode=yes`;
- `StrictHostKeyChecking=yes`;
- `GlobalKnownHostsFile=/dev/null`;
- `HostKeyAlgorithms=ssh-ed25519`;
- `ConnectTimeout=5`;
- maximum 3 attempts only for pre-remote transport/host-key establishment failures;
- authentication failure stops immediately;
- any remote-started probe failure stops immediately;
- no unpinned key acceptance;
- no user known_hosts/config mutation.

## Remote probe design

The future probe is intended to run inside the existing production backend runtime/container.

During this implementation task, DO NOT run it against production.

The remote helper must perform stages in this exact order and stop at the first failure.

### Stage 0 — production guard

Read-only confirm:
- runtime/ref exact `8091736337689b68b4510126e74d9e409397f696`;
- Alembic `0046`;
- exactly one MTProto account;
- exactly one manual-selected group.

No IDs emitted.

### Stage 1 — local stored-state structure

In process memory only:

1. decrypt the stored account session using existing application `CredentialEncryption`;
2. initialize `StringSession(session)`;
3. decrypt the single selected-group `provider_peer_reference_encrypted`;
4. parse it using exact release local reference helper;
5. validate it against the selected row's peer id using exact release `validate_provider_peer_reference`;
6. construct `TelegramClient(StringSession(session), api_id, api_hash)` without network.

Emit only:
- `SESSION_DECRYPT_PASS`
- `STRING_SESSION_PARSE_PASS`
- `REFERENCE_DECRYPT_PASS`
- `REFERENCE_PARSE_PASS`
- `REFERENCE_PEER_MATCH_PASS`
- `TELEGRAM_CLIENT_CONSTRUCT_PASS`

### Stage 2 — one live authorization check

Only if all local structural stages pass:

- call `client.connect()` exactly once;
- call `client.is_user_authorized()` exactly once;
- emit only:
  - `CONNECT_PASS=true/false`
  - `IS_USER_AUTHORIZED=true/false`

If not authorized, stop.

No re-login.

### Stage 3 — one raw Telethon history-read probe

Only if authorized:

- use the already validated InputPeer;
- execute a read-only history iteration equivalent to the first real manual-sync fetch:
  - `iter_messages(input_peer, limit=1, reverse=False)`;
- consume at most one item;
- do not inspect/emit message text, sender, IDs, timestamps, titles, or metadata;
- do not materialize anything;
- do not write DB;
- do not call application `fetch_history()`, because its broad mapping hides the raw exception class.

Emit only:
- `ITER_MESSAGES_STARTED=true/false`
- `ITER_MESSAGES_ONE_ITEM_OR_EMPTY_PASS=true/false`

If an exception occurs, emit only:
- `FAILURE_STAGE=<sanitized stage>`
- `RAW_EXCEPTION_CLASS=<Python/Telethon class name only>`

Never emit exception messages.

Always disconnect in `finally`.

## Forbidden provider operations

The helper MUST NOT call:
- send_message;
- edit_message;
- delete_messages;
- send_read_acknowledge;
- mark read;
- any write RPC;
- login/code/password methods;
- folder/group discovery;
- more than the one authorized history-read iteration.

No automatic provider retry.

## Output allowlist

The remote output must be strictly allowlisted to:

- production guard booleans;
- structural stage booleans;
- connect/auth booleans;
- history stage booleans;
- sanitized stage name;
- exception class name;
- `TELEGRAM_PROVIDER_CALL_COUNT`;
- `PRODUCTION_MUTATION=false`;
- `SESSION_OR_REFERENCE_PRINTED=false`.

It must never emit:
- user/account/Telegram/peer IDs;
- phone;
- usernames/titles;
- encrypted/decrypted session;
- provider reference;
- access hash;
- message IDs/text/content;
- API ID/hash;
- credential key;
- tokens;
- IPs;
- raw logs;
- exception message/traceback.

## Required local tests

Add explicit tests for at least:

1. exact reviewed strict SSH argv/target/port/pin behavior is reused;
2. no local shell wrapper;
3. temp known_hosts lifecycle;
4. max-3 retry only for pre-remote transport failures;
5. auth failure no retry;
6. remote-started failure no retry;
7. Stage 3 cannot run before all structural stages pass and authorization is true;
8. `client.connect()` called at most once;
9. `is_user_authorized()` called at most once;
10. `iter_messages(... limit=1, reverse=False)` called at most once;
11. no application `fetch_history()` call;
12. no Telegram write/login/discovery methods;
13. one-item/empty iterator result never emits message data;
14. raw exception output is class name only, no message/traceback;
15. positive/negative peer ids cannot appear in output;
16. session/reference/API credentials cannot appear in output;
17. helper contains no DB-write / production mutation command;
18. client disconnect executes on success and failure.

Run:
- focused pytest;
- Ruff on changed Python files;
- `git diff --check`.

## Review handoff

After tests:
- commit on `review/telegram-mtproto-m4ag`;
- push only that review branch;
- do not run production probe;
- report:
  - full SHA;
  - test count/pass;
  - Ruff result;
  - diff-check result;
  - concise mapping of tests to safety properties;
  - any remaining gap.

Final marker:
`TELEGRAM_MTPROTO_M4AG1_REVIEW_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
