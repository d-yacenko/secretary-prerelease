# Current task — Telegram Bot API M4BJ1: build fail-closed Stage B retirement harness

## Status

M4BI1 Stage A backend production deploy is COMPLETE / PASS.

Current production runtime/ref:
`fe151f12f64886505253e765b82458710a949e34`

Alembic:
`0046`

Stage A live behavior:
- legacy `POST /telegram/link` is retired;
- legacy Bot webhook ingress is retired;
- Bot-derived send/reply is retired;
- MTProto remains the live Telegram transport;
- historical Bot-derived objects/tables remain preserved.

Human product direction remains:
- no cross-transport deduplication;
- Bot API will be retired and later destroyed;
- historical Bot-derived objects are retained.

## Goal

Build and locally verify a dedicated, fail-closed production harness for Stage B retirement.

This task is CODE/TEST ONLY.

Do NOT execute the harness against production in this task.

## Intended future Stage B live behavior

A later separately-authorized one-shot run must:

1. verify exact production target/host pin/repository/ref/worktree/health/Alembic;
2. verify current runtime is exact `fe151f12f64886505253e765b82458710a949e34`;
3. verify DB/API/worker preflight and preserve DB container + volume;
4. verify Bot credentials are currently available without printing values;
5. verify MTProto credentials/capability state before mutation without printing values;
6. call Telegram Bot API `deleteWebhook` exactly once with pending Bot updates dropped;
7. verify webhook deletion through a bounded read-back such as `getWebhookInfo`, emitting only sanitized booleans/count-free facts;
8. clear only these four production Bot settings:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_BOT_USERNAME`
   - `TELEGRAM_WEBHOOK_SECRET`
   - `TELEGRAM_WEBHOOK_URL`
9. recreate only API + worker so retired Bot secrets are removed from running container environments;
10. prove DB container unchanged;
11. prove DB volume unchanged;
12. prove no non-Bot `.env` setting changed;
13. prove the four Bot settings resolve empty in API + worker;
14. prove `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` remain present/equal for API + worker;
15. prove `SECRETARY_CREDENTIAL_KEY` and DB credential invariants remain intact without printing values;
16. prove `TELEGRAM_MTPROTO_AI_ENABLED=false`;
17. prove health PASS and Alembic exact `0046`.

This harness does NOT delete the Telegram bot account itself. Final BotFather/account destruction is a later human step after Stage B is production-accepted.

## Required implementation shape

Prefer the established production harness pattern:

- local entrypoint under `ops/production/`, e.g. `retire_telegram_bot.py`;
- streamed remote helper under `ops/production/`;
- committed `target.json` only;
- canonical origin/path checks;
- strict pinned SSH host-key verification;
- no direct ad-hoc SSH;
- no secret values in argv, stdout, stderr, logs, temp files, Git, or test snapshots.

The provider call must not put the Bot token in a shell/process command line. Use an in-process HTTP client/stdlib mechanism or equivalent that keeps the token out of argv and sanitizes all failures.

## Environment mutation contract

Do not delete or rewrite arbitrary `.env` content.

The helper must:
- require exactly one assignment for each of the four Bot keys before mutation;
- atomically clear their values while preserving all other file content/settings;
- preserve file permissions;
- compare a redacted/neutralized before-vs-after representation to prove only those four values changed;
- never print old/new secret values, hashes, prefixes, line contents, or the full environment.

If any target key is duplicated, malformed, or cannot be changed deterministically: fail closed before environment mutation.

## Provider ordering / failure boundary

Required order:
1. all production preflight;
2. Bot `deleteWebhook`;
3. sanitized webhook-deleted verification;
4. only then clear Bot env values;
5. recreate API + worker;
6. postflight verification.

If provider deletion fails:
- do not change `.env`;
- do not recreate services;
- report sanitized blocker.

After webhook deletion succeeds, do not attempt to re-enable/reconfigure the webhook automatically on later failure. Report the exact sanitized stage and preserve the already-retired direction.

Do not automatically restore Bot secrets after they have been deliberately cleared.

## Tests

Add focused tests covering at minimum:
- canonical checkout/target/ref/release validation;
- exact four-key env mutation;
- duplicate/missing target env key fail-closed;
- non-Bot env bytes/content preserved by neutralized comparison;
- Bot token never appears in subprocess argv or emitted output;
- mocked `deleteWebhook` success/failure;
- mocked webhook read-back confirms empty URL;
- provider failure causes zero env/service mutation;
- env mutation occurs only after provider success;
- only API+worker recreate is issued; never DB;
- MTProto credentials and AI=false postflight checks;
- sanitized failure protocol;
- no second provider call/retry loop beyond the bounded delete + verification sequence.

Run:
- focused harness tests;
- Python compile for local + remote helpers;
- Ruff;
- `git diff --check`.

## Scope discipline

Do NOT in this task:
- call Telegram Bot API;
- SSH to production;
- change production `.env`;
- delete webhook;
- recreate production services;
- deploy/rollback/move refs;
- delete Bot-only source files;
- remove Bot config fields from Compose/Settings;
- delete legacy DB tables/migrations/objects;
- change MTProto behavior;
- enable MTProto AI;
- delete the bot account through BotFather.

## Authorization

AUTHORIZED:
- local code/tests for the Stage B retirement harness;
- update `PROJECT_STATE.md`;
- commit and push to canonical `main`.

NOT AUTHORIZED:
- any live Stage B action.

## Required report

Return:
- commit SHA;
- files changed;
- exact harness protocol/stages;
- secret-safety mechanism;
- env mutation proof mechanism;
- provider-call bounds;
- service recreation scope;
- focused tests/compile/Ruff/diff-check results;
- production SSH=0;
- Bot API/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BJ1_RETIREMENT_HARNESS_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
