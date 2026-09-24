# Current task — Unify all generative AI on one per-user model selector

## Supersedes

This task supersedes the earlier active task created at `c0e0c2ef7299d64c9a073f97fcfcd24f1b38cf49` before implementation.

## Architecture decision

Secretary must have exactly one user-selectable generative/reasoning model for all text/reasoning AI workloads.

The existing persisted/API field `assistant_model` remains the canonical per-user setting for backward compatibility; do not add a second DB field and do not create an Alembic migration merely to rename it.

The Flutter label should become `Модель ИИ`, because the selection is no longer Assistant-only.

The canonical deployment fallback remains `OPENAI_ASSISTANT_MODEL`. The legacy generic `OPENAI_MODEL` must be retired from runtime use.

Specialized models remain independent and are OUTSIDE this selector:
- embeddings;
- transcription/STT;
- speech/TTS.

Production runtime remains exact `54888ed5797b4b84fa663ff8be11b8b74c64e2a6`, Alembic `0046`.

## Official selectable model IDs

Use this exact default allowlist order:

1. `gpt-6-luna`
2. `gpt-6-sol`
3. `gpt-6-astra`
4. `gpt-5.6-luna`
5. `gpt-5.6-terra`
6. `gpt-5.6-sol`

Default model: `gpt-6-luna`.

Do NOT invent `gpt-6-terra`; it is not an official model ID in the current GPT-6 family.

## Authorization

Code/test/documentation only.

No production mutation, no production env edit, and no live paid OpenAI/provider call in this task.

## Required implementation

### 1. Canonical configuration

- Change `backend/app/core/config.py` default `openai_assistant_model` to `gpt-6-luna`.
- Change the default allowed Assistant/generative model list to the exact six IDs/order above.
- Preserve current insertion/deduplication semantics for an explicitly configured deployment default.
- Keep `assistant_model` as the API/DB field name, but treat/document it as the canonical generative model.

### 2. Retire the hidden second generative model

Audit every runtime OpenAI text/reasoning call site.

All user-scoped generative work must resolve the same effective per-user `assistant_model`.

Known workloads that must be covered include at least:
- interactive Assistant / tool calling / finalization;
- proactive review;
- summarization, including conversation-stack summaries;
- auto-label classification;
- correlation judge;
- semantic/background summaries if model-backed;
- legacy `SecretaryService` / `OpenAISecretaryProvider` bounded-context analysis and proposal generation.

For any additional generative OpenAI call site found by the audit, apply the same rule.

The legacy `settings.openai_model` / `OPENAI_MODEL` must not remain as a runtime model source for generative work.

If the legacy Secretary path currently constructs a provider without user context:
- trace its real runtime callers;
- make the runtime construction user-scoped and feed it `EffectiveUserSettings.assistant_model`;
- if a global helper is truly dead/test-only, remove it or make that status explicit and prove no runtime caller depends on it.

Do not silently leave a global Terra fallback in an obscure path.

### 3. Deployment wiring

`infra/compose.yaml` currently forwards `OPENAI_MODEL` but does not forward the documented Assistant model controls.

For both `api` and `worker`:
- remove runtime forwarding of `OPENAI_MODEL`;
- forward the canonical settings needed by the existing configuration:
  - `OPENAI_ASSISTANT_MODEL`
  - `OPENAI_ALLOWED_ASSISTANT_MODELS`
  - `OPENAI_ASSISTANT_REASONING_EFFORT`
  - `OPENAI_ASSISTANT_VERBOSITY`
  - `OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS`
- preserve the existing specialized OpenAI settings for embeddings/STT/TTS as applicable.

Update `.env.example`:
- remove/deprecate the documented `OPENAI_MODEL` line so it is no longer presented as an active runtime model;
- set `OPENAI_ASSISTANT_MODEL=gpt-6-luna`;
- set `OPENAI_ALLOWED_ASSISTANT_MODELS=gpt-6-luna,gpt-6-sol,gpt-6-astra,gpt-5.6-luna,gpt-5.6-terra,gpt-5.6-sol`.

Do not edit the real production `.env`. An old unused `OPENAI_MODEL` key may remain there until a separately authorized env-maintenance task.

