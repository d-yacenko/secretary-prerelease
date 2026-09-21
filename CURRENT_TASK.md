# Current task — Telegram MTProto M4BB3: one human-shell 2000+1 scope preview

## Status

M4BB2R probe is accepted at:
`d923db98f77fb1e389455b13b5c3bc84f83173ba`

Production runtime/ref remains:
`cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`

Alembic:
`0046`

Exactly one configured Telegram folder is already saved from the UI. The old runtime remains fail-closed on the 500-dialog preview boundary.

## Authorization

Authorize exactly ONE live run from the proven HUMAN sandbox shell:

`ops/production/manual_mtproto_scope_preview_2000_probe.sh`

BREAK-GLASS READ-ONLY human-shell SSH is explicitly authorized for this one run.

Executor subprocess SSH is NOT authorized.

This run is allowed to perform only the read-only provider operations embedded in the accepted probe:
- folder definition read;
- authorization checks;
- bounded dialog iteration up to 2001.

No scope reconciliation and no history/message fetch.

## Exact human command

```bash
cd ~/work/secretary-prerelease
git fetch origin
git checkout --detach origin/main
git rev-parse HEAD
bash ops/production/manual_mtproto_scope_preview_2000_probe.sh
```

The script takes no arguments.

## One-shot rule

Run exactly once.

If remote/provider execution starts and any stage fails:
- do not retry;
- paste the complete sanitized output;
- STOP.

## Strictly forbidden

Do NOT:
- click Apply Scope;
- click Sync;
- change folder configuration;
- login/re-login;
- call reconcile_scope manually;
- fetch history/messages;
- deploy M4BB1;
- move production ref;
- mutate production;
- restart/recreate containers;
- migrate;
- enable MTProto AI;
- change Bot API.

## Required output

Paste the complete sanitized output.

Important fields:
- `ACCOUNT_EXACTLY_ONE`
- `CONFIGURED_FOLDER_EXACTLY_ONE`
- `IGNORE_MUTED`
- `DIALOGS_SCANNED_RETAINED`
- `SCOPE_MATCH_COUNT`
- `SKIPPED_BROADCAST`
- `SKIPPED_BOT`
- `SKIPPED_UNSUPPORTED`
- `SKIPPED_OTHER`
- `TRUNCATED`
- `TELEGRAM_NETWORK_CALLS`
- terminal marker.

## Interpretation

- `TRUNCATED=false` and a reasonable scope count -> complete safe preview; next phase may deploy M4BB1.
- `TRUNCATED=true` -> even the 2000-dialog bound is incomplete; do not deploy/activate yet.
- provider/auth failure -> stop; do not relogin or retry without new authorization.

Final marker after report:
`TELEGRAM_MTPROTO_M4BB3_SCOPE_PREVIEW_COMPLETE`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
