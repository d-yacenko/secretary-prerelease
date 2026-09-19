# Current task — Telegram MTProto M4AD: production authorization-invalid diagnosis

## Status

Production backend/runtime remains:
`8091736337689b68b4510126e74d9e409397f696`

Production Alembic:
`0046`

Fresh exact-SHA Linux client is available and exposes the Telegram MTProto controls.

Human completed Telegram login through the existing MTProto UI, including 2FA. After authorization:
- connected identity rendered;
- folders rendered;
- groups rendered;
- human selected exactly one manual group;
- the group-selection provider discovery succeeded.

On the first explicit manual group sync:
- no history counters appeared;
- the UI showed `Telegram MTProto authorization is no longer valid`.

Official Telegram -> Active Devices currently shows the newly created Secretary MTProto session as active. This is human-observed evidence only; do not print or persist its identifiers/location metadata.

Important: the Account/status UI can still display a connected account because `TelegramMtprotoAuthService.status()` is DB-row based and does not live-probe Telegram authorization.

This task authorizes only **M4AD — sanitized read-only diagnosis of why persisted MTProto authorization became invalid between successful discovery and first history sync**.

Do NOT re-authenticate, retry history sync, alter scope, deploy code, mutate production, or touch Telegram sessions.

## User safety

Until M4AD completes:
- do not retry Telegram login;
- do not terminate the new Telegram session from Telegram Devices;
- do not retry Sync;
- do not click Apply Scope;
- keep Bot API untouched.

## Production diagnostic authorization

A narrowly scoped read-only production inspection is authorized.

Use only the canonical committed production target and strict SSH host-key verification from existing production tooling.

Allowed read-only actions:
- Git/ref/worktree verification;
- docker inspect / docker ps;
- sanitized docker logs for api/worker;
- read-only PostgreSQL SELECTs;
- read-only file/code inspection.

Forbidden:
- service restart/recreate;
- DB writes;
- env edits;
- Alembic writes;
- ref moves;
- ad-hoc Telegram/provider auth calls;
- direct Telethon connection/probe;
- decrypting/printing session content;
- Telegram logout/revoke;
- code changes.

Do not print account IDs, Telegram user IDs, peer IDs, phone, session ciphertext/plaintext, bearer tokens, credential key/API hash, provider references, IP addresses, or raw user content.

## Diagnostic questions

### 1. Persisted account state

Using read-only DB inspection, return booleans/counts only:
- exactly one MTProto account row exists for the affected Secretary user;
- `session_encrypted` is non-empty;
- account row freshness is consistent with the recent login (relative freshness only);
- active auth challenge count is zero after completed login;
- selected manual-group count;
- configured sync-folder count;
- active scope count.

Do NOT decrypt or print the session.

### 2. Recurring worker concurrency

Inspect:
- whether a Telegram recurring source-sync job exists;
- sanitized status: pending/running/failed;
- last run/failure relative to login/sync attempt;
- sanitized failure category/class if persisted;
- whether current configured folder/scope state could have caused `reconcile_scope` provider calls concurrently with the manual sync.

Do not trigger/rearm jobs.

### 3. API/worker evidence

Inspect only the narrow time window around the latest MTProto login/group-selection/manual-sync activity.

Return:
- route names/status codes for MTProto auth/group/sync calls if present;
- normalized exception/error class names where available;
- whether manual sync returned authorization-invalid;
- whether worker independently observed authorization-invalid/provider-unavailable in the same window;
- whether any `AUTH_KEY_DUPLICATED` / `AuthKeyDuplicatedError` evidence exists;
- whether any `AUTH_KEY_UNREGISTERED`, `SESSION_REVOKED`, `UnauthorizedError`, or `AuthKeyNotFound` class evidence exists.

Do not print raw exception payloads if they may contain identifiers.

### 4. Code-path audit at exact release SHA

Prove:
- `session_encrypted` is written only by authorized-account save/update paths, not discovery/history/worker;
- group selection does not overwrite account session;
- history sync decrypts the same stored account session;
- status endpoint is DB-only and can display connected despite provider auth invalidity;
- existing fake/unit auth tests do not prove a real Telethon 2FA StringSession can be reopened for later provider calls;
- identify whether `AuthKeyDuplicatedError` is explicitly classified; if not, state its actual current fallback path.

### 5. Classification

Do NOT repair or re-login during M4AD.

Classify evidence as one of:
A. provider authorization truly revoked/unregistered;
B. likely concurrent auth-key duplication;
C. stored-session persistence/corruption defect;
D. insufficient evidence.

If evidence is insufficient, propose the smallest separately-authorized diagnostic/test.

## Completion report

Return:
- production ref/runtime and health, read-only;
- account/challenge/selection/scope booleans/counts;
- recurring job state;
- sanitized API/worker evidence;
- exact code-path conclusions;
- whether AuthKeyDuplicated evidence exists;
- classification A/B/C/D and why;
- confirmation no Telegram/provider call was made by diagnostic;
- confirmation no session was decrypted/printed;
- confirmation no production mutation occurred.

Final marker:
`TELEGRAM_MTPROTO_M4AD_DIAGNOSIS_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
