# Current task — Telegram MTProto M4AW1: human Inbox visibility verification

## Status

M4AV1 production deploy is complete and PASS.

Production release/runtime/ref:
`2db36510fe884eadc40d63fed8661ed3627f1cbb`

Production verification:
- health PASS;
- Alembic `0046`;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- API recreated;
- worker recreated;
- no migration / no `0047`.

Known persisted Telegram state before this deploy:
- exactly one manually selected group;
- `manual_selected=true`;
- `scope_active=false`;
- `history_complete=true`;
- `backfill_cursor_present=false`;
- 228 imported MTProto objects.

The deployed backend now makes a correctly owned MTProto object ordinarily visible when:

`manual_selected=true OR scope_active=true`

No Sync or Apply Scope is needed for this verification.

## Goal

Verify through the existing Secretary UI that already-imported Telegram messages from the manually-selected group now appear in the normal Inbox.

This task is HUMAN UI ONLY.

## Procedure

1. Use the persistent Secretary preview client already established for this production account.
2. Open/reload the normal Inbox.
3. If the Inbox was already open before deploy, perform only the ordinary UI refresh/navigation needed to reload the feed.
4. Look for Telegram entries from the selected manual group.
5. Open at most one visible Telegram item if needed to confirm it is the expected source/group.
6. Report only safe user-visible facts:
   - whether Telegram items are visible in Inbox;
   - approximate visible count on the current page, if obvious;
   - whether opening one item shows normal content/presentation.

## Strictly forbidden

Do NOT:
- click Telegram Sync;
- Apply Scope;
- change folders/selections;
- login/re-login;
- run provider probes;
- use production SSH;
- mutate production;
- enable MTProto AI;
- change Bot API.

Do not report Telegram/account/group/message numeric IDs.

## Interpretation

- Telegram items visible in normal Inbox => manual-only ordinary visibility is production-verified.
- No Telegram items visible => do not Sync or Apply Scope; capture the Inbox screenshot/state and STOP for read-only diagnosis.

Final marker after successful verification:

`TELEGRAM_MTPROTO_M4AW1_INBOX_VISIBILITY_PASS`

`CURRENT_TASK.md` is the source of active authorization.
