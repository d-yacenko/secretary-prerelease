# Current task — Telegram MTProto M4AD retry: read-only production authorization-invalid diagnosis

## Status

Production backend/runtime expected:
`8091736337689b68b4510126e74d9e409397f696`

Production Alembic expected:
`0046`

Human completed Telegram MTProto login through the existing UI. Folders/groups rendered and one manual group was selected. The first explicit manual sync showed:
`Telegram MTProto authorization is no longer valid`

Official Telegram Active Devices still shows the newly created Secretary MTProto session as active.

Previous M4AD was blocked before SSH authentication by a host-key mismatch. M4ADH has now re-established the canonical trust anchor:

Pinned ED25519 fingerprint:
`SHA256:VSSBeGqYXy8GGruKZhPJ2WZu8dP38i5ldE6FH+etoRs`

Three independent scans now consistently advertise the same ED25519 fingerprint; DNS is stable. The repository trust anchor must NOT be changed.

This task authorizes only a retry of the original sanitized read-only M4AD production diagnosis.

Do NOT re-authenticate, retry history sync, alter scope, deploy code, mutate production, or touch Telegram sessions.

## Production diagnostic authorization

Use only canonical production target and strict host-key verification from existing production tooling.

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
- ad-hoc Telegram/provider calls;
- direct Telethon connection/probe;
- decrypting/printing session content;
- Telegram logout/revoke;
- code changes;
- any host-key bypass.

Do not print account IDs, Telegram user IDs, peer IDs, phone, session ciphertext/plaintext, bearer tokens, credential key/API hash, provider references, IP addresses, or raw user content.

## Diagnostic questions

### 1. Persisted account state

Using read-only DB inspection, return booleans/counts only:
- exactly one MTProto account row exists for the affected Secretary user;
- session_encrypted is non-empty;
- account row freshness is consistent with the recent login;
- active auth challenge count;
- selected manual-group count;
- configured sync-folder count;
- active scope count.

Do NOT decrypt or print the session.

### 2. Recurring worker concurrency

Inspect:
- whether a Telegram recurring source-sync job exists;
- sanitized status: pending/running/failed;
- last run/failure relative to login/manual-sync attempt;
- sanitized failure category/class if persisted;
- whether configured folder/scope state could have caused reconcile_scope provider calls concurrently with manual sync.

Do not trigger/rearm jobs.

### 3. API/worker evidence

Inspect only the narrow time window around the latest MTProto auth/group-selection/manual-sync activity.

Return:
- route names/status codes for MTProto auth/groups/sync calls if present;
- normalized exception/error class names where available;
- whether manual sync returned authorization-invalid;
- whether worker independently observed authorization-invalid/provider-unavailable in the same window;
- whether any AUTH_KEY_DUPLICATED / AuthKeyDuplicatedError evidence exists;
- whether any AUTH_KEY_UNREGISTERED, SESSION_REVOKED, UnauthorizedError, or AuthKeyNotFound evidence exists.

Do not print raw exception payloads if they may contain identifiers.

### 4. Exact code-path audit at release SHA

Confirm:
- session_encrypted is written only by authorized-account save/update paths;
- discovery/history/worker do not overwrite it;
- group selection does not overwrite it;
- history sync decrypts the same stored account session;
- status endpoint is DB-only and can still render connected despite provider auth invalidity;
- fake/unit auth tests do not prove a real Telethon 2FA StringSession can be reopened later;
- whether AuthKeyDuplicatedError is explicitly classified; if not, identify the actual fallback path.

### 5. Classification

Do NOT repair or re-login.

Classify as:
A. provider authorization truly revoked/unregistered;
B. likely concurrent auth-key duplication;
C. stored-session persistence/corruption defect;
D. insufficient evidence.

If evidence is insufficient, propose the smallest separately-authorized next diagnostic/test.

## Completion report

Return:
- production ref/runtime and health;
- account/challenge/selection/scope booleans/counts;
- recurring job state;
- sanitized API/worker evidence;
- exact code-path conclusions;
- AuthKeyDuplicated evidence yes/no;
- classification A/B/C/D and why;
- confirmation strict pinned host-key verification passed;
- confirmation no Telegram/provider call was made by diagnostic;
- confirmation no session was decrypted/printed;
- confirmation no production mutation occurred.

Final marker:
`TELEGRAM_MTPROTO_M4AD_DIAGNOSIS_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
