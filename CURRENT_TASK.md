# Current task — Telegram Bot API M4BX1: one-shot live read-only Stage 2 diagnostic awaiting explicit authorization

## Status

M4BW1 Stage 2 diagnostic hardening is ARCHITECT ACCEPTED.

Accepted diagnostic commit:
`65309f1060990e5cb3ca639a0a1d7eb699a07881`

Current production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Expected Alembic:
`0046`

The previous M4BV1 live run safely reached Stage 2 and failed with the undifferentiated legacy code `STAGE_2_READ_ONLY_STATE`. All Stage 0/1 checks passed and all provider/write/recreate counters were zero.

## Authorization state

ONE LIVE READ-ONLY STAGE 2 DIAGNOSTIC RUN IS NOT YET AUTHORIZED.

Acceptable explicit authorization text:

`Разрешаю live read-only Stage 2 diagnostic M4BX1`

After explicit authorization, execute exactly once:

`bash ops/production/verify_telegram_bot_stage_c.sh`

## Purpose

This run exists only to identify the exact read-only Stage 2 cause through one of the fixed sanitized stages:

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

If all checks pass, the verifier may instead complete with the existing success protocol.

## Read-only guarantees

Must remain:
- Telegram/provider calls = 0;
- DB writes = 0;
- env writes = 0;
- service restart/recreate = 0;
- deploy/ref movement = 0;
- no identifiers/content/SQL/exception messages emitted.

## Failure handling

If verifier fails or blocks:
- do not retry;
- do not bypass;
- do not use direct SSH;
- do not restart/recreate services;
- do not modify DB/env;
- return the complete sanitized output and STOP.

A valid remote verifier failure must not be relabeled as `ssh_failed`.

`CURRENT_TASK.md` is the source of active authorization.
