# Current task — AH2-MR1.1 eval safety-boundary correction

AH2-MR1 implementation `e1a5dab3faabbfff26c9bd84d969f394a9c211e4` is **not yet Architect source-accepted**.

The scripted A2/T1 execution path is directionally correct and stays eval-only, but source review found two safety-boundary gaps that must be corrected before expanding fixtures or making any real-model call.

This is a narrow correction slice. Do not start AH2-MR2 or the real-model batch.

## Baseline

- AH2-MR1 implementation: `e1a5dab3faabbfff26c9bd84d969f394a9c211e4`
- Executor HOLD: `4b8f392727a1c9abed5c36301bccfd2e61cbbd13`
- production runtime/ref: `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- production Alembic: `0052 / 0052`
- production health: PASS
- real model calls so far: 0

Before implementation verify:

- current `main` is the HOLD above or a descendant containing no unrelated product change;
- `git diff aa3f475a3a0ee49b938364e6d53f3657711b1a9b..HEAD -- backend/app` is empty;
- `python -m evals.secretary_agent.cli validate-catalog` passes.

If `backend/app` has drifted, STOP.

## Blocking finding 1 — guard validates settings, then opens a different global object

Current AH2-MR1 does:

- `assert_disposable_database(settings.postgres_host, settings.postgres_db)`;
- then opens the imported global `app.db.engine.engine`.

This means the safety decision is made from one configuration surface while the actual connection is a separately constructed global engine.

Also, current `assert_disposable_database()` treats any loopback host plus any non-empty database name as positively "local/disposable". That is not a strong enough invariant for the future paid/model runner: a loopback endpoint can still be a tunnel or otherwise not be the intended eval DB.

### Required correction

Remove the AH2-M runner's dependency on the global application `engine`.

The eval runner must receive its database execution target explicitly, e.g. an injected SQLAlchemy `Engine` / connection factory / narrowly equivalent eval-only dependency.

The safety guard must validate the **same actual target that will be opened**.

Minimum required semantics:

1. no fallback to `app.db.engine.engine` or production `SessionLocal`;
2. the actual injected engine URL/target must resolve to an allowed local host:
   - `localhost`
   - `127.0.0.1`
   - `::1`;
3. database name must be present;
4. the caller must explicitly classify the supplied target as eval/disposable through an eval-only contract rather than inheriting ordinary product settings silently;
5. fail closed before `.connect()` when the target is not accepted;
6. the safe identity returned/logged must contain no password/credential-bearing DSN.

Do not query production to compare fingerprints.

Do not introduce a production secret dependency.

A dedicated future env/config input may be added under eval code if needed, but do not require an API key and do not change `backend/app/**`.

### Required tests

Add deterministic evidence that:

- a local explicitly eval-classified injected engine is accepted;
- a remote engine URL is rejected before connection;
- a local URL without explicit eval/disposable classification is rejected;
- changing ordinary `settings.postgres_host` cannot redirect the injected runner;
- the runner contains no use/import of global `app.db.engine.engine` and no `SessionLocal` fallback.

## Blocking finding 2 — sanitizer is not an artifact boundary

Current `assert_no_secrets()` is a standalone helper. `run_scripted()` returns an `EvalRun` without passing an artifact payload through that boundary.

The current key matcher also does not explicitly reject hidden-reasoning/raw-provider/production-data fields.

For AH2-M, "we have a sanitizer function" is insufficient. The committed artifact path must be structurally safe by construction.

### Required correction

Add one eval-only artifact serialization boundary, for example a function equivalent to:

`build_safe_artifact_payload(run, public_config, ...)`

Exact naming is up to the implementation.

Requirements:

1. it serializes from the bounded `EvalRun` + allowlisted public eval metadata only;
2. it must not accept/store an arbitrary raw provider response;
3. before returning/writing a payload, reject secret-bearing keys/values including API keys, passwords, credential-bearing DSNs, OAuth/access/refresh tokens and authorization values;
4. reject hidden-reasoning/raw-provider fields such as:
   - `chain_of_thought`
   - `reasoning_trace`
   - `hidden_reasoning`
   - raw provider request/response or wire payload fields;
5. reject explicitly production-scoped identity/data fields such as `production_user_id` or equivalent;
6. retain only the user-visible final answer, not model reasoning;
7. configuration metadata must come from the existing public/allowlisted config representation;
8. A2 and T1 scripted runs must be serializable through this boundary successfully.

Do not attempt fuzzy PII detection. The important invariant is a narrow allowlisted artifact schema plus synthetic fixtures, not pretending a regex can prove arbitrary text is non-sensitive.

### Required tests

Add tests proving:

- A2 and T1 safe payloads pass;
- `OPENAI_API_KEY`, credential DSN, OAuth/access/refresh token fields fail;
- hidden reasoning/raw provider response fields fail;
- `production_user_id` / explicitly production-scoped fields fail;
- only the normal `final_answer` is retained from provider-facing output;
- the safe payload can round-trip as JSON.

## Existing behavior to preserve

Do not regress the accepted MR1 direction:

- imported live `SYSTEM_INSTRUCTIONS`;
- imported live `ASSISTANT_TOOL_DEFINITIONS`;
- `PerTurnToolBudget`;
- `BoundAssistantToolRunner`;
- `DomainToolService`;
- `ToolExecutionGateway`;
- `ExecutionContext.INTERACTIVE_ASSISTANT`;
- AH2-E `RecordingToolRunner`;
- temporary assistant tool injection restored on success and exception;
- A2 staged-only remains unchanged in DB;
- T1 still uses `ActionPlanService` canonical approval execution and produces one confirmed open ongoing `Публикации` Task locally;
- no model call;
- no live external transport.

The current post-approval trace reconstruction is acceptable for A2/T1 in this correction slice because `ActionPlanService.approve()` executes the canonical `execute_approved_actions_with_tools` path and a failed action raises rather than returning a successful action row. Do not broaden this trace mechanism for the remaining scenarios yet.

## Allowed files

Prefer only:

- `backend/evals/secretary_agent/runner.py`;
- `backend/evals/secretary_agent/safety.py`;
- `backend/tests/test_ah2m_eval_runner.py`.

A small additional eval-only module/test is allowed if it makes the artifact boundary cleaner.

Do not modify `backend/app/**`.

## Required checks

Run:

- focused AH2-MR1/MR1.1 tests;
- `backend/tests/test_ah2e_eval_harness.py`;
- `backend/tests/test_ah1_doc_registry_drift.py`;
- `backend/tests/test_assistant_ontology_kernel.py`;
- `backend/tests/test_ah2d_task_tool_descriptions.py`;
- `backend/tests/test_ah2t_planned_interval.py`;
- `python -m evals.secretary_agent.cli validate-catalog`;
- `git diff --check`;
- `git diff aa3f475a3a0ee49b938364e6d53f3657711b1a9b..HEAD -- backend/app`.

Scripted A2/T1 dry runs must still make zero real model calls and zero external network calls.

## Explicitly forbidden

- OpenAI/model call;
- requiring or reading `OPENAI_API_KEY`;
- production DB access;
- production credential access;
- SSH to production;
- live email/chat/calendar transport;
- deployment;
- migration;
- desktop installation/replacement;
- changes to product prompt/tool/domain/API/UI;
- AH2-MR2/full fixture expansion;
- 15-scenario smoke;
- 49-trial batch;
- AH2-C;
- unrelated work.

## Completion contract

When complete:

1. append a compact factual AH2-MR1.1 result to `PROJECT_STATE.md`;
2. return `CURRENT_TASK.md` to HOLD;
3. HOLD must include:
   - implementation SHA;
   - exact changed files;
   - how the actual injected DB target is validated;
   - proof there is no global app-engine/SessionLocal fallback;
   - safe artifact boundary summary;
   - deterministic test counts;
   - A2/T1 scripted results;
   - model/network call count = 0;
   - `backend/app` parity with production;
   - production unchanged;
   - real AH2-M still blocked on local eval API key;
4. commit/push to `main`;
5. STOP.

Do not start AH2-MR2 after finishing this correction.
