# Current task — Production rollout: unified per-user generative model selector

## Human authorization

The human explicitly authorized this production rollout.

This authorization covers:
- fast-forwarding `origin/production`;
- the normal production deploy path via `ops/production/deploy.py`;
- read-only/sanitized production verification.

It does NOT authorize:
- editing the production `.env`;
- live paid OpenAI/provider calls;
- unrelated production changes;
- direct/manual SSH deployment outside the normal deploy harness.

## Release contents

Deploy the current task commit itself as the exact release SHA.

Its parent MUST be exactly:
`c455d8caf1d9be18e2d8e37f4e446fc96d9d4e3b`

The accepted implementation contained in this release is:
`6b22bdc94e5c993a44d6d9b719a1dbbbcbfea529`

Verification completion:
`34d7dcc91210d0e4d26b3d608faf65a086e76c4c`

Current production/rollback baseline:
`54888ed5797b4b84fa663ff8be11b8b74c64e2a6`

Expected Alembic head remains:
`0046`

## Required preflight — BEFORE moving production ref

1. Canonical bootstrap:
   - clean worktree;
   - `HEAD == origin/main`;
   - current HEAD is this task commit;
   - its parent is exactly `c455d8caf1d9be18e2d8e37f4e446fc96d9d4e3b`.

2. Confirm:
   - `origin/production == 54888ed5797b4b84fa663ff8be11b8b74c64e2a6`;
   - current production runtime reports the same release SHA;
   - Alembic is `0046`.

3. Capture sanitized rollback invariants before deploy:
   - production DB container identity;
   - production DB volume identity;
   - production `.env` SHA-256 only;
   - API and worker container identities.

4. Read ONLY these non-secret model-related keys from production `.env`, without printing any other env content:
   - `OPENAI_ASSISTANT_MODEL`;
   - `OPENAI_ALLOWED_ASSISTANT_MODELS`;
   - `OPENAI_ASSISTANT_REASONING_EFFORT`;
   - `OPENAI_ASSISTANT_VERBOSITY`;
   - `OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS`.

   Treat an unset key as acceptable because Compose has canonical defaults.

5. BLOCK BEFORE ANY PRODUCTION REF MOVEMENT if:
   - `OPENAI_ASSISTANT_MODEL` is explicitly set to a value other than `gpt-6-luna`; or
   - `OPENAI_ALLOWED_ASSISTANT_MODELS` is explicitly set and does not equal exactly:
     `gpt-6-luna,gpt-6-sol,gpt-6-astra,gpt-5.6-luna,gpt-5.6-terra,gpt-5.6-sol`.

   Do not edit `.env` to fix a blocker. Report and STOP.

Reasoning/verbosity/max-output explicit overrides are allowed if syntactically valid under the deployed config; report their non-secret values.

## Authorized rollout sequence

Only if preflight passes:

1. Fast-forward `origin/production` non-force from
   `54888ed5797b4b84fa663ff8be11b8b74c64e2a6`
   to the exact current task commit/release SHA.

2. Deploy ONLY through the normal production path:
   `ops/production/deploy.py`

3. Require deploy success:
   - deployment PASS;
   - health PASS;
   - Alembic remains `0046`;
   - runtime release SHA equals the exact release SHA;
   - rollback is not used unless the normal deploy harness determines it is required.

4. Confirm post-deploy invariants:
   - DB container identity unchanged;
   - DB volume identity unchanged;
   - production `.env` SHA-256 unchanged;
   - API and worker are the expected newly deployed containers;
   - no unrelated service/config mutation.

## Post-deploy functional verification — NO LIVE OPENAI CALL

Use authenticated application/API inspection if the existing production verification harness supports it. Do not expose credentials/tokens.

Verify the effective settings contract for the authorized user:

- `GET /me/settings` succeeds;
- `allowed_assistant_models` is exactly, in order:
  1. `gpt-6-luna`
  2. `gpt-6-sol`
  3. `gpt-6-astra`
  4. `gpt-5.6-luna`
  5. `gpt-5.6-terra`
  6. `gpt-5.6-sol`
- report the current `assistant_model` value without changing it;
- report current `assistant_reasoning_effort` without changing it.

Do NOT issue an Assistant prompt merely to test the provider. No paid/live OpenAI request is authorized in this rollout.

If authenticated settings inspection cannot be performed safely with the existing harness, do not improvise credentials; record it as NOT VERIFIED and continue only with infrastructure health verification.

## Rollback rule

If normal deployment or health verification fails after the production ref moves, use ONLY the rollback behavior already provided by the production deployment harness to restore the baseline release `54888ed5797b4b84fa663ff8be11b8b74c64e2a6`.

Do not manually mutate DB, Compose state, nginx, DNS, firewall, or credentials.

## Completion

Record sanitized exact results in `PROJECT_STATE.md`, including:
- exact deployed release SHA;
- production ref before/after;
- deployment and health status;
- Alembic;
- DB/container/env invariants;
- effective allowed model list and current user-selected model if safely observable;
- whether rollback was used.

Then return `CURRENT_TASK.md` to HOLD, commit/push, and STOP.
