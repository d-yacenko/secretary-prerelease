# Current task — Telegram Bot API M4BK1R2: finalize deterministic Stage B failure protocol

## Status

M4BK1R corrective commit:
`f2eb592a9f7103006d5edbbdf6c9a547b87250bb`

Architect review: core safety hardening accepted, but NOT YET ACCEPTED FOR SECOND LIVE RUN.

Current production runtime/ref remains:
`fe151f12f64886505253e765b82458710a949e34`

Alembic:
`0046`

No second live Stage B action is authorized.

## Goal

Make the final small harness correction so every expected pre/postflight failure has a deterministic sanitized stage and the remaining ordering assertions are covered through `remote_main`.

CODE/TEST ONLY.

## Required corrections

### 1. No STAGE_UNKNOWN for expected retirement checks

Wrap expected checks in explicit `HarnessError` stages.

At minimum distinguish:

- application HTTP health preflight;
- Alembic preflight;
- env/resolved-credential preflight;
- provider delete;
- provider read-back;
- env race/write;
- API/worker recreation;
- post-recreate application container identity/running checks;
- DB container identity/volume checks;
- non-Bot env preservation;
- Bot-settings-empty checks;
- Compose resolved-environment postflight;
- actual API/worker running-container environment postflight;
- MTProto/protected/AI=false postflight;
- application health postflight;
- Alembic postflight.

Stage names may be consolidated where logically appropriate, but a failure after irreversible provider/env mutation must identify whether it occurred during env write, service recreation, DB preservation, running-container env validation, health, or Alembic.

`STAGE_UNKNOWN` should remain only for truly unexpected programmer/runtime exceptions outside known checks.

### 2. Malformed Bot env must be proven pre-provider through remote_main

Add a mocked `remote_main` regression for at least one malformed/duplicate/missing Bot-key case proving:
- terminal failure at the env-preflight stage;
- `TELEGRAM_NETWORK_CALLS=0`;
- no env write;
- no service recreation.

Existing direct helper tests are retained but are not sufficient by themselves.

### 3. Prove both actual new container environments are inspected

Add focused assertions that on success:
- `_container_environment` is called with the new API container ID;
- `_container_environment` is called with the new worker container ID;
- failures in either actual container environment produce the named postflight stage;
- provider call count remains exactly 2 and there is no retry.

### 4. Preserve all accepted hardening

Do not weaken:
- fresh exact `origin/production` fetch/check before provider calls;
- `target.json` as sole production identity;
- canonical `compose exec -T api alembic current` / `0046 (head)`;
- direct DB running/health proof;
- precomputed four-key-only env transform before provider calls;
- byte-identical env race guard before atomic write;
- permissions preservation;
- positive MTProto API ID and API/worker credential equality;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- exactly one `deleteWebhook(drop_pending_updates=true)`;
- exactly one `getWebhookInfo`;
- no provider retry;
- API+worker-only recreation;
- old/new API+worker IDs must differ;
- DB container/volume unchanged;
- actual running-container env verification;
- no automatic webhook or Bot-secret restoration.

## Validation

Run:
- focused retirement harness tests;
- local helper compile;
- bundled helper compile;
- Bash syntax;
- Ruff;
- `git diff --check`.

## Authorization

AUTHORIZED:
- local harness/test changes only;
- update `PROJECT_STATE.md`;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- second live harness run;
- Bot API/provider calls;
- webhook changes;
- production env mutation;
- production service recreation;
- deploy/rollback/ref movement;
- BotFather/account destruction;
- Stage C cleanup;
- MTProto behavior changes;
- AI enablement.

## Required report

Return:
- corrective commit SHA;
- files changed;
- explicit stage map;
- malformed-env remote_main regression result;
- actual-container-env inspection regression result;
- complete focused tests/compile/Ruff/Bash/diff-check results;
- production SSH=0;
- Bot API/provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BK1R2_FAILURE_PROTOCOL_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
