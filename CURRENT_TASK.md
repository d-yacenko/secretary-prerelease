# Current task — Telegram Bot API M4BJ1R: harden Stage B retirement harness

## Status

M4BJ1 implementation commit:
`31703dcef0f93443abe67d408fed26cd8430debe`

Architect review: NOT YET ACCEPTED FOR LIVE STAGE B.

Current production runtime/ref remains:
`fe151f12f64886505253e765b82458710a949e34`

Alembic:
`0046`

No Stage B production action has occurred.

## Accepted parts

The current harness already has the correct high-level retirement order:
1. production preflight;
2. one `deleteWebhook(drop_pending_updates=true)`;
3. one `getWebhookInfo` read-back;
4. clear only the four Bot env values;
5. recreate only API + worker;
6. verify DB/volume/non-Bot env/MTProto/AI/health/Alembic.

Secret output handling, atomic four-key mutation, and DB exclusion are directionally accepted.

## Required corrections

### 1. Fresh authoritative production ref before any provider mutation

The remote helper currently checks its local `origin/production` tracking ref without first fetching.

Before any Bot API call, it must:
- run a bounded `git fetch --prune origin` (or explicit `production` fetch);
- require fetched `origin/production` exact
  `fe151f12f64886505253e765b82458710a949e34`;
- require current HEAD exact same release;
- fail closed before provider work on any mismatch/fetch failure.

The local wrapper should also fetch both `main` and `production` and require local `origin/production` exact release before SSH.

### 2. target.json is the only production identity source

Remove duplicated concrete SSH target / port / host-key literals from
`retire_telegram_bot.sh`.

Use the committed `ops/production/target.json` as the single source, following the established `deploy.py` contract:
- validate required fields;
- validate canonical repository path/origin/health/compose files;
- validate port and fingerprint format;
- obtain ssh target/port/pin only from that file.

Do not add a second hard-coded copy of the current endpoint or fingerprint in the wrapper or tests.

Prefer factoring a small testable Python target loader if that keeps the shell wrapper simple.

### 3. Real destructive-ordering regression coverage

Add tests that exercise the `remote_main` control flow with all external effects mocked.

At minimum prove:

A. `deleteWebhook` failure:
- provider delete attempted exactly once;
- no read-back;
- no env mutation;
- no service recreation;
- sanitized failure stage;
- network call count = 1.

B. webhook read-back failure after successful delete:
- delete exactly once;
- read-back exactly once;
- no env mutation;
- no service recreation;
- sanitized failure stage;
- network call count = 2.

C. full provider success:
- delete occurs before read-back;
- read-back occurs before env mutation;
- env mutation occurs before API/worker recreation;
- recreation command contains only `api worker`, never `db`;
- no extra provider call/retry;
- terminal success has network call count = 2.

D. fresh production-ref fetch failure/mismatch:
- zero provider calls;
- zero env mutation;
- zero service recreation.

Tests must not depend on live DB, Docker, SSH, or provider access.

### 4. Preserve existing safety

Do not weaken:
- exact release `fe151f12f64886505253e765b82458710a949e34`;
- Alembic `0046`;
- four-key-only atomic env clearing;
- permissions preservation;
- neutralized non-Bot env equality proof;
- Bot token absent from subprocess argv/output;
- max two provider calls;
- no automatic webhook restore;
- no automatic Bot-secret restore after deliberate clear;
- DB container/volume invariants;
- MTProto credential preservation;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- sanitized output protocol.

## Validation

Run:
- focused retirement harness tests;
- local helper compile;
- bundled remote helper compile;
- Bash syntax;
- Ruff;
- `git diff --check`.

## Authorization

AUTHORIZED:
- local code/tests only for the M4BJ1 retirement harness;
- update `PROJECT_STATE.md`;
- commit and push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- Bot API/provider calls;
- webhook deletion;
- production env mutation;
- production service recreation;
- deploy/rollback/ref changes;
- deleting the bot account;
- Stage C cleanup;
- MTProto changes or AI enablement.

## Required report

Return:
- corrective commit SHA;
- files changed;
- exact fresh-ref correction;
- target.json single-source correction;
- destructive-ordering regression results;
- focused tests/compile/Ruff/diff-check results;
- production SSH=0;
- Bot API/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BJ1R_RETIREMENT_HARNESS_FIXED`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
