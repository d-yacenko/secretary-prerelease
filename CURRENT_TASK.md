# Current task — Telegram MTProto M4AR1: one human manual Sync after bound-normalization deploy

## Status

Production deploy M4AQ1 is complete and PASS.

Production runtime/ref:
`b7fbdc71584cfde042a998fbfefb06015175a205`

Alembic:
`0046`

Runtime invariants:
- API/worker recreated and healthy;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- Bot API untouched;
- stored Telegram MTProto session and selection state preserved by deploy.

The deployed fix normalizes absent Telethon history bounds:
- `min_message_id=None -> min_id=0`
- `max_message_id=None -> max_id=0`

M4AO2 previously proved the old runtime failed before the first message at:
- `STAGE_3_PAGE1_ITERATION`
- `RAW_EXCEPTION_CLASS=TypeError`
- seen/converted = 0/0
after connect and authorization PASS.

## Goal

Perform exactly ONE human-controlled manual Sync of the already-selected Telegram group through the existing Secretary UI.

This task is HUMAN UI ONLY.

No Executor production SSH or provider probe is authorized.

## Human procedure

Use the existing fresh/persistent Secretary client already connected to the production backend.

1. Open Account / Telegram MTProto controls.
2. Confirm the existing account still appears connected.
3. Confirm the previously manually-selected group is still selected.
4. Do NOT Apply Scope.
5. Press Sync exactly once for that already-selected group.
6. Wait for the UI result.
7. Capture the exact sanitized outcome:
   - success indication / imported-count summary if shown; or
   - exact user-facing error text/status.
8. Then STOP.

## One-shot rule

Exactly one Sync click is authorized.

If it errors:
- do not retry;
- do not log out/re-login;
- do not re-enter code/password;
- do not Apply Scope;
- do not change selection;
- do not refresh/discover folders/groups as a workaround.

If the UI itself refreshes status automatically as part of normal rendering, that is acceptable; do not manually trigger unrelated discovery actions.

## Strictly forbidden

Do NOT:
- run the human-shell provider probe again;
- run application/provider diagnostics before seeing the Sync result;
- use Executor SSH;
- use manual production SSH/Compose;
- mutate production;
- run migrations;
- enable MTProto AI;
- change Bot API;
- change Telegram scope/selections;
- perform a second Sync.

## Required report

Return only the human-observed sanitized result:
- account connected status: yes/no;
- selected group still present: yes/no;
- Sync clicked: exactly once;
- final UI success/error text;
- any visible aggregate count/status that contains no IDs/content/secrets.

Do not include:
- message contents;
- account/group/peer IDs;
- session/reference values;
- Telegram credentials.

Final marker after reporting:
`TELEGRAM_MTPROTO_M4AR1_HUMAN_SYNC_COMPLETE`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
