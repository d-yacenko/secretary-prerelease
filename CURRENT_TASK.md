# Current task — AH2-MR2.1 provider seam and scripted round parity

AH2-MR2 is Architect source-accepted for the authorized no-write/read-only fixture slice.

Before any mutation fixture expansion or real-model call, correct the eval provider seam so the scripted runner obeys the same provider-call and round-boundary contract as production.

This slice is infrastructure-only.

## Baseline

- AH2-MR2 implementation: `e17d1b122e01f2a7bb4736e8c611532506bf59a7`
- AH2-MR2 Executor HOLD: `c96b5c4136c807da44d6703267dabd7c0008450c`
- Architect acceptance ledger commit: `9005af60dade646667f90ba6d03e83db5fc22a76`
- production runtime/ref: `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- production Alembic: `0052 / 0052`
- production health: PASS
- real model calls so far: 0

Before implementation:

1. update to current `main`;
2. verify `git diff aa3f475a3a0ee49b938364e6d53f3657711b1a9b..HEAD -- backend/app` is empty;
3. run `python -m evals.secretary_agent.cli validate-catalog`;
4. preserve the injected disposable `EvalDatabase` and safe-artifact boundaries.

If `backend/app` has drifted, STOP.

## Why this correction is required

Current MR2 `run_scripted()` calls the provider with:

`provider.run(..., prepared=prepared)`

That is an eval-only side-channel. `PreparedFixture` contains fixture-internal data, including values that are deliberately not model-visible.

Production `OpenAIAssistantProvider.run()` does **not** accept `prepared` or arbitrary `**kwargs`.

Also, production provider semantics promote newly model-visible ids by calling `tool_runner.commit_model_visible_outputs()` after each tool-call round. The current scripted path executes all fixture calls and relies on one outer commit after `provider.run()`.

That is sufficient for the already accepted read-only traces, but not a valid foundation for the upcoming read->write scenarios.

## Goal

Make the eval runner provider-compatible and round-faithful without adding any new product scenarios.

After this slice:

- a provider with the exact production `run()` call surface can be passed without adaptation;
- no `PreparedFixture` or hidden fixture metadata is passed through the provider call;
- scripted traces are expressed as explicit tool-call rounds;
- each scripted tool-call round commits model-visible outputs at the same boundary as production;
- the generic runner does not add an extra semantic commit after the provider returns;
- existing P1/T2/T3/R3/S1/N1/A2/T1 traces remain structurally green.

No real OpenAI call is authorized.

## Provider seam

Make the eval `EvalProvider` contract compatible with the existing production `OpenAIAssistantProvider.run()`.

The runner may pass only production-supported arguments:

- `message`;
- `history`;
- `ui_context`;
- `reference_datetime`;
- `timezone`;
- `tool_runner`;
- `identity_facts`;
- optionally the existing production-supported keyword-only `system_instructions` and `tool_definitions` if the eval deliberately pins the already imported live contracts.

Do not pass:

- `PreparedFixture`;
- fixture symbols;
- hidden edge ids;
- stored fixture-only metadata;
- arbitrary eval-only `**kwargs`.

Prefer removing permissive `**kwargs` from the eval protocol so an incompatible call fails statically/tests rather than being silently accepted by a fake.

## Scripted provider

Add or refactor an eval-only scripted provider/driver that:

1. implements the same `run()` call shape as production;
2. is given only a scripted tool-call plan, not the entire `PreparedFixture`;
3. can record model-visible tool results for deterministic tests;
4. never constructs OpenAI or performs network I/O;
5. never receives hidden fixture metadata through `run()`.

A test helper/factory may bind the fixture's **scripted round plan** before `run()`, but must bind only the calls/rounds required to drive the fake. Do not hand the whole fixture object to the provider.

## Scripted round model

Replace the flat fixture `calls` concept with explicit rounds, or an equivalent representation preserving the same semantics.

A scripted round is the set/sequence of tool calls made from one model response.

After all tool calls in that round are returned to the scripted model, call:

`tool_runner.commit_model_visible_outputs()`

exactly as the production provider does before the next model round.

The generic eval runner must not compensate with one unconditional commit after provider return.

For existing fixtures:

- P1: one read round;
- T2: one read round;
- T3: one read round;
- R3: one read round;
- S1: one read round;
- N1: one read round;
- A2: one mutation/staging round;
- T1: represent `retrieve` and subsequent `create_task` as separate rounds.

Do not change the AH2-E expected scenario semantics.

## Critical allowlist proof

Add a focused deterministic test using the canonical `PerTurnToolBudget` + local eval tool path to prove round-boundary behavior with R3:

1. prepare the R3 fixture with only Task/PDF ids initially seen;
2. call `list_neighbors`;
3. take one exact `references` edge id from that **bounded tool output**;
4. before `commit_model_visible_outputs()`, an attempted `remove_relation(edge_id)` must be rejected as not exposed;
5. after the commit boundary, the same exact edge id must pass the edge-id allowlist and reach the normal approval boundary;
6. do not approve/execute that removal;
7. outer transaction rollback leaves fixture state unchanged.

This is an infrastructure test, not the scored R3 scripted scenario. The scored R3 scenario must still make no removal call.

Do not inspect or seed private edge ids as a shortcut for step 3.

## Production-shape compatibility proof

Add a strict fake provider whose `run()` signature matches the production provider shape and contains no `**kwargs`.

Run at least one existing scenario through the generic eval runner with that provider successfully.

Also add a test that would fail if the runner again supplies `prepared=` or another unsupported eval-only keyword.

No OpenAI client construction is needed.

## Existing guarantees to preserve

Keep all accepted MR1/MR1.1/MR2 properties:

- live imported `SYSTEM_INSTRUCTIONS`;
- live imported `ASSISTANT_TOOL_DEFINITIONS`;
- explicit injected disposable DB target;
- no global app engine / `SessionLocal` fallback;
- `PerTurnToolBudget`;
- `BoundAssistantToolRunner`;
- `RecordingToolRunner`;
- canonical local `DomainToolService` / `ToolExecutionGateway`;
- A2 staged-only;
- T1 canonical `ActionPlanService` approved local execution;
- read-only MR2 fixtures and their initial-id semantics;
- safe artifact serialization from `EvalRun` + public config only;
- outer transaction rollback isolation;
- zero model calls;
- zero external network calls.

## Allowed files

Prefer only eval infrastructure/tests:

- `backend/evals/secretary_agent/runner.py`;
- `backend/evals/secretary_agent/fixtures.py`;
- optionally one small eval-only scripted-provider module;
- `backend/tests/test_ah2m_eval_runner.py`.

Do not modify `backend/app/**`.

Do not change AH2-E scorer rules.

## Required deterministic tests

At minimum prove:

1. generic provider invocation contains no eval-only `prepared`/fixture argument;
2. strict production-shape fake provider works;
3. scripted provider gets only scripted rounds, not `PreparedFixture`;
4. one `commit_model_visible_outputs()` occurs after each scripted tool-call round;
5. no unconditional generic-runner commit is required after provider return;
6. T1 is two scripted rounds and remains structurally green;
7. R3 pre-commit exact edge removal is rejected;
8. R3 post-commit exact edge removal reaches approval-required but is not executed;
9. scored R3 still contains only `list_neighbors` and remains unchanged;
10. P1/T2/T3/S1/N1/A2 remain green;
11. all safe artifacts still JSON round-trip;
12. sequential-run isolation remains green;
13. OpenAI construction/network path remains unused.

Keep green:

- `backend/tests/test_ah2e_eval_harness.py`;
- `backend/tests/test_ah1_doc_registry_drift.py`;
- `backend/tests/test_assistant_ontology_kernel.py`;
- `backend/tests/test_ah2d_task_tool_descriptions.py`;
- `backend/tests/test_ah2t_planned_interval.py`.

Also run:

- `python -m evals.secretary_agent.cli validate-catalog`;
- `git diff --check`;
- `git diff aa3f475a3a0ee49b938364e6d53f3657711b1a9b..HEAD -- backend/app`.

## Explicitly forbidden

- OpenAI/model calls;
- reading/requiring `OPENAI_API_KEY`;
- production DB/credentials;
- SSH to production;
- live external transports;
- deployment/migration/client replacement;
- changes to product prompt/tool/domain/API/UI;
- adding F1/F2/M1/M2/R1/R2/A1 fixtures;
- terminal-T2/chat-F2 variants;
- full 15-scenario smoke;
- 49-trial batch;
- AH2-C;
- unrelated work.

## Completion contract

When complete:

1. append a compact factual AH2-MR2.1 result to `PROJECT_STATE.md`;
2. return `CURRENT_TASK.md` to HOLD;
3. HOLD must include:
   - implementation SHA;
   - exact changed files;
   - provider call-surface summary;
   - confirmation no `PreparedFixture` reaches provider `run()`;
   - scripted-round commit semantics;
   - R3 pre-commit rejection / post-commit approval-boundary proof;
   - per-scenario preservation result;
   - deterministic test counts;
   - model calls = 0;
   - external network calls = 0;
   - `backend/app` parity with production;
   - production unchanged;
   - real AH2-M still blocked on local eval API key;
4. commit/push to `main`;
5. STOP.

Do not start mutation fixtures or any real-model run without Architect review.
