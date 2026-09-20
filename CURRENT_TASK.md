# Current task — Telegram MTProto M4AL1: sanitized read-only log inspection after M4AK

## Status

M4AK human Sync was performed exactly once on production runtime:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Visible result:
`Telegram provider is temporarily unavailable`

After reopening Account settings:
- connected account remained visible;
- folders/groups continued to load;
- no authorization-invalid banner remained.

No retry/re-login/Apply Scope/group-folder change occurred.

This task authorizes a zero-provider-call, read-only production log inspection only.

## Goal

Determine whether the single M4AK request left any sanitized evidence that narrows the failure:
- HTTP status;
- known MTProto exception class name;
- history/provider stage indication;
- API vs worker origin.

Do not make any Telegram provider calls.

## Authorization mode

BREAK-GLASS READ-ONLY SSH is explicitly authorized for this task because normal deploy tooling does not expose logs.

Use ONLY the canonical target from:
`ops/production/target.json`

Use strict pinned ED25519 verification exactly as in the accepted production diagnostics:
- BatchMode=yes
- StrictHostKeyChecking=yes
- temporary UserKnownHostsFile containing only the verified pinned host key
- GlobalKnownHostsFile=/dev/null

No host discovery/fallback/alternative target.

## Preconditions

Verify locally:
- clean checkout;
- current main == origin/main;
- origin/production == `23fa07df213d5a70a6dc1d3c8b32af39228107eb`;
- target.json unchanged.

On remote, before reading logs:
- production HEAD == `23fa07df213d5a70a6dc1d3c8b32af39228107eb`;
- worktree clean;
- api/worker/db running;
- Alembic 0046.

If any guard fails: STOP.

## Allowed remote operations

Read-only only:
- `git rev-parse`, `git status`;
- `docker compose ps`;
- `docker compose logs` for api/worker;
- read-only health/Alembic checks.

Inspect only a narrow recent window sufficient to include the one M4AK click, preferably last 30 minutes.

Do not print raw logs to the user/report.

## Sanitized parsing

Server-side/local parser may inspect raw logs transiently but must emit ONLY aggregate/sanitized facts.

Allowed output fields:

- `M4AK_ROUTE_SEEN=true|false`
- `M4AK_HTTP_503_COUNT=<bounded integer>`
- `M4AK_HTTP_409_COUNT=<bounded integer>`
- `API_EXCEPTION_CLASS=<allowlisted class token|none>`
- `WORKER_EXCEPTION_CLASS=<allowlisted class token|none>`
- `AUTH_INVALID_EVIDENCE=true|false`
- `PROVIDER_UNAVAILABLE_EVIDENCE=true|false`
- `VALUE_ERROR_EVIDENCE=true|false`
- `TYPE_ERROR_EVIDENCE=true|false`
- `FLOOD_WAIT_EVIDENCE=true|false`
- `AUTH_KEY_EVIDENCE=true|false`
- `SESSION_REVOKED_EVIDENCE=true|false`
- `UNAUTHORIZED_EVIDENCE=true|false`
- `RAW_TRACEBACK_PRESENT=true|false`
- `TELEGRAM_NETWORK_CALLS=0`

Known allowlisted exception class tokens may include only:
- ValueError
- TypeError
- FloodWaitError
- AuthKeyError
- AuthKeyNotFound
- AuthKeyUnregisteredError
- SessionRevokedError
- UnauthorizedError
- TelegramMtprotoProviderUnavailableError
- TelegramMtprotoAuthorizationInvalidError
- none

If another exception class appears, emit:
`API_EXCEPTION_CLASS=OTHER`
or
`WORKER_EXCEPTION_CLASS=OTHER`
without message text.

Do NOT emit:
- peer/group IDs;
- Telegram user ID/username/display name;
- message IDs/content;
- session/reference;
- request bodies;
- tokens/cookies/headers;
- DB IDs;
- raw log lines;
- exception messages/tracebacks.

## Forbidden

Do NOT:
- call Telegram;
- retry Sync;
- use application fetch_history;
- run diagnostic provider probes;
- re-login;
- Apply Scope;
- mutate DB;
- mutate files/env;
- restart/recreate services;
- change refs;
- change SSH trust;
- run migrations;
- enable AI;
- touch Bot API.

## Interpretation

A. ValueError/TypeError evidence
=> taxonomy fix is working and root class is non-auth. Next task should reproduce the exact second-page/history stage read-only.

B. FloodWait evidence
=> provider throttling/transient; no re-login. Decide on retry/backoff UX separately.

C. AuthKey/SessionRevoked/Unauthorized evidence
=> genuine auth signal; stop before any re-login and review exact evidence.

D. Only route 503/provider-unavailable, no root class
=> logs are insufficient. Next task is one narrow second-page read-only probe.

E. No route evidence
=> do not retry Sync. Report log visibility gap; next diagnostic still requires explicit authorization.

## Required report

Return only:
- preflight guards;
- sanitized fields above;
- production unchanged;
- provider calls = 0.

Final marker:
`TELEGRAM_MTPROTO_M4AL1_LOG_REVIEW_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
