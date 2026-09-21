# Current task — Telegram MTProto M4BB3 complete: await M4BB1 deploy authorization

## Status

M4BB3 read-only wide preview is complete and PASS.

Current production runtime/ref:
`cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`

Alembic:
`0046`

M4BB1 accepted deploy candidate:
`c69d2353c19c4958e1fb60aac69466fcf6ac1482`

## Complete preview evidence

One configured folder, muted exclusion enabled:

- `DIALOGS_SCANNED_RETAINED=649`
- `SCOPE_MATCH_COUNT=28`
- `SKIPPED_BROADCAST=15`
- `SKIPPED_BOT=21`
- `SKIPPED_UNSUPPORTED=67`
- `SKIPPED_OTHER=0`
- `TRUNCATED=false`
- `TELEGRAM_NETWORK_CALLS=6`

Interpretation:
- the current account dialog universe is complete below the new 2000 bound;
- the selected folder's complete derived scope is 28 peers;
- the earlier 500-dialog truncation was a boundary artifact;
- the complete 649-dialog scan still yields exactly the same 28 scope peers seen in the old partial preview.

No Apply Scope, no Sync, no reconciliation, no history/message fetch, and no DB mutation occurred in M4BB3.

## Important recurring behavior

Existing recurring MTProto sync calls `reconcile_scope()` before each recurring history pass.

Therefore after M4BB1 is deployed, the already-saved one-folder configuration may become active automatically on the next recurring run; pressing "Применить область" is not required for eventual activation under the current recurring design.

Because the full preview has already proven the exact complete scope breadth (28 peers), this activation is now bounded/known rather than surprising.

## Authorization state

NO deploy is currently authorized.

Do NOT:
- move `production` ref;
- deploy M4BB1;
- click Apply Scope;
- click Sync;
- change folder configuration;
- login/re-login;
- use production SSH;
- mutate production;
- enable MTProto AI;
- change Bot API.

Await explicit human deployment authorization.

If authorized, deploy schema-neutral candidate:
- release `c69d2353c19c4958e1fb60aac69466fcf6ac1482`
- rollback `cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`
- expected Alembic `0046`
- canonical `ops/production/deploy.py` only.

After successful deploy, acceptance should verify:
1. scope becomes active for the expected 28 peers (whether via recurring reconciliation or one explicit Apply Scope, depending on observed timing);
2. fresh peers receive shallow bootstrap only (one newest-first page, max 20 provider entries each);
3. no deep historical backfill is introduced;
4. Inbox begins showing folder-derived Telegram items;
5. no AI/embedding activity from MTProto while the production flag remains disabled.

`CURRENT_TASK.md` is the source of active authorization.
