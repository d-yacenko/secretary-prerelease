# Current task — Telegram MTProto M4AD final retry: live read-only production diagnosis

## Status

Production backend/runtime expected:
`8091736337689b68b4510126e74d9e409397f696`

Production Alembic expected:
`0046`

Human completed MTProto login, folders/groups loaded, one manual group was selected, and the first manual sync returned:
`Telegram MTProto authorization is no longer valid`

Official Telegram Active Devices still shows the newly created Secretary MTProto session as active.

M4ADH/M4ADH2 have now cleared the SSH infrastructure blocker:

- repository-pinned ED25519 fingerprint:
  `SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs`
- three independent keyscans were stable;
- exact repository `_verified_known_hosts()` returned one matching ED25519 line;
- `ssh-keygen -F web-itx.duckdns.org` matched the generated file;
- inherited SSH config does not alter target/port/proxy/canonicalization;
- strict no-auth probes A/B/C all passed host-key verification;
- previous SSH failure is classified invocation-specific/transient.

Do NOT change `target.json`, the pin, SSH config, or known_hosts.

This task authorizes only **live read-only M4AD production diagnosis**.

## Required SSH invocation contract

Build the temporary known_hosts file using the exact current repository helper:

`ops/production/deploy.py::_verified_known_hosts()`

for:
- target `root@web-itx.duckdns.org`
- port `22`
- expected fingerprint `SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs`

For the authenticated read-only SSH session use inherited SSH config plus explicit:

- `BatchMode=yes`
- `StrictHostKeyChecking=yes`
- `UserKnownHostsFile=<exact temp file>`
- `GlobalKnownHostsFile=/dev/null`
- `HostKeyAlgorithms=ssh-ed25519`
- short connect timeout

Do NOT use `-F /dev/null` for the authenticated session, because normal identity/auth configuration may still be needed.

If host-key verification fails again, STOP. Do not bypass it.

## Allowed read-only production actions

- Git ref/worktree inspection;
- `docker ps`, `docker inspect`;
- sanitized `docker logs` for api/worker;
- read-only PostgreSQL SELECTs;
- read-only code/file inspection.

## Forbidden

Do NOT:
- re-authenticate Telegram;
- retry manual history sync;
- click/apply scope;
- make ad-hoc Telegram/provider calls;
- run direct Telethon probes;
- decrypt or print the stored Telegram session;
- restart/recreate services;
- write to DB;
- edit env;
- run Alembic writes;
- move refs;
- change code;
- mutate production;
- touch Bot API;
- change MTProto AI quarantine.

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

Read-only verify:

- production ref exact `8091736337689b68b4510126e74d9e409397f696`;
- runtime api/worker exact release provenance if determinable read-only;
- Alembic exact `0046`;
- DB/api/worker healthy/running;
- production worktree clean.

Return PASS/FAIL without secrets.

## 2. Persisted MTProto state

Using read-only SELECTs, return only booleans/counts:

- exactly one MTProto account row for the affected Secretary user: yes/no;
- `session_encrypted` non-empty: yes/no;
- account row freshness consistent with the recent login: yes/no;
- active auth challenge count;
- manual-selected group count;
- configured sync-folder count;
- active scope count.

Do NOT decrypt session material.

## 3. Recurring Telegram job / concurrency

Inspect:

- whether a recurring Telegram MTProto sync job exists;
- status: pending/running/failed;
- last run/failure relative to login/manual-sync attempt;
- sanitized failure class/category if persisted;
- whether current folder/scope state would cause `reconcile_scope` to issue provider calls;
- whether a worker provider-call window plausibly overlapped the manual sync.

Do not trigger/rearm anything.

## 4. API/worker evidence

Inspect only the narrow recent window around:
- MTProto auth completion;
- folder/group discovery;
- manual group selection;
- first manual group sync.

Return:
- MTProto route names and status codes if logs contain them;
- normalized exception/error class names;
- whether manual sync returned HTTP 409 authorization-invalid;
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

Do not print raw exception payloads containing identifiers.

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

Choose only from evidence:

A. provider authorization truly revoked/unregistered;
B. likely concurrent auth-key duplication;
C. stored-session persistence/corruption defect;
D. insufficient evidence.

Do not repair or re-login during this task.

If D, propose the smallest separately authorized next diagnostic/test.

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

`TELEGRAM_MTPROTO_M4AD_DIAGNOSIS_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
