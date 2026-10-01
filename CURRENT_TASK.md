# Current task — AH2-MR3 internal approval-gated mutation fixtures

AH2-MR2.1 is Architect source-accepted.

Build the next deterministic fixture slice for internal Secretary mutations only. This slice adds F1, M1, M2, R1, R2, and A1 to the eval registry and generalizes eval-only approval execution just enough to execute those approved synthetic internal actions.

No external communication fixture is authorized yet.

This slice must make **zero OpenAI/model calls** and **zero live external network calls**.

## Baseline

- AH2-MR2.1 implementation: `a9cb409e18b56f7481f4078aeef44593a70d96fc`
- AH2-MR2.1 Executor HOLD: `1a2ce8c480d193cdd351b535d51baaa3657342f4`
- Architect acceptance ledger commit: `bb32dfff85224073bb26d2418c839cb0365dbb6b`
- production runtime/ref: `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- production Alembic: `0052 / 0052`
- production health: PASS
- real model calls so far: 0

Before implementation:

1. update to current `main`;
2. verify `git diff aa3f475a3a0ee49b938364e6d53f3657711b1a9b..HEAD -- backend/app` is empty;
3. run `python -m evals.secretary_agent.cli validate-catalog`;
4. preserve the injected disposable DB, production-shaped provider seam, per-round commits, ID allowlists, transaction rollback, and safe artifact boundary.

If `backend/app` has drifted, STOP.

## Authorized new scenarios

Add exactly these primary catalogue scenarios:

- F1 — Flow evidence attachment;
- M1 — one-shot reminder;
- M2 — planned Task interval plus deadline;
- R1 — Task composition via `part_of`;
- R2 — Task actor role `waiting_on`;
- A1 — truthful no-op status update.

Together with existing P1/T1/T2/T3/R3/S1/N1/A2, the primary fixture registry should then cover **14 of the 15** catalogue scenarios. F2 remains intentionally absent.

Do not add terminal-T2 or chat-F2 variants in this slice.

## Approval execution generalization

Current eval approval execution is intentionally narrow around T1/create_task. Generalize it only for the internal tools required by the accepted fixtures.

The eval runner may execute an approved synthetic action only when all of these are true:

1. scenario approval mode is `staged_then_executed`, or `staged_then_executed_if_present` and an action is actually staged;
2. the staged plan contains exactly one action for the currently authorized deterministic fixtures;
3. the tool is in an explicit eval-only internal allowlist:
   - `create_task`
   - `update_task`
   - `link_objects`
   - `create_scheduled_activity`
   - `set_task_status`
4. execution goes through `ActionPlanService.create_plan(...)` then `ActionPlanService.approve(...)`;
5. the approved action result is recorded as an executed `ToolCallRecord`;
6. final facts are read from the local DB after canonical approved execution.

Do not call `DomainToolService` directly in approved mode as a shortcut.

Keep:

- `staged_only` => never execute;
- `approval=none` => never auto-execute;
- no execution for `COMMUNICATE`, `EXTERNAL_WRITE`, or any tool outside the explicit eval-only allowlist.

Add a deterministic fail-closed test showing an unallowlisted staged tool cannot be auto-approved by the eval runner.

## Round and provenance rule

Any ID used by a mutation must be either:

- legitimately seeded because it is present in the synthetic turn/UI context; or
- discovered in an earlier scripted read round and promoted through `commit_model_visible_outputs()`.

The scripted round plan may contain deterministic future-round arguments, but the canonical `PerTurnToolBudget` must be the enforcement boundary. Add tests where appropriate showing a discovered ID would fail before its read-round commit.

Do not globally seed fixture symbols.

## F1 — PDF as evidence for an existing Task

Utterance is the existing catalogue F1.

Synthetic setup:

- one confirmed Flow/file/PDF object representing the exact “this PDF” and exposed in turn context;
- one confirmed open Task `Публикации`;
- no existing `references` edge between them.

Preferred scripted path:

Round 1:
- `retrieve` the Task `Публикации`.

Commit model-visible outputs.

Round 2:
- `update_task` on the retrieved Task with exactly the PDF id in `evidence_object_ids`.

Use the canonical additive evidence field; do not create a second Task and do not use `related_to`.

Stage, approve, and execute that one action via `ActionPlanService`.

Final facts must prove:

- PDF remains non-Task;
- exactly one confirmed evidence relation of type `references` connects the PDF and Task according to the canonical domain behavior;
- no duplicate Task was created.

The AH2-E F1 structural scorer must have all automatable dimensions PASS/NOT_APPLICABLE and overall INCOMPLETE only for final-answer MANUAL_REVIEW.

## M1 — one-shot reminder, not a Task

Fixed eval temporal context remains:

- reference datetime: `2026-10-01T12:00:00+02:00`;
- timezone: `Europe/Amsterdam`.

Synthetic setup needs no existing Task.

Scripted mutation:

- `create_scheduled_activity`;
- title representing `Позвонить в издательство`;
- `run_at=2026-10-02T09:00:00+02:00`;
- normal priority unless a different explicit catalogue-supported value is necessary.

Do not call:

- `create_task`;
- `create_calendar_event`.

Stage, approve, execute canonically.

Final facts:

- `scheduled_activity_count = 1`;
- `task_count = 0`;
- created activity is still an internal scheduled activity, not a calendar event.

## M2 — planned execution interval plus deadline on one Task

Create one confirmed open finite Task `Черновик`. Do not create another Task.

The Task id must be discovered by a read unless it is explicitly placed in synthetic turn context. Prefer a read round so the ID boundary is exercised.

Suggested trace:

Round 1:
- `retrieve` `Черновик`.

Commit.

Round 2:
- one `update_task` containing all of:
  - `object_id`;
  - `planned_start_at`;
  - `planned_end_at`;
  - `due_at`.

Use a deterministic, future, timezone-aware interpretation consistent with the fixed reference context. For the scripted fixture use:

- planned start: `2026-10-06T10:00:00+02:00`;
- planned end: `2026-10-06T12:00:00+02:00`;
- due date on Friday `2026-10-09` represented by a valid timezone-aware datetime according to existing Task due-date conventions.

Do not add:

- reminder/scheduled activity;
- calendar event;
- second Task.

Stage, approve, execute canonically.

Final facts must prove:

- task_count = 1;
- both planned boundaries are present;
- end > start;
- due_at is present;
- no reminder/calendar side object was created.

Do not change AH2-T semantics or validation.

## R1 — child Task part_of parent Direction

Synthetic setup:

- child Task representing “эта задача”, explicitly exposed in turn context;
- parent Task/Direction `Публикации`, `completion_mode=ongoing`;
- no existing parent edge.

Preferred trace:

Round 1:
- `retrieve` parent `Публикации`.

Commit.

Round 2:
- `link_objects` with:
  - source = child Task;
  - target = parent `Публикации`;
  - `relation_type=part_of`;
  - valid confidence.

Stage, approve, execute canonically.

Final facts:

- exactly one confirmed `part_of` edge;
- source is child;
- target is parent;
- no `depends_on` substitute;
- no second parent.

The parent must be compatible with the existing Task composition invariants. Do not weaken those invariants.

## R2 — waiting_on actor role, not generic edge

Synthetic setup:

- one confirmed open Task `Черновик`;
- exactly one Person `Марина` with enough exact identity data for deterministic `resolve_person`;
- no existing `waiting_on` relation.

Preferred trace:

Round 1:
- `resolve_person({"query":"Марина"})`;
- `retrieve` the Task `Черновик`.

These may be calls in the same scripted model round.

Commit.

Round 2:
- one `update_task` with:
  - exact Task `object_id`;
  - `waiting_on_person_ids=[<resolved Marina id>]`.

Do not call `link_objects` as a substitute.

Stage, approve, execute canonically.

Final facts:

- one confirmed actor edge with role `waiting_on`;
- Task remains the same Task;
- no generic `related_to` edge is created for this actor fact.

The Person id must be the id returned by the prior bounded `resolve_person` output and must pass the normal relation allowlist only after the round commit.

## A1 — truthful no-op after approval

Synthetic setup:

- one confirmed Task already in `status=open`;
- Task id exposed in turn context.

Scripted mutation:

- `set_task_status({"object_id": ..., "status":"open"})`.

The interactive call should stage approval as usual for an internal write.

For `staged_then_executed_if_present`:

- approve and execute the one staged synthetic action;
- canonical final execution must report `changed=false`;
- record the executed call effect with `changed=false`;
- final Task status remains `open`.

Do not convert this into `update_task`.

Final facts:

- `status = open`;
- `changed = false`.

The final response itself remains MANUAL_REVIEW; this slice only proves structural/effect truth.

## Final-fact readers

Final facts must be derived from the local DB/domain state, not from scripted arguments.

For relations, inspect confirmed canonical edges.

For M1/M2/A1, inspect the actual persisted object fields/effects after approved execution.

Avoid declaring success merely because an approval result object existed.

## Safe artifacts

Every new completed scripted run must pass:

`build_safe_artifact_payload(run, config.public_dict())`

and JSON round-trip.

No fixture-only hidden metadata may be added to the artifact schema.

## Isolation

Keep outer transaction rollback per trial.

Extend isolation evidence so at least one mutation scenario followed by another scenario leaves no synthetic objects/users/edges/scheduled activities after the first run commits its inner approved action and the outer eval transaction rolls back.

The test must inspect more than the synthetic user display-name prefix; prove relevant object/edge counts do not leak across trial boundaries.

## Required deterministic tests

At minimum prove:

1. registry contains existing 8 plus exactly F1/M1/M2/R1/R2/A1; F2 remains absent;
2. generic approval executor is restricted to the explicit internal allowlist;
3. unallowlisted staged action fails closed and is not executed;
4. F1 read->commit->update evidence path creates one canonical references fact and no Task duplicate;
5. M1 creates one scheduled activity and zero Tasks/calendar events;
6. M2 writes planned start/end + due_at together on the same existing Task;
7. M2 creates no reminder/calendar/second Task;
8. R1 writes child -> parent `part_of`, not reversed and not `depends_on`;
9. R2 resolves Marina, commits the read round, then writes `waiting_on_person_ids` through `update_task`;
10. R2 creates no generic `related_to` actor substitute;
11. A1 approved execution records `changed=false` and status stays open;
12. each new scenario scores INCOMPLETE solely because `truthful_final_response` is MANUAL_REVIEW;
13. all new artifacts JSON-round-trip;
14. mutation-run outer rollback prevents cross-trial object/edge/activity leakage;
15. existing P1/T1/T2/T3/R3/S1/N1/A2 remain green;
16. production-shaped provider seam and per-round commits remain green;
17. OpenAI construction/network path remains unused.

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

## Allowed files

Prefer eval-only changes:

- `backend/evals/secretary_agent/fixtures.py`;
- `backend/evals/secretary_agent/runner.py`;
- `backend/evals/secretary_agent/scripted.py` only if needed;
- focused AH2-M eval tests.

A small eval-only helper module is allowed if it keeps approval execution/final-fact readers clear.

Do not modify `backend/app/**`.

Do not weaken AH2-E scorer rules.

## Explicitly forbidden

- any OpenAI/model call;
- reading/requiring `OPENAI_API_KEY`;
- production DB or credentials;
- SSH to production;
- email/chat/calendar live transports;
- `send_email`, `send_message`, or actual `create_calendar_event` execution;
- deployment, migration, client replacement;
- product prompt/tool/domain/API/UI changes;
- F2 fixture;
- terminal-T2 variant;
- chat-F2 variant;
- 15-scenario real-model smoke;
- 49-trial batch;
- AH2-C;
- unrelated work.

## Completion contract

When complete:

1. append a compact factual AH2-MR3 result to `PROJECT_STATE.md`;
2. replace this file with `# Current task — HOLD`;
3. HOLD must include:
   - implementation SHA;
   - exact changed files;
   - registry coverage (14/15 primary scenarios, F2 absent);
   - approval-execution allowlist;
   - per-scenario F1/M1/M2/R1/R2/A1 result;
   - ID provenance/round result for F1/R1/R2;
   - A1 `changed=false` evidence;
   - rollback isolation evidence;
   - deterministic test counts;
   - model calls = 0;
   - external network calls = 0;
   - `backend/app` identical to production;
   - production unchanged;
   - real AH2-M still blocked on local eval API key;
4. commit/push to `main`;
5. STOP.

Do not start F2/external fixture work or any real-model run without Architect review.
