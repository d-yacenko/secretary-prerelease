# Current task — Telegram MTProto M4BF1: human Inbox acceptance for folder-derived scope

## Status

M4BE2 post-deploy backend/runtime acceptance is PASS.

Production runtime/ref:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

Alembic:
`0046`

Confirmed production state:
- exactly one MTProto account;
- exactly one configured folder;
- active scope = 28 peers;
- all 28 are folder-only active peers;
- all 28 have a latest history cursor;
- all 28 have `history_complete=true`;
- backfill cursor present = 0;
- persisted history cutoff present = 0;
- folder-only active peers with >20 objects = 0;
- max active-peer object count = 20;
- MTProto embeddings/current provenance/pending-running embedding jobs = 0;
- Telegram network calls from the acceptance probe = 0;
- DB writes from the acceptance probe = 0.

## Goal

Human-confirm that folder-derived Telegram messages are visible through the normal Inbox UI.

This is the final UI acceptance step for the folder-derived shallow-bootstrap phase.

## Human action

Using the normal Secretary client:

1. Open the normal Inbox.
2. Do not enter Telegram account settings.
3. Do not press Sync.
4. Do not press Apply Scope.
5. Do not change folders or Telegram selection.
6. Scroll/load older Inbox pages if necessary, because Inbox is ordered together with all other sources.
7. Confirm whether Telegram items from the folder-derived scope are visible.

No specific Telegram chat/title/message content needs to be reported. A simple visible / not visible result is enough.

## Stop conditions

If Telegram items are visible:
- report PASS and STOP.

If no Telegram items are visible after reasonable Inbox pagination:
- report NOT VISIBLE and STOP;
- do not Sync, Apply Scope, re-login, alter folder config, or run any probe.

## Authorization

AUTHORIZED:
- normal read-only Inbox browsing/pagination in the client.

NOT AUTHORIZED:
- Sync;
- Apply Scope;
- Telegram account/folder changes;
- login/re-login;
- production SSH/probes;
- production mutation;
- deploy/rollback/ref changes;
- enabling MTProto AI;
- Bot API changes.

`CURRENT_TASK.md` is the source of active authorization.
