# Current task — Telegram MTProto M4AI1: fix read-path error taxonomy

## Status

M4AH3 live first-page probe: PASS.

Confirmed on exact diagnostic SHA:
`2b9b8d3d7f19f2174808ecdadfd4bddc148aa5e9`

Evidence:
- strict pinned SSH PASS;
- exactly one MTProto account/manual-selected group;
- session decrypt/StringSession parse/reference decrypt/reference parse/peer-match/client construct all PASS;
- one connect PASS;
- one live authorization check returned true;
- one `iter_messages(input_peer, limit=100, reverse=False)`;
- 100 messages seen;
- 100 exact `_history_entry_from_message()` conversions succeeded;
- ENTRIES_NONE=0;
- no login/write/discovery/materialization/production mutation.

Therefore the earlier manual group Sync HTTP 409 surfaced as
`Telegram MTProto authorization is no longer valid`
is NOT evidence of a currently invalid stored session.

Exact release defect:
`TelethonMtprotoTransport.fetch_history()` and discovery code broadly map
`ValueError` / `TypeError` to `TelegramMtprotoAuthorizationInvalidError`.

This task authorizes only implementation + tests + review branch push.

NO production deploy/run is authorized.

## Goal

Make MTProto read-path error taxonomy truthful:

- only real auth-key/session invalidation errors become authorization-invalid;
- non-auth `ValueError` / `TypeError` from read/discovery/history paths become provider-unavailable or a more specific existing non-auth error;
- API 503 wording must be provider-neutral, not "authorization provider", because the same response helper is used for history/discovery.

## Branch / base

Create a new review branch from current main.

Preferred:
`review/telegram-mtproto-m4ai`

Do not modify production.

## Required code changes

### 1. fetch_history()

In:
`backend/app/connectors/telegram/mtproto_transport.py`

Preserve auth-invalid mapping ONLY for genuine auth/session exceptions already explicitly enumerated, such as:
- `AuthKeyNotFound`
- `AuthKeyUnregisteredError`
- `SessionRevokedError`
- `UnauthorizedError`
- `UserDeactivatedBanError`
- `UserDeactivatedError`

Review whether `AuthKeyError` itself should also be explicitly included for read paths, based on existing Telethon usage in the repo and exception hierarchy. Do not guess silently: add a test-backed choice.

Remove broad:
`except (ValueError, TypeError) -> TelegramMtprotoAuthorizationInvalidError`

For non-auth `ValueError` / `TypeError` in `fetch_history()`, map to:
`TelegramMtprotoProviderUnavailableError("Telegram history provider is temporarily unavailable")`

Preserve:
- provider-reference invalid application errors;
- group unavailable mapping;
- FloodWait mapping;
- existing TelegramMtprotoError passthrough.

### 2. discovery read paths

Audit `discover_groups()`, `discover_folders()`, and any other provider-backed read/discovery method in the same transport for the same broad `ValueError/TypeError -> authorization-invalid` pattern.

Where present:
- genuine auth/session exceptions remain authorization-invalid;
- non-auth ValueError/TypeError become provider-unavailable;
- do not change login/code/password semantics.

### 3. API provider error wording

In:
`backend/app/api/telegram_mtproto.py`

Current shared provider 503 detail is:
`Telegram authorization provider is temporarily unavailable`

Change it to provider-neutral wording suitable for auth, discovery, and history, e.g.:
`Telegram provider is temporarily unavailable`

Preserve:
- status 503;
- Retry-After behavior.

### 4. No behavior expansion

Do NOT:
- change DB schema;
- add migration;
- change sync limits/page sizes;
- change scope behavior;
- change AI quarantine;
- change Bot API;
- change mutation/write error semantics unless a failing regression proves necessary;
- alter login flow;
- alter session persistence;
- add retries;
- deploy.

## Required tests

Add focused regression tests proving at least:

1. fetch_history genuine auth exception -> TelegramMtprotoAuthorizationInvalidError;
2. fetch_history ValueError -> TelegramMtprotoProviderUnavailableError;
3. fetch_history TypeError -> TelegramMtprotoProviderUnavailableError;
4. fetch_history provider-reference invalid remains provider-reference invalid;
5. fetch_history group/private peer errors remain group-unavailable;
6. fetch_history FloodWait remains provider-unavailable with retry semantics;
7. discover_groups genuine auth exception -> auth-invalid;
8. discover_groups ValueError/TypeError -> provider-unavailable;
9. discover_folders equivalent coverage if it contains the same broad mapping;
10. API provider response remains HTTP 503;
11. API provider detail is provider-neutral;
12. Retry-After preserved;
13. no change to auth start/code/password invalid-code/password behavior;
14. no schema/migration changes;
15. existing Telegram MTProto focused suites remain passing.

If practical, add a regression directly matching the original symptom:
- a ValueError arising after authorization in history path must NOT produce HTTP 409 auth-invalid;
- it should surface through provider-unavailable/503 path.

## Verification

Run:
- focused pytest covering modified MTProto transport/API tests;
- existing Telegram MTProto suites relevant to A1/A2/A3/C2;
- Ruff on changed Python files;
- `git diff --check`.

## Review handoff

After implementation:
- commit on `review/telegram-mtproto-m4ai`;
- push only that review branch;
- do NOT deploy;
- report:
  - full SHA;
  - tests count/pass;
  - Ruff;
  - diff-check;
  - exact exception-taxonomy changes;
  - whether AuthKeyError was included and why;
  - remaining gaps.

Final marker:
`TELEGRAM_MTPROTO_M4AI1_REVIEW_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
