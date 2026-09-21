# Current task — Telegram MTProto M4AX1: human paginated Inbox verification

## Status

M4AW3 read-only probe is complete and PASS.

Production runtime/ref:
`2db36510fe884eadc40d63fed8661ed3627f1cbb`

Observed:
- `IMPORTED_OBJECT_COUNT=228`
- `TRANSPORT_VISIBLE_COUNT=228`
- `INBOUND_COUNT=219`
- `OUTBOUND_COUNT=9`
- `INBOX_ELIGIBLE_COUNT=219`
- `FIRST_PAGE_TOTAL_COUNT=30`
- `FIRST_PAGE_TELEGRAM_COUNT=0`
- `FIRST_50_TELEGRAM_COUNT=0`
- `TELEGRAM_NETWORK_CALLS=0`

Conclusion:
- import is good;
- manual-only transport visibility is good;
- 219 Telegram messages are canonical Inbox-eligible;
- 9 outbound Telegram messages are intentionally suppressed from Inbox;
- Telegram items are simply older/lower in the global Inbox ordering than the first 50 items.

The persistent preview client implements cursor-based infinite loading and automatically calls `_loadMore()` near the bottom of the Inbox list.

## Goal

HUMAN UI ONLY.

Confirm that Telegram items appear after loading older Inbox pages.

## Procedure

1. Keep/open the normal Inbox in the persistent preview client.
2. Scroll downward through `Последние входящие`.
3. Continue approaching the bottom so the client can auto-load older pages.
4. Wait briefly whenever a loading spinner appears.
5. Continue until either:
   - Telegram items from the selected group appear; or
   - at least several additional pages have loaded and Telegram still does not appear.
6. If a Telegram item appears, open at most one if needed to verify ordinary presentation.

## Report

Return only:
- Telegram appeared: yes/no;
- approximate number of additional feed items/pages loaded before first Telegram item;
- whether one Telegram item opens normally, if opened;
- screenshot optional.

## Strictly forbidden

Do NOT:
- Sync;
- Apply Scope;
- login/re-login;
- change Telegram selections/folders;
- run provider probes;
- use production SSH;
- mutate production;
- enable AI;
- change Bot API.

If Telegram still does not appear after several older pages load, STOP. Do not Sync.

Final marker on success:
`TELEGRAM_MTPROTO_M4AX1_PAGINATED_INBOX_PASS`

`CURRENT_TASK.md` is the source of active authorization.
