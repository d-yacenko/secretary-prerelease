# Current task — Add GPT-6 models to the existing Assistant model selector

## Context

Official OpenAI pricing and model documentation now list GPT-6 Luna as available in the API with Responses API, function calling, image input, and reasoning-effort support.

Secretary already has an end-to-end per-user Assistant model selector:
- deployment defaults/allowlist in `backend/app/core/config.py`;
- validation/effective-user override in `EffectiveUserSettingsService`;
- `GET/PATCH /me/settings` exposes `allowed_assistant_models` and `assistant_model`;
- Flutter `Account → ИИ → Модель Assistant` renders the server-provided allowlist and persists the selection.

Do not build a second model-selection system.

Production runtime remains exact `54888ed5797b4b84fa663ff8be11b8b74c64e2a6`, Alembic `0046`.

## Authorization

Code/test/documentation only. No production mutation and no live paid provider call in this task.

## Required change

1. Change the Assistant deployment default in `backend/app/core/config.py` from:
   - `gpt-5.6-luna`
   to:
   - `gpt-6-luna`.

2. Make the default Assistant allowlist, in this exact preference order:
   - `gpt-6-luna`
   - `gpt-6-sol`
   - `gpt-5.6-luna`

   Keep the existing deployment-default insertion/deduplication semantics.

3. Preserve per-user model overrides:
   - a stored model remains effective if it is still in the allowlist;
   - therefore an existing explicit `gpt-5.6-luna` selection must not be silently rewritten;
   - users can switch to `gpt-6-luna` through the already-existing Flutter dropdown.

4. Keep current Assistant request shape unchanged:
   - OpenAI Responses API;
   - function/tool calling;
   - `store=False`;
   - reasoning effort default `low`;
   - verbosity default `low`;
   - current max-output and max-rounds behavior.

5. Do NOT change the generic/background `OPENAI_MODEL=gpt-5.6-terra` in this task. That is a separate workload and requires a separate audit.

6. Update `.env.example` to document:
   - `OPENAI_ASSISTANT_MODEL=gpt-6-luna`;
   - `OPENAI_ALLOWED_ASSISTANT_MODELS=gpt-6-luna,gpt-6-sol,gpt-5.6-luna`.

7. Do not hardcode token prices into the product UI. Pricing changes independently from Secretary releases.

8. Add/update focused tests proving:
   - default Assistant model is `gpt-6-luna`;
   - default allowed list has the exact three models and order above;
   - `gpt-6-luna`, `gpt-6-sol`, and `gpt-5.6-luna` are accepted through `PATCH /me/settings`;
   - a model outside the allowlist is rejected;
   - an existing stored `gpt-5.6-luna` remains effective;
   - with no stored override, effective model is `gpt-6-luna`;
   - Flutter continues to render the server-provided multi-model list and sends the selected id through the existing `assistant_model` field.

9. If existing tests reveal that the Flutter dropdown assumes a single item, fix only that regression; do not redesign the Account screen.

## Acceptance checks

Run relevant backend focused tests, relevant Flutter account/settings tests, `py_compile`, Ruff check/format check, Flutter analyze for touched files, and `git diff --check`.

No Alembic migration should be needed.

## Not authorized

- production deploy or production ref movement;
- production env edits;
- live OpenAI API/provider calls;
- changing `OPENAI_MODEL` background workloads;
- DB writes outside tests;
- Google/OAuth, Telegram, DNS/firewall, nginx, or unrelated feature work.

Record implementation result and exact commit SHA in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, push, and STOP.
