# CURRENT_TASK

## Status

ACTIVE

## REL1D-A.1 — correct role-import AI audit lifecycle and token accounting

REL1D-A implementation `d1d4708d7e491131d81ced19de4495bef0c0ddc5` is **not yet Architect source-accepted**.

Architect review found one bounded audit/budget defect that must be corrected before REL1D-B:

1. a successful real role-import extraction currently emits `EVENT_MODEL_ROUND` twice:
   - once inside `OpenAIRoleImportExtractionProvider`;
   - once again in `PersonRoleImportExtractionService`;
   both events can carry the same `input_tokens/output_tokens`, so one paid extraction can be counted twice by `OpenAIDailyBudgetGuard`;

2. the custom role-import trace writes a `trace_finished` event but does not call the canonical trace finish path, so `AITrace.finished_at` / terminal trace state are not finalized correctly;

3. because the custom trace uses the request session, a failed extraction that becomes an HTTP error can be rolled back with the request, losing the failed AI audit trace.

This task fixes only those audit/accounting semantics.

Do not start REL1D-B/C.

Do not change extraction product semantics, source formats, client preview, Person/Role grounding, or persistence behavior.

No deploy, migration, client install, or real model/provider call.

## Fixed baseline

Preserve all accepted/intended REL1D-A behavior:

- raster source formats exactly `.png/.jpg/.jpeg/.webp`;
- raster upload only with `ingest_content=false`;
- signature + SHA-256 + user/object upload-path checks;
- text source from stored full/chunk/body only, cap 24000 chars;
- proposal output max 32 ungrounded rows;
- no Person/RoleTerm/assignment/identity/edge/task/label/notification/ActionPlan writes;
- one-shot Responses API;
- `store=False`;
- no tools;
- structured JSON;
- current-user credential/effective model;
- prompt-injection boundary;
- client explicit `Извлечь роли` preview and `Ничего не сохранено`;
- schema head `0054`.

