# Current task — Telegram MTProto M4AX1 complete: await next product authorization

## Status

M4AX1 human paginated Inbox verification is PASS.

Production runtime/ref:
`2db36510fe884eadc40d63fed8661ed3627f1cbb`

Verified end-to-end:
- Telegram MTProto history import persisted successfully;
- 228 imported objects exist for the selected group;
- 219 inbound objects are canonical Inbox-eligible;
- manual-selected objects are ordinarily visible without `Apply Scope`;
- older Telegram items appear through normal Inbox cursor pagination;
- client presentation is working.

No additional Sync or Apply Scope was required.

## Remaining product follow-up

Previously recorded preference for future folder-derived onboarding:
- do not deep-backfill months/history for every newly activated chat;
- bootstrap only a shallow recent window, roughly 10–20 latest messages per chat;
- after bootstrap, continue incremental new-message sync.

This follow-up is NOT currently authorized for implementation.

Also unchanged:
- recurring MTProto sync still follows `scope_active=true` only;
- manual-only visibility does not itself enable recurring sync;
- production `TELEGRAM_MTPROTO_AI_ENABLED=false` policy remains the intended quarantine;
- no migration / no `0047`;
- Bot API untouched.

## Authorization state

No additional Telegram/provider or production action is currently authorized.

Do NOT:
- Sync;
- Apply Scope;
- change folders/selections;
- login/re-login;
- deploy or mutate production;
- change AI flag;
- change Bot API.

Await explicit human selection of the next product task.

`CURRENT_TASK.md` is the source of active authorization.
