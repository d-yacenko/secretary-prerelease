# Current task — Telegram MTProto shallow folder bootstrap accepted: await deploy authorization

## Status

M4AY1 + M4AY1R + M4AY1R2 are accepted as the folder-scope shallow-bootstrap deploy candidate.

Candidate release:
`cbd5e7dbe5b8030a1ad100f97bcd2d12f9dccfaa`

Current production runtime/ref remains:
`2db36510fe884eadc40d63fed8661ed3627f1cbb`

Expected Alembic remains:
`0046`

No migration / no `0047`.

## Accepted semantics

Fresh folder-scope peer:
- `scope_active=true`;
- no `history_latest_message_id`;
- one newest-first provider fetch;
- limit exactly 20;
- no min/max history bounds;
- no historical second page, even with `has_more=true`;
- eligible entries materialize regardless of age;
- latest message ID advances from the provider page;
- no backfill cursor;
- history complete for backfill purposes;
- `history_cutoff_at` is not created or rewritten.

Existing folder-scope peer:
- incremental min-id only;
- no historical page;
- existing cutoff/backfill/completion state preserved.

Manual `sync_group`:
- existing 14-day bounded backfill unchanged.

Recurring:
- remains `scope_active=true` only.

AI:
- `TELEGRAM_MTPROTO_AI_ENABLED=false` remains the intended production quarantine;
- no Q1 policy change.

## Validation note

- 5 DB-independent policy tests PASS;
- 81 DB-backed tests collected but could not initialize because local executor `db` hostname is unavailable;
- Python compile PASS;
- Ruff PASS;
- `git diff --check` PASS.

The missing local PostgreSQL is recorded and does not authorize use of production DB for testing.

## Authorization state

NO production deploy is currently authorized.

Do NOT:
- move `production` ref;
- run `ops/production/deploy.py`;
- use production SSH;
- save/select Telegram folders live;
- preview scope live;
- Apply Scope live;
- run live Telegram Sync;
- login/re-login;
- enable MTProto AI;
- change Bot API;
- mutate production.

Await explicit human deployment authorization.

After a successful deploy, the intended acceptance sequence is separately authorized:
1. select one small Telegram folder;
2. save folder configuration;
3. preview scope and inspect breadth;
4. Apply Scope once;
5. allow bounded recurring/scope sync to bootstrap peers;
6. verify aggregate counts and Inbox visibility without deep history loading.

`CURRENT_TASK.md` is the source of active authorization.
