# Current task — Telegram Bot API M4BX1: execute one-shot live read-only Stage 2 diagnostic

## Status

Human explicitly authorized one live read-only Stage 2 diagnostic run.

Accepted diagnostic verifier commit:
`65309f1060990e5cb3ca639a0a1d7eb699a07881`

Current production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Expected Alembic:
`0046`

## Authorization

Authorize exactly ONE execution of:

`bash ops/production/verify_telegram_bot_stage_c.sh`

## Purpose

Identify the exact Stage 2 cause through one fixed sanitized code, or complete success.

Expected possible Stage 2 codes:
- `STAGE_2_BOOTSTRAP`
- `STAGE_2_LEGACY_ROUTES`
- `STAGE_2_MTPROTO_ROUTE`
- `STAGE_2_BOT_SETTINGS`
- `STAGE_2_DB_SESSION`
- `STAGE_2_ACCOUNT`
- `STAGE_2_SCOPE`
- `STAGE_2_LEGACY_AGGREGATE`
- `STAGE_2_LEGACY_CANDIDATES`
- `STAGE_2_INBOX_READ`
- `STAGE_2_CANDIDATE_BOUND`
- `STAGE_2_CHILD_PROTOCOL`
- `STAGE_2_CHILD_EXECUTION`

If the verifier succeeds, return the normal full success protocol.

## Hard prohibitions

Must remain:
- Telegram/provider calls = 0;
- DB writes = 0;
- env writes = 0;
- service restarts/recreates = 0;
- deploy/ref movement = 0;
- no SQL, exception messages, IDs, account/peer/message identifiers, titles, bodies, or env values emitted.

## Failure handling

If verifier fails or blocks:
- do not retry;
- do not bypass;
- do not use direct SSH;
- do not restart/recreate services;
- do not modify DB/env;
- return complete sanitized output and STOP.

A valid remote verifier failure must not be relabeled as `ssh_failed`.

## Required report

Return the complete sanitized stdout exactly as produced.

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
