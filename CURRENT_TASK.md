# Current task — AH2-MR1 committed real-model eval runner infrastructure

AH2-M real-model evaluation remains the active program, but the first model call is still blocked by the absence of a local eval OpenAI API key.

The previous preflight recorded 64 passing deterministic checks and a scripted-provider dry-run, but the current repository contains only the source-accepted AH2-E harness under `backend/evals/secretary_agent`; there is no committed AH2-M execution runner yet.

AH2-MR1 exists to make the preflight/execution infrastructure reproducible in Git before any paid/model call.

This slice is **infrastructure only**.

## Baseline

Before implementation, verify:

- current `main` is descended from `05c613d216f8e6e9ce9943eca0eebef19fc756cd`;
- production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`;
- `git diff aa3f475a3a0ee49b938364e6d53f3657711b1a9b..HEAD -- backend/app` is empty;
- `python -m evals.secretary_agent.cli validate-catalog` passes.

If `backend/app` has drifted from production, STOP and report it. Do not adapt the eval to a different product contract.

## Goal

Commit a small, deterministic, eval-only AH2-M runner foundation that can later execute the authorized real-model batch, while proving today that:

1. it cannot accidentally use production DB;
2. it can run the real Assistant tool-policy path against a local/disposable DB;
3. model/provider behavior is injectable;
4. scripted fake-provider runs make zero network/model calls;
5. approval staging and approved local execution can be recorded into AH2-E `EvalRun`;
6. the runner restores any temporary eval injection/monkeypatch after success and failure;
7. artifacts/config metadata can be sanitized without leaking secrets.

Do **not** implement the full 49-trial real-model batch in this slice.

## Allowed files

Prefer changes only under:

- `backend/evals/secretary_agent/**`;
- `backend/tests/test_ah2m_*.py` or equivalent focused eval tests;
- narrowly necessary eval documentation.

Do not modify `backend/app/**`.

Do not weaken or rewrite AH2-E scoring rules to make a scripted trace pass.

## Required runner contract

Add an eval-only runner/module with explicit configuration for at least:

- model name;
- reasoning effort;
- verbosity;
- max rounds;
- max output tokens;
- reference datetime;
- timezone;
- execution mode/provider injection.

The production-contract source must be imported from the existing application code; do not copy or fork `SYSTEM_INSTRUCTIONS` or `ASSISTANT_TOOL_DEFINITIONS`.

Default deterministic temporal context for tests:

- timezone: `Europe/Amsterdam`;
- reference datetime: `2026-10-01T12:00:00+02:00`.

The runner must expose a clean seam for a later real `OpenAIAssistantProvider`, but AH2-MR1 tests must use only a scripted/fake provider.

## Local/disposable DB guard

The runner must fail closed before any tool execution unless the DB is positively identified as local/disposable.

At minimum, reject:

- non-local production-looking hosts;
- a configuration that cannot be positively classified as local/disposable.

Do not print credentials or a full credential-bearing DSN.

The runner must never open or read production `SessionLocal` as a fallback.

## Tool execution path

For eval execution, reuse the existing Assistant semantics rather than creating a parallel ontology:

- `PerTurnToolBudget`;
- `BoundAssistantToolRunner`;
- current tool registry/policy;
- `DomainToolService`;
- `ToolExecutionGateway`;
- `ExecutionContext.INTERACTIVE_ASSISTANT`;
- AH2-E `RecordingToolRunner`.

If temporary injection of `assistant_session.run_assistant_tool` is required to bind a local trial session, implement it only inside eval code and restore the original function in a `finally` path.

Do not change production behavior to make the eval easier.

## Minimal deterministic fixtures for AH2-MR1

Do not build all fifteen real-model scenario fixtures yet.

Implement only enough synthetic fixture support to prove the runner architecture with two representative scripted-provider dry runs:

### A2 staged-only

Synthetic utterance/state equivalent to AH2-E A2:

- request to create Task `Купить бумагу`;
- no such Task exists;
- scripted provider stages `create_task`;
- approval is not granted;
- DB remains unchanged;
- `EvalRun` records `approval_required`;
- AH2-E structural score remains `INCOMPLETE` only because answer truthfulness is `MANUAL_REVIEW`, with automatable dimensions passing.

### T1 staged + approved local execution

Synthetic utterance/state equivalent to AH2-E T1:

- request to create ongoing Direction `Публикации`;
- no equivalent Task exists;
- scripted provider uses the expected bounded read/create sequence;
- stage the exact action through the normal approval boundary;
- approve only that synthetic action;
- execute locally through the canonical approved-action path;
- record the executed call/effect;
- derive final semantic facts from the local DB;
- produce an AH2-E `EvalRun` whose automatable dimensions pass.

No external provider transport is needed for these two dry runs.

## Fake/live transport guard

Add a deterministic guard proving AH2-MR1 cannot instantiate a live email/chat/calendar transport during scripted dry runs.

This may be a whitelist/registry assertion around eval transport injection; do not change product transport behavior.

## Sanitization

Add a small artifact/config sanitization boundary sufficient to prove that committed eval artifacts cannot contain:

- `OPENAI_API_KEY`;
- DB passwords/full credential-bearing DSNs;
- OAuth/provider tokens;
- production user data;
- hidden reasoning / chain-of-thought.

Do not log or persist secret values in tests.

## Required deterministic tests

Before completion, add focused tests for:

1. production-code parity guard against release `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`;
2. local/disposable DB acceptance and non-local fail-closed rejection;
3. eval tool-runner injection restores the original production function after success;
4. restoration also happens after an exception;
5. scripted provider path makes zero real model/network calls;
6. A2 staged-only leaves DB unchanged;
7. T1 stage -> approved execution creates exactly one ongoing Task locally;
8. recorded calls preserve approval/execution/effect facts for AH2-E;
9. fake/live transport guard;
10. sanitizer rejects or removes secret-bearing fields.

Also keep green:

- `backend/tests/test_ah2e_eval_harness.py`;
- `backend/tests/test_ah1_doc_registry_drift.py`;
- `backend/tests/test_assistant_ontology_kernel.py`;
- `backend/tests/test_ah2d_task_tool_descriptions.py`;
- `backend/tests/test_ah2t_planned_interval.py`.

Run `git diff --check`.

## Explicitly forbidden in AH2-MR1

- any OpenAI/model call;
- reading or requesting a production user's OpenAI key;
- requiring `OPENAI_API_KEY` for tests;
- production DB access;
- SSH to production;
- real email/chat/calendar actions;
- migrations;
- deployment;
- desktop client replacement;
- changes under `backend/app/**`;
- prompt/tool-description tuning;
- behavior fixes based on anticipated eval results;
- AH2-C;
- SW2-B;
- relation-editor or unrelated product work.

## Completion contract

When complete:

1. append a compact factual AH2-MR1 result to `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD`;
3. HOLD must include:
   - implementation SHA;
   - exact changed files;
   - deterministic test counts;
   - scripted dry-run result for A2 and T1;
   - confirmation that model/network calls were zero;
   - confirmation that `backend/app` still matches production;
   - confirmation that production remains unchanged;
   - explicit statement that AH2-M real-model execution is still blocked on a local eval API key;
4. commit + push to `main`;
5. STOP.

Do not start AH2-MR2/full fixture expansion and do not make a real model call without the next Architect authorization.
