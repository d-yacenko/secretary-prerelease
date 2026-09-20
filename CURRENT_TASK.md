# Current task — Telegram MTProto M4AJR: promote production ref then deploy exact candidate

## Status

Initial M4AJ deployment attempt was correctly BLOCKED before production mutation.

Observed:
- `origin/production` is still:
  `8091736337689b68b4510126e74d9e409397f696`
- accepted release candidate is:
  `23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Exact deploy contract in `ops/production/remote_deploy.py` requires:
`origin/production == --release-sha`
before any production checkout/build/recreate is allowed.

Therefore the correct workflow is:

1. explicitly promote `origin/production` to the exact accepted candidate;
2. run the normal pinned deploy harness unchanged.

No deploy harness bypass or manual remote checkout is authorized.

## Accepted release

Release SHA:
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Current/rollback production SHA:
`8091736337689b68b4510126e74d9e409397f696`

Expected Alembic:
`0046`

## Phase 1 — production ref promotion

This task explicitly authorizes one GitHub ref update:

`origin/production`:
from
`8091736337689b68b4510126e74d9e409397f696`
to
`23fa07df213d5a70a6dc1d3c8b32af39228107eb`

Requirements:

- verify current `origin/production` is exactly rollback SHA before update;
- verify release SHA exists and is an ancestor/reachable accepted candidate;
- update ONLY branch `production`;
- exact target SHA only;
- no force to any other SHA;
- do not move `main`;
- no tags;
- no file edits for the promotion itself.

If current production ref is not exactly expected rollback SHA:
STOP.

After update verify:
`origin/production == 23fa07df213d5a70a6dc1d3c8b32af39228107eb`

If promotion fails:
STOP. Do not deploy.

## Phase 2 — normal deploy harness

Only after exact production-ref promotion PASS, run the existing normal deployment harness unchanged:

`python3 ops/production/deploy.py --release-sha 23fa07df213d5a70a6dc1d3c8b32af39228107eb --rollback-sha 8091736337689b68b4510126e74d9e409397f696 --expected-alembic 0046`

Do not edit deploy.py or remote_deploy.py.

## Preflight expected by harness

The harness must verify:

- canonical local checkout;
- clean local main;
- local main == origin/main;
- canonical target.json;
- pinned production SSH host key;
- schema-neutral release;
- production repo clean;
- production origin correct;
- origin/production == exact release;
- current production HEAD is rollback or release SHA;
- db/api/worker present and healthy/running;
- production health PASS;
- DB volume identity captured;
- .env hash captured;
- API/worker required env and credential key consistent;
- DB TCP auth PASS;
- Alembic 0046.

If harness blocks:
STOP and report exact sanitized reason.

## Authorized production mutations

Only the existing deploy harness may:

- switch production checkout to exact release SHA;
- build api + worker;
- recreate api + worker;
- leave DB container/volume untouched.

No migration action beyond verifying 0046.

## Strictly forbidden

Do NOT:

- manually SSH and bypass deploy.py;
- manually git switch production outside harness;
- deploy any SHA other than accepted release;
- change DB/schema;
- run migration 0047;
- recreate/delete DB/volume;
- edit .env;
- change credential key;
- login/re-login Telegram;
- submit Telegram code/password;
- run Telegram manual Sync/history import;
- Apply Scope;
- change groups/folders;
- enable MTProto AI;
- change/retire Bot API;
- change target.json or SSH trust;
- change deploy.py/remote_deploy.py during this task;
- perform unrelated cleanup.

## Rollback semantics

If rollout fails after service recreation, use the harness's built-in rollback to:
`8091736337689b68b4510126e74d9e409397f696`

Additionally, if runtime rollback occurs, restore GitHub `origin/production` back to rollback SHA only after confirming runtime rollback succeeded.

If rollout fails before production mutation but after production-ref promotion:
- restore `origin/production` to rollback SHA;
- report no runtime mutation.

Do not leave GitHub production ref pointing at release when runtime is confirmed rolled back.

## Required report

### Promotion
- old origin/production SHA;
- new origin/production SHA;
- exact promotion PASS/FAIL.

### Deploy transport/preflight
- target/pin;
- SSH;
- production old HEAD;
- worktree;
- services/DB;
- health;
- Alembic.

### Rollout
- exact release HEAD;
- API recreated;
- worker recreated;
- DB container unchanged;
- DB volume unchanged;
- env unchanged;
- migration action none.

### Final consistency
- origin/production SHA;
- production runtime/ref SHA;
- health;
- Alembic;
- AI flag preserved;
- Bot API untouched;
- Telegram login/history actions none.

If rollback:
- failure reason;
- runtime rollback PASS/FAIL;
- production ref restored PASS/FAIL;
- final SHA.

Final marker:
`TELEGRAM_MTPROTO_M4AJR_DEPLOY_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
