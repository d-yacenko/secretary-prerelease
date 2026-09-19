# Current task — Telegram MTProto M4AD-LIVE: production read-only diagnosis

## Status

SSH transport blocker is CLOSED.

M4ADH3 proved, in one exact invocation path:
- `_verified_known_hosts()` PASS;
- temporary known_hosts exists/non-empty;
- parser match PASS;
- pinned ED25519 fingerprint PASS;
- `ssh -G` contract PASS;
- direct argv, no `sh -c`, PASS;
- strict host-key verification PASS;
- SSH authentication PASS;
- remote `true` exit code 0.

Production data was not inspected and production was not mutated during M4ADH3.

Production backend/runtime expected:
`8091736337689b68b4510126e74d9e409397f696`

Production Alembic expected:
`0046`

Human MTProto flow observed:
- login completed through UI;
- folders/groups loaded;
- one manual group selected;
- first explicit manual group sync showed `Telegram MTProto authorization is no longer valid`;
- official Telegram Active Devices still shows the newly created Secretary session as active.

This task authorizes only **M4AD-LIVE — sanitized read-only production diagnosis**.

## Required SSH transport

Reuse the exact M4ADH3 transport construction in the SAME process/session:
- exact current `ops/production/deploy.py::_verified_known_hosts()`;
- target `root@web-itx.duckdns.org`, port 22;
- expected pin `SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs`;
- write returned line to temp known_hosts;
- keep temp file alive until all authorized remote commands finish;
- invoke `ssh` directly as argv, never via `sh -c`.

Required SSH options:
- `-p 22`
- `-o BatchMode=yes`
- `-o StrictHostKeyChecking=yes`
- `-o UserKnownHostsFile=<same live temp file>`
- `-o GlobalKnownHostsFile=/dev/null`
- `-o HostKeyAlgorithms=ssh-ed25519`
- `-o ConnectTimeout=5`

Do NOT use `-F /dev/null` for authenticated access.

If host-key verification fails, STOP. Do not bypass.

## Allowed production actions

Read-only only:
- Git ref/worktree inspection;
- `docker ps`, `docker inspect`;
- sanitized `docker logs` for api/worker;
- read-only PostgreSQL SELECTs;
- read-only code/file inspection;
- health check.

## Forbidden

Do NOT:
- re-authenticate Telegram;
- retry manual history sync;
- apply scope;
- make ad-hoc Telegram/provider calls;
- run direct Telethon probes;
- decrypt/print stored Telegram session;
- restart/recreate services;
- write DB;
- edit env;
- run Alembic writes;
- move Git refs;
- change code;
- mutate production;
- touch Bot API;
- alter MTProto AI quarantine.

Do not print:
- Secretary user/account IDs;
- Telegram user IDs;
- peer IDs;
- phone;
- session ciphertext/plaintext;
- bearer tokens;
- credential key/API hash;
- provider references;
- IP addresses;
- raw message content.

## 1. Production state

Verify read-only:
- production ref exact `8091736337689b68b4510126e74d9e409397f696`;
- runtime api/worker release provenance if determinable read-only;
- Alembic exact `0046`;
- DB/api/worker running/healthy;
- production worktree clean.

## 2. Persisted MTProto state

Using read-only SELECTs, return only booleans/counts:
- exactly one MTProto account row for affected Secretary user: yes/no;
- `session_encrypted` non-empty: yes/no;
- account row freshness consistent with recent login: yes/no;
- active auth challenge count;
- manual-selected group count;
- configured sync-folder count;
- active scope count.

Do NOT decrypt session material.

## 3. Recurring Telegram job / concurrency

Inspect:
- recurring Telegram MTProto sync job exists yes/no;
- status pending/running/failed;
- last run/failure relative to login/manual-sync attempt;
- sanitized failure class/category if persisted;
- whether current folder/scope state would cause `reconcile_scope` provider calls;
- whether worker provider-call activity plausibly overlapped the manual sync.

Do not trigger/rearm anything.

## 4. API/worker evidence

Inspect only the narrow recent window around:
- MTProto auth completion;
- folder/group discovery;
- manual group selection;
- first manual group sync.

Return:
- MTProto route names and HTTP status codes if logged;
- normalized exception/error class names;
- whether manual group sync returned authorization-invalid / HTTP 409;
- whether worker independently saw authorization-invalid or provider-unavailable;
- evidence yes/no for:
  - `AUTH_KEY_DUPLICATED`
  - `AuthKeyDuplicatedError`
  - `AUTH_KEY_UNREGISTERED`
  - `AuthKeyUnregisteredError`
  - `SESSION_REVOKED`
  - `SessionRevokedError`
  - `UnauthorizedError`
  - `AuthKeyNotFound`

Do not print raw payloads containing identifiers.

## 5. Exact release code-path confirmation

At exact release SHA confirm:
- `session_encrypted` is written only by authorized-account save/update;
- discovery/history/worker do not overwrite it;
- manual group selection does not overwrite it;
- history sync decrypts and uses that same stored session;
- status endpoint is DB-only and can render connected despite provider auth invalidity;
- fake/unit auth tests do not prove real Telethon 2FA StringSession reopen behavior;
- `AuthKeyDuplicatedError` is not explicitly classified and state its actual fallback path.

## 6. Classification

Choose only from live evidence:
A. provider authorization truly revoked/unregistered;
B. likely concurrent auth-key duplication;
C. stored-session persistence/corruption defect;
D. insufficient evidence.

Do not repair or re-login during this task.

If D, propose the smallest separately-authorized next diagnostic/test.

## Completion report

Return:
- strict pinned SSH verification PASS/FAIL;
- production ref/runtime/Alembic/health;
- MTProto account/challenge/selection/scope booleans/counts;
- recurring Telegram job state;
- sanitized API/worker evidence;
- AuthKeyDuplicated evidence yes/no;
- exact code-path conclusions;
- classification A/B/C/D with evidence;
- confirmation no Telegram/provider call was made by diagnostic;
- confirmation no session was decrypted/printed;
- confirmation no production mutation occurred.

Final marker:
`TELEGRAM_MTPROTO_M4AD_LIVE_DIAGNOSIS_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