### 4. Existing per-user overrides

Preserve stored user choices if they are still in the allowlist.

Examples:
- stored `gpt-5.6-luna` remains `gpt-5.6-luna`;
- stored `gpt-5.6-terra` remains `gpt-5.6-terra`;
- stored `gpt-5.6-sol` remains `gpt-5.6-sol`.

With no valid stored override, effective model is the deployment default, now `gpt-6-luna`.

No bulk DB rewrite is required.

### 5. Reasoning compatibility

Keep Secretary's currently supported reasoning choices `none|low|medium|high`; do not expand UI scope to xhigh/max in this task.

GPT-6 Astra does not support `reasoning=none`.

Therefore:
- backend validation must reject an incompatible `gpt-6-astra + none` effective/requested combination;
- the Flutter model/reasoning controls must not allow the user to persist that invalid pair;
- if the user switches to `gpt-6-astra` while current reasoning is `none`, send a single coherent settings update that changes reasoning to `low` together with the model, rather than temporarily storing an invalid configuration;
- switching reasoning to `none` while Astra is selected must be unavailable or cleanly rejected before persistence;
- all other listed models may continue using the currently supported app-level reasoning choices.

Do not add silent server-side mutation on read.

### 6. Flutter UI

Use the existing Account → ИИ model selector.

- Rename label `Модель Assistant` to `Модель ИИ`.
- Continue rendering the server-provided allowed model list.
- Do not build a second selector.
- Continue sending the model ID through the existing `assistant_model` field.
- Keep reasoning, verbosity, max rounds, and budget controls otherwise unchanged.

Raw model IDs are acceptable display text for this task; no pricing UI is required.

### 7. Request semantics

Preserve:
- Responses API;
- function/tool calling;
- `store=False`;
- default reasoning `low`;
- default verbosity `low`;
- current max-output/max-rounds behavior;
- current audit/budget accounting.

Do not hardcode token prices into the product.

## Required focused tests

Add/update tests proving at minimum:

1. default effective generative model is `gpt-6-luna`;
2. default allowlist is exactly the six IDs above in that order;
3. all six valid model IDs are accepted by `PATCH /me/settings`;
4. `gpt-6-terra` and an arbitrary unknown model are rejected;
5. valid existing stored GPT-5.6 overrides remain effective;
6. no stored override resolves to `gpt-6-luna`;
7. interactive Assistant uses the effective per-user model;
8. proactive AI uses the same effective per-user model;
9. summarization uses the same effective per-user model;
10. auto-label uses the same effective per-user model;
11. correlation judge uses the same effective per-user model;
12. legacy Secretary analysis/proposals use the same effective per-user model in runtime paths;
13. any other generative runtime provider found by the audit uses the same model source;
14. no runtime generative call site references `settings.openai_model` or otherwise sources `OPENAI_MODEL`;
15. Astra + `none` is rejected, while Astra + `low|medium|high` remains valid;
16. Flutter renders the server-provided model list through the existing selector and sends `assistant_model`;
17. Flutter switching from reasoning `none` to Astra persists a coherent Astra + `low` update;
18. Compose config forwards canonical Assistant/generative settings to both api and worker and no longer forwards `OPENAI_MODEL`;
19. specialized embedding/transcription/TTS model settings are unchanged.

Prefer behavior tests over brittle source-text grep, but a focused static regression check against reintroducing `OPENAI_MODEL` is acceptable in addition to behavior tests.

## Acceptance checks

Run:
- relevant backend focused tests;
- relevant Flutter account/settings tests;
- `py_compile`;
- Ruff check;
- Ruff format check;
- Flutter analyze for touched files;
- `docker compose config --quiet`;
- `git diff --check`.

No Alembic migration should be needed.

Record the implementation result, the audited generative call-site summary, and exact commit SHA in `PROJECT_STATE.md`. Return `CURRENT_TASK.md` to HOLD, push, and STOP.

## Not authorized

- production deploy or production ref movement;
- production env mutation;
- live OpenAI API calls;
- DB writes outside tests;
- changing embedding/STT/TTS model choices;
- Google/OAuth, Telegram, DNS/firewall, nginx, or unrelated feature work.
