# Current task — Telegram MTProto M4AE: human provider-backed discovery probe

## Status

M4ADH4R3 live read-only diagnosis completed successfully on approved diagnostic SHA
`ec4f51be6882433210d62ec6dbcfcdb19563be83`.

Live production facts:
- runtime/ref match expected release `8091736337689b68b4510126e74d9e409397f696`;
- Alembic `0046`;
- health/api/worker/db healthy/running;
- exactly one MTProto account;
- encrypted session non-empty;
- active auth challenges = 0;
- manual-selected groups = 1;
- configured folders = 0;
- active scope = 0;
- recurring Telegram job exists/pending/recent;
- recurring scope provider call possible = false;
- recurring history provider call possible = false;
- manual group sync route observed = true;
- manual group sync HTTP 409 = true;
- worker authorization-invalid/provider-unavailable evidence = false;
- requested AuthKeyDuplicated/AuthKeyUnregistered/SessionRevoked/Unauthorized/AuthKeyNotFound tokens = false.

Classification remains D / insufficient evidence.

Important release-code fact:
`TelethonMtprotoTransport.fetch_history()` maps both real authorization-loss conditions AND
`ValueError` / `TypeError` to
`TelegramMtprotoAuthorizationInvalidError("Telegram MTProto authorization is no longer valid")`.

Therefore the UI message does not yet prove Telegram revoked the session.

This task authorizes only **M4AE — one human UI provider-backed discovery probe using the existing connected session**.

## Human action

Do not use Executor for this task.

In the already-running exact-release preview client:

1. Navigate away from Account/Profile if currently open.
2. Re-open Account/Profile so `TelegramMtprotoAccountSection` is recreated and `_loadStatus()` runs.
3. Do not press:
   - Login / Get code;
   - Sync;
   - Apply Scope;
   - Save folders;
   - any group checkbox.
4. Wait until the Telegram MTProto section finishes loading.

Expected code path on connected status:
- GET status (DB-only);
- then `_loadScopeData()` issues:
  - GET folders (provider-backed discovery);
  - GET configured sync-folders (DB-only);
  - GET groups (provider-backed discovery).

The human should report only one of:

A. **DISCOVERY_PASS**
- connected identity shown;
- folders/groups populate normally;
- no red MTProto authorization error appears.

B. **DISCOVERY_AUTH_INVALID**
- red `Telegram MTProto authorization is no longer valid` appears while loading folders/groups.

C. **DISCOVERY_OTHER_ERROR**
- another error appears; provide screenshot/text, excluding secrets.

No other action is authorized.

## Interpretation

- DISCOVERY_PASS strongly proves the currently stored session can still reconnect and make Telegram read calls; this would make the earlier manual-sync 409 more likely to be fetch_history-specific/misclassified rather than a generally revoked session.
- DISCOVERY_AUTH_INVALID means the stored session currently fails even discovery and justifies a separately-authorized one-shot provider-auth diagnostic or controlled re-auth plan.
- DISCOVERY_OTHER_ERROR requires classification before further action.

No production mutation, no login, no sync, no scope change.

Final human report marker is one of:
`TELEGRAM_MTPROTO_M4AE_DISCOVERY_PASS`
`TELEGRAM_MTPROTO_M4AE_DISCOVERY_AUTH_INVALID`
`TELEGRAM_MTPROTO_M4AE_DISCOVERY_OTHER_ERROR`

`CURRENT_TASK.md` is the source of active authorization.
