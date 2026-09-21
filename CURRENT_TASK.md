# Current task — Telegram MTProto M4AW3: one human-shell Inbox eligibility probe

## Status

M4AW2 build/review is accepted at:
`1d25e033376b9a9215b02a9ef9b02946c9e82ae9`

Production runtime/ref remains:
`2db36510fe884eadc40d63fed8661ed3627f1cbb`

The normal Inbox UI showed no Telegram items after the manual-only visibility deploy.

The accepted read-only probe reports:
- imported MTProto objects;
- transport-visible objects;
- inbound/outbound split;
- canonical RecentSourceService Inbox-eligible count;
- first-page and first-50 Telegram counts.

## Authorization

Authorize exactly ONE live run from the proven HUMAN sandbox shell:

`ops/production/manual_mtproto_inbox_eligibility_probe.sh`

BREAK-GLASS READ-ONLY human-shell SSH is explicitly authorized for this one run.

Executor subprocess SSH is NOT authorized.

## Exact human command

```bash
cd ~/work/secretary-prerelease
git fetch origin
git checkout --detach origin/main
git rev-parse HEAD
bash ops/production/manual_mtproto_inbox_eligibility_probe.sh
```

The script takes NO arguments.

The local checkout may be current `origin/main`; the probe itself requires production runtime/ref exact:
`2db36510fe884eadc40d63fed8661ed3627f1cbb`

## One-shot rule

Run exactly once.

If remote execution starts and any stage fails:
- do not retry;
- paste the complete sanitized output;
- STOP.

## Strictly forbidden

Do NOT:
- construct TelegramClient;
- connect to Telegram/provider;
- click Sync;
- Apply Scope;
- change selections/folders;
- login/re-login;
- write/flush/commit DB;
- enqueue summaries/jobs;
- materialize/upsert;
- restart/recreate services;
- run migrations;
- edit production;
- enable MTProto AI;
- change Bot API.

## Required output

Paste the complete sanitized probe output.

Important fields:
- `IMPORTED_OBJECT_COUNT`
- `TRANSPORT_VISIBLE_COUNT`
- `INBOUND_COUNT`
- `OUTBOUND_COUNT`
- `INBOX_ELIGIBLE_COUNT`
- `FIRST_PAGE_TOTAL_COUNT`
- `FIRST_PAGE_TELEGRAM_COUNT`
- `FIRST_50_TELEGRAM_COUNT`
- `TELEGRAM_NETWORK_CALLS=0`
- terminal marker.

## Interpretation

- imported > 0, transport-visible = 0 => deployed transport visibility is not effective; STOP.
- transport-visible > 0, Inbox-eligible = 0 => Inbox filtering is removing the objects; diagnose from aggregate breakdown, no Sync.
- Inbox-eligible > 0, first-page Telegram = 0, first-50 > 0 => ordering/pagination, not transport visibility.
- first-page Telegram > 0 but UI still shows none => backend feed contains them; next task is client presentation/merge diagnosis.

Final marker after report:
`TELEGRAM_MTPROTO_M4AW3_INBOX_PROBE_COMPLETE`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
