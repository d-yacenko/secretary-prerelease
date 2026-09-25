# Current task — Task Refinement T6: task-aware proactive proposal guard

Task Refinement T1/T1R, T2, T3, T4, and T5 are architect-accepted.

Implement only a narrow refinement of the existing proactive task-proposal path so it can use the canonical Task Profile and full canonical non-terminal Task lifecycle when deciding whether to emit a new task proposal.

Do not create Tasks automatically. Do not change proactive scheduling/cadence, enablement defaults, confidence thresholds, notification ranking, personal-relevance policy, provider calls, model family/configuration, production deployment, or the human-acceptance requirement from T5.

## Product intent

The repository already has a bounded proactive-review flow that may emit a `task_proposal` Notification. The Task itself is created only after explicit user acceptance.

Task Refinement T1-T5 introduced richer canonical Task semantics:
- explicit Task Profile;
- actor/dependency/evidence relations;
- derived operational state;
- canonical lifecycle;
- canonical accepted proposal materialization.

T6 should make the existing proactive proposal path aware of those semantics before it suggests a duplicate obligation.

This is a **proposal-quality / duplicate-suppression refinement**, not a new obligation extractor.

## Goal

After T6:

- proactive review remains read-only + Notification proposal only;
- `get_task_profile` is available to the proactive read-only tool runner;
- the model instructions explicitly say to inspect a plausible existing Task with `get_task_profile` before proposing a new Task when such a candidate is found;
- server-side duplicate suppression uses canonical Task lifecycle semantics, not only explicit `open/in_progress`;
- legacy active Tasks with `status=None` count as active for duplicate suppression;
- terminal Tasks do not suppress a genuinely new proposal merely because they reference the same source;
- no Task is created before explicit Notification acceptance.

## 1. Add `get_task_profile` to proactive read-only tools

Extend the proactive read-only allowlist and tool definitions with the existing canonical `get_task_profile`.

Requirements:
- permission remains READ;
- no write tool becomes available;
- existing proactive hard tool-call cap stays unchanged;
- existing seen-object allowlist behavior must continue to work with Task Profile output;
- use the existing canonical tool registry/assistant definition, do not fork a proactive-specific profile schema.

Do not add `create_task`, `update_task`, relation writes, or any other mutation tool.

## 2. Instructions: inspect existing obligations before proposing a new one

Update the existing proactive system instructions narrowly.

The model should:
- use existing bounded search/retrieval tools to look for a plausible existing Task when the evidence appears to describe an obligation;
- when a plausible Task candidate is found, use `get_task_profile` to inspect lifecycle + operational state + explicit actors/dependencies/evidence before proposing a new Task;
- prefer an `insight` about an existing active Task when new evidence changes or advances that Task;
- avoid proposing a duplicate Task for an obligation already represented by an active canonical Task;
- understand that lifecycle `status` and derived `operational.operational_state` are different;
- treat proposed relations in Task Profile as transparency only, not confirmed operational truth.

Keep the existing control/data separation wording and proposal-only safety language.

Do not turn the prompt into a large planning framework. This is a targeted duplicate-avoidance instruction.

## 3. Canonical server-side duplicate guard

Refine `ProactiveReviewService._active_task_references` or the equivalent guard.

A Task referencing the same exact source Object should suppress a new task proposal only when the Task is:

- same-user;
- `kind="task"`;
- active/not tombstoned/not rejected;
- lifecycle non-terminal according to canonical read semantics.

Important:
- `status=None` is legacy-active and MUST suppress duplication;
- `open` and `in_progress` suppress duplication;
- `done`, legacy `completed`, `cancelled`, `archived`, `deleted`, tombstoned, or rejected Tasks do NOT suppress;
- the `references` edge must be confirmed and same-user;
- proposed/rejected evidence edges do NOT suppress.

Reuse `is_terminal_for_reads` / `TERMINAL_TASK_STATUSES_FOR_READS` semantics rather than creating another lifecycle list.

Do not recursively inspect dependency graphs in the server guard.

## 4. Exact-source duplicate suppression stays a guard, not ontology inference

The server-side exact-source guard is intentionally conservative.

Do not infer that two different source Objects are the same obligation based on title similarity, embeddings, same sender, same thread, or same Person.

Broader semantic duplicate judgment remains the model's bounded read-only job.

Do not create a new persisted duplicate/obligation signature in T6.

## 5. Existing Task Profile semantics

The proactive runner must receive the exact same Task Profile shape already used by Assistant/MCP:

- lifecycle `status`;
- actor roles;
- dependencies/dependents;
- evidence;
- nested `operational`;
- truncation flags;
- relation provenance/state.

Do not create a reduced competing proactive Task Profile.

The normal Task Profile boundedness and proposed-relation semantics remain unchanged.

## 6. Proposal-only safety remains unchanged

Prove that:
- proactive `task_proposal` still persists only a Notification;
- no Task is created at proactive-review time;
- ignored/rejected Notification still creates no Task;
- accepted Notification still uses T5 canonical materialization;
- write tools remain blocked in `ProactiveToolRunner`.

Do not change proactive enablement defaults.

## 7. Scope exclusions

Do not implement:

- automatic Task creation;
- new generic Flow obligation extractor;
- new provider ingestion path;
- new ranking/scoring system;
- proactive cadence changes;
- confidence threshold changes;
- new Personal Relevance rules;
- automatic Person-role/dependency inference;
- Project entity;
- migrations;
- production deploy.

## Focused proof

Add tests proving at minimum:

1. `get_task_profile` is present in `PROACTIVE_READ_TOOL_NAMES` / proactive tool definitions.
2. `ProactiveToolRunner` can successfully call `get_task_profile` for a seen Task.
3. A write tool such as `create_task` is still rejected by the proactive runner.
4. Task Profile output through proactive runner includes canonical `operational`.
5. Same-source confirmed `references` to an `open` Task suppress a new task proposal.
6. Same-source confirmed `references` to an `in_progress` Task suppress.
7. Same-source confirmed `references` to a legacy `status=None` Task suppress.
8. Same-source Task with `done` does not suppress.
9. Same-source Task with legacy `completed` does not suppress.
10. Same-source Task with `cancelled`, `archived`, or `deleted` does not suppress.
11. Tombstoned/rejected Task does not suppress.
12. Proposed/rejected `references` edge does not suppress.
13. Cross-user Task/edge does not suppress.
14. Proactive decision that proposes a Task for an exact source with an active referencing Task is dropped server-side even if the model output asks to notify.
15. The same model output is allowed when only terminal referencing Tasks exist.
16. Existing source-kind Task guard remains: source Object itself being `kind=task` cannot produce a new task proposal.
17. Proactive task proposal still creates Notification only; no Task before acceptance.
18. Accepting that Notification still creates exactly one canonical `status=open` Task through T5.
19. Existing proactive insight behavior remains unchanged.
20. No migration, auto-create, cadence/threshold change, ranking, Project entity, or deploy.

Run:
- relevant proactive unit/integration tests, especially `tests/test_proactive_secretary_a.py`, `tests/test_proactive_secretary_b.py`, `tests/test_proactive_secretary_c.py`;
- `tests/test_task_proposal_acceptance.py`;
- `tests/test_task_operational.py`;
- `tests/test_task_relations.py`;
- relevant tool registry / tool gateway tests;
- Ruff/compile touched Python;
- `git diff --check`.

Known unrelated baseline failures caused by persistent bootstrap notifications must be reported precisely and not hidden or opportunistically changed.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Do not begin automatic Flow-to-Task extraction, automatic Task creation, ranking/scoring, project/roadmap semantics, or deploy.
