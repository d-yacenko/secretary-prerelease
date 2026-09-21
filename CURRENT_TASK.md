# Current task — Telegram MTProto visibility decision: await human scope choice

## Status

M4AT2R read-only visibility probe is complete and PASS.

Production runtime/ref:
`b7fbdc71584cfde042a998fbfefb06015175a205`

Observed persisted state:
- `MANUAL_SELECTED=true`
- `SCOPE_ACTIVE=false`
- `HISTORY_COMPLETE=true`
- `BACKFILL_CURSOR_PRESENT=false`
- `IMPORTED_OBJECT_COUNT=228`
- `ACTIVE_VISIBLE_OBJECT_COUNT=0`
- `TELEGRAM_NETWORK_CALLS=0`

Conclusion:
- Telegram history import succeeded and is complete for the selected group;
- 228 MTProto objects are persisted;
- none are eligible for normal Inbox/search/retrieval because the matching selection is not in active scope;
- this is expected under the current accepted transport visibility model: `manual_selected` and `scope_active` are independent.

## Important UI/product boundary

Do NOT press `Apply Scope` blindly.

Current `Apply Scope` reconciles the folder-derived dynamic scope. It does not mean "activate the one manually-selected group only".

If zero folders are configured, applying that scope will not activate the manual-only group.

If folders are configured, applying scope may activate multiple dialogs from those folders.

Therefore the next action requires an explicit human product choice:

1. Keep visibility bounded to exactly the one manually-selected group.
   - This requires a separately authorized product/semantics change because the current accepted read gate does not expose manual-only selections in Inbox.

2. Use the existing folder-derived scope.
   - Human selects/saves desired Telegram folders, previews the resulting scope, reviews its breadth, and only then separately authorizes `Apply Scope`.

## Authorization state

No further Telegram/provider action is currently authorized.

Do NOT:
- Sync again;
- Apply Scope;
- change folders/selections;
- login/re-login;
- run provider probes;
- mutate production.

Await explicit human choice: exact manual group visibility vs folder-derived scope.

`CURRENT_TASK.md` is the source of active authorization.