Production/backend/client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`, Alembic `0054 / 0054`.

## Required correction A — use canonical durable AI-trace lifecycle

Replace the ad-hoc role-import trace lifecycle with the canonical AI audit machinery or an exactly equivalent implementation.

Preferred shape:

- `ai_trace_session(user_id, WORKLOAD_ROLE_IMPORT_EXTRACTION, object_id=source_object_id)`
- use its own audit session / canonical durable trace behavior rather than relying on the request product-data transaction.

Requirements:

- successful extraction persists one completed `AITrace`;
- `finished_at` is non-null;
- `success=true`;
- terminal `trace_finished` event exists exactly once;
- provider/extraction failure after trace start persists a completed failed `AITrace`;
- failed trace has `finished_at` non-null;
- `success=false`;
- `error_category` is bounded/sanitized;
- terminal `trace_finished` event exists exactly once;
- request rollback / HTTP error must not erase the failed audit trace;
- do not commit product-data mutations merely to preserve audit.

Do not invent a second tracing framework.

## Required correction B — exactly one budget-chargeable model event per actual provider call

For one real OpenAI Responses extraction request, there must be at most one event whose type is in:

- `EVENT_MODEL_ROUND`;
- `EVENT_MODEL_ROUND_FAILED`.

### Success

If a Responses API call returns a response:

- emit exactly one `EVENT_MODEL_ROUND`;
- include actual reported `input_tokens/output_tokens` once;
- include model/source-kind and other already-safe technical metadata as appropriate;
- never emit a second `EVENT_MODEL_ROUND` for proposal normalization.

### Provider/API failure

If the provider actually attempts the Responses API call and it raises:

- emit exactly one `EVENT_MODEL_ROUND_FAILED`;
- do not fabricate token counts when OpenAI did not report them;
- do not echo source bytes/text, names, roles, evidence, API key, or provider exception text that may contain source content;
- trace still finishes as failed.

### Budget blocked before API request

If `OpenAIDailyBudgetGuard.ensure_allowed()` blocks before `responses.create`:

- no model-round/model-round-failed event should claim that a provider call occurred;
- trace may finish failed/blocked;
- no token usage is charged for the blocked call.

## Required correction C — proposal/result metadata is non-chargeable

The normalized proposal still needs safe audit metadata:

- `source_kind`;
- source byte/text length;
- `source_revision`;
- item count;
- source/items truncation;
- model identifier when available.

Do **not** encode this by emitting a second `EVENT_MODEL_ROUND`.

Use one of:

- a new explicit non-budget event such as `role_import_proposal`; or
- safe terminal trace metadata if that fits existing audit conventions.

If adding an event constant:

- keep it narrow and documented;
- it must not be included in `BUDGET_USAGE_EVENT_TYPES`;
- it must not inflate model-call counts.

Do not repeat `input_tokens/output_tokens` on a second event unless that event is explicitly non-chargeable **and** all aggregate/reporting code proves it cannot double-count. Preferred: token usage lives only on the single model event.

## Required correction D — budget/accounting truth

For a scripted real-provider response reporting, for example:

- `input_tokens=2`;
- `output_tokens=3`;

prove:

- one extraction contributes exactly **5** daily tokens, not 10;
- AI audit summary/list reports exactly one model call for that extraction;
- repeated two successful extractions contribute 10 total, not 20;
- a blocked pre-call contributes 0;
- a provider-call failure with no reported usage contributes 0, not an estimate.

Do not change global daily-budget rules.

## Required correction E — audit privacy remains intact

Preserve the REL1D-A privacy contract.

No persisted audit metadata/payload/error field may contain raw:

- raster bytes/base64;
- source document text;
- extracted Person names;
- role text;
- role context;
- evidence excerpts;
- API key;
- upload path;
- arbitrary provider exception body.

Safe technical values remain allowed:

- workload;
- model;
- source kind;
- byte/text length;
- source revision/hash;
- item count;
- truncation booleans;
- actual token usage;
- bounded error category.

If capture mode can persist payloads through the canonical trace helper, explicitly ensure REL1D extraction never opts raw source/proposal fields into payload capture.

## Required deterministic tests

Extend focused REL1D-A tests to prove at minimum:

1. successful scripted production-provider path creates exactly one chargeable `model_round`;
2. no second `model_round` is emitted by proposal normalization;
3. one 2-input/3-output extraction charges exactly 5 daily tokens;
4. two such extractions charge exactly 10;
5. AI audit model-call count is exactly 1 per extraction;
6. successful trace has:
   - `finished_at != null`;
   - `success=true`;
   - exactly one terminal trace-finished event;
7. provider-call exception creates exactly one `model_round_failed`;
8. failed trace is durably present after the request/error transaction is rolled back;
9. failed trace has:
   - `finished_at != null`;
   - `success=false`;
   - bounded error category;
   - exactly one terminal event;
10. pre-call daily-budget rejection emits no model-round event and charges 0;
11. proposal metadata is present in a non-chargeable location/event;
12. proposal event does not affect budget or model-call count;
13. source revision/item count/truncation remain auditable;
14. raw source token sentinel, extracted name/role/evidence sentinel and provider exception sentinel are absent from all persisted audit metadata/payload/error fields;
15. extraction still mutates no product rows beyond normal isolated AI audit accounting;
16. existing REL1D-A source/extraction behavior remains green.

Prefer testing the actual service/trace integration, not only isolated helper functions.

## Regression checks

Run at minimum:

- `backend/tests/test_rel1d_role_import_extraction.py`;
- `backend/tests/test_rel1d_role_import_source.py`;
- focused AI audit summary/list tests;
- focused OpenAI daily-budget tests;
- resource registration/upload focused tests;
- REL1A and REL1C role regressions touched by this area;
- Ruff on changed Python;
- `py_compile` on changed/new role-import modules;
- `git diff --check`.

No Dart/client changes are expected. If no client file changes, Flutter tests need not be rerun beyond recording that client behavior is untouched.

### Existing unrelated baseline failures

The REL1D-A HOLD reports four combined-suite failures that were reproduced against the pre-REL1D-A registration service:

- `test_register_same_revision_already_ingested_skips_content`;
- `test_register_long_text_chunks_embedded_by_worker_and_ranked_in_context`;
- `test_metadata_only_upload_persisted_for_later_ingest`;
- `test_mixed_workload_summary_metrics`.

Do not repair unrelated debt in this corrective slice.

Re-run/report them only as needed to establish that REL1D-A.1 did not add a new failure. If any of those four changes behavior because this audit fix touches shared audit accounting, stop and explain rather than silently rewriting unrelated expectations.

## Expected production-code scope

Expected changes should be limited to a narrow subset of:

- `backend/app/services/person_role_import_extraction_service.py`;
- `backend/app/llm/openai_role_import_provider.py`;
- `backend/app/ai_audit/constants.py` only if a dedicated non-chargeable event is added;
- focused REL1D-A/audit/budget tests.

Avoid changing:

- raster upload/storage logic;
- resource registration semantics;
- client code;
- PersonRoleService;
- REL1C Assistant tools;
- Personal Relevance;
- Proactive;
- Alembic/schema.

## Explicit non-goals

Do not start:

- Person grounding;
- RoleTerm matching;
- Person promotion;
- batch proposal confirmation;
- batch role persistence;
- source provenance writes into PersonRoleAssignment;
- REL1D-B;
- REL1D-C;
- ORG1;
- deployment.

## Production / external-effect boundary

Source-only.

Do not:

- move `production`;
- deploy;
- migrate;
- build/install/replace the client;
- call OpenAI or another real provider;
- mutate production data.

## Completion protocol

After implementation:

1. append a compact REL1D-A.1 result to `PROJECT_STATE.md` with:
   - single-model-event rule;
   - exact budget proof;
   - trace success/failure lifecycle;
   - non-chargeable proposal metadata location;
   - privacy proof;
   - exact test counts;

2. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - exact test counts;
   - schema still `0054`;
   - production/client still `6f802d...`;
   - no deploy/migration/client/model/provider/product-data action;
   - REL1D-B/C not started;

3. commit + push to `main`;

4. STOP.

Do not start REL1D-B from HOLD.
