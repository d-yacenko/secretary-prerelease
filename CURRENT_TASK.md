# Current task — Task Refinement T5: canonical Notification->Task acceptance

Task Refinement T1/T1R, T2, T3, and T4 are architect-accepted.

Implement only the canonicalization of the existing human-accepted Notification task-proposal materialization path.

Do not change proactive-review model behavior, proposal-generation prompts, proactive scheduling/cadence, notification ranking, automatic Flow-to-Task discovery, task scoring/ranking, Project/roadmap semantics, provider calls, or production deployment.

## Product intent

The system already has an older path where a Notification with `proposal.type == "task"` becomes a confirmed Task after explicit user acceptance.

That path must now obey the canonical Task Refinement invariants instead of constructing Task objects through an older parallel semantic path.

This stage is about one write path only: **user accepts an existing task proposal -> canonical Task is created exactly once with preserved evidence/provenance**.

## Goal

After T5:

- accepting a task proposal still requires explicit user action;
- no Task is created before acceptance;
- accepted Tasks use canonical Task lifecycle semantics;
- source evidence remains linked by canonical `references`;
- idempotent repeated acceptance still returns the same Task;
- malformed/invalid proposal payloads fail closed without partial writes;
- existing proactive proposal generation remains unchanged.

## 1. Canonical lifecycle on accepted Tasks

An accepted Notification task proposal must materialize a canonical active Task with:

- `kind="task"`;
- `origin="agent"`;
- `state="confirmed"`;
- canonical lifecycle `status="open"`;
- accepted title/body/confidence;
- accepted due date if supplied.

Do not rely on `status=None` as the newly created lifecycle state on this path.

Use existing Task lifecycle constants/helpers rather than a new string vocabulary where practical.

## 2. Timing semantics — do not invent a migration

The existing proposal payload may contain `start_at`.

Do **not** silently reinterpret one legacy `start_at` instant as a canonical planned execution interval, because canonical planning requires both `planned_start_at` and `planned_end_at`.

For T5:
- preserve the existing accepted proposal `start_at` behavior if it is currently part of the public proposal contract;
- do not map it to `planned_start_at` without a valid explicit interval;
- do not add a migration;
- do not change T3 scheduled-later semantics.

If comments/docs need clarification, state that proposal `start_at` is not the canonical planned execution interval.

## 3. Reuse one canonical materialization helper/service

Avoid keeping raw Task construction logic embedded in `NotificationService`.

Create or reuse a small Task proposal acceptance/materialization helper/service so the accepted Notification path has one explicit home for:

- validated Task fields;
- canonical status;
- provenance;
- metadata anchor to the Notification;
- source evidence relation;
- embedding enqueue.

Do not route this through Assistant pending ActionPlan approval — the human already explicitly accepted the Notification.

Do not create another user-facing API.

## 4. Exact source evidence

If `notification.source_object_id` is present:

- validate it is still same-user and valid for canonical Task evidence;
- create one confirmed `references` edge from the new Task to that exact source Object;
- preserve exact source-object provenance;
- do not infer a different source from title/body text.

If there is no source object, acceptance may still create the Task.

Do not automatically convert `related_object_id` into a Task relation in T5. It belongs to Notification context unless a later stage gives it explicit Task semantics.

## 5. Fail closed before partial writes

Before creating the Task, validate the complete payload needed for materialization.

At minimum reject/fail closed for:

- empty/missing effective title;
- invalid datetime payloads;
- invalid/cross-user/deleted/rejected source evidence;
- values that violate canonical Task creation invariants.

A failed acceptance must not leave:
- a partial Task;
- a partial evidence edge;
- an embedding job for a non-created Task;
- a Notification falsely marked accepted.

Use transaction/session semantics consistent with the repository's existing services.

## 6. Idempotent repeated acceptance

Current behavior where a Notification with `result_object_id` returns the existing accepted Task must remain idempotent.

Prove:
- first accept creates exactly one Task;
- second accept creates no second Task;
- no duplicate `references` edge;
- no duplicate embedding job caused by repeated acceptance;
- Notification remains accepted and points to the same result object.

If `result_object_id` points to an object that is missing, belongs to another user, or is not the expected Task, fail closed rather than silently creating a replacement or accepting inconsistent state.

## 7. Preserve proposal-only safety

Do not alter proactive-review behavior in this task.

Specifically:
- proactive task proposal still creates only a Notification;
- no Task exists before user acceptance;
- rejected/ignored Notification does not create a Task;
- proposal confidence/priority behavior stays unchanged;
- model/tool allowlists stay unchanged.

## 8. Existing Task Refinement semantics

The accepted Task must immediately work with the already accepted canonical layers:

- Task Profile;
- T3 operational projection;
- T4 Today projection when its due date qualifies;
- canonical lifecycle mutations;
- canonical `references` evidence.

Do not add Person roles, dependencies, waiting/delegation, or inferred relations from proposal text in T5.

## 9. Scope exclusions

Do not implement:

- new Flow obligation extractor;
- automatic creation of Tasks from messages/emails;
- new LLM prompt or model call;
- proactive-review expansion;
- proactive notification policy changes;
- automatic actor/dependency inference;
- new Task status;
- Project entity;
- scoring/ranking;
- migration;
- deploy.

## Focused proof

Add tests proving at minimum:

1. Accepting a valid task Notification creates one confirmed agent Task with `status="open"`.
2. Title/body/confidence/due_at are preserved.
3. Existing proposal `start_at` behavior is preserved but is not silently copied into `planned_start_at` / `planned_end_at`.
4. Exact valid source Object creates one confirmed `references` edge.
5. No source Object still permits valid Task creation.
6. Cross-user source evidence fails before Task creation.
7. Deleted/tombstoned/rejected source evidence fails before Task creation.
8. Missing/empty effective title fails without a Task.
9. Invalid datetime payload fails without a Task.
10. Failure leaves Notification unresolved/not accepted and no embedding job for a new Task.
11. Repeated acceptance returns the same `result_object_id` and creates no duplicate Task.
12. Repeated acceptance creates no duplicate evidence edge.
13. Repeated acceptance does not enqueue a second embedding for the same accepted Task.
14. Inconsistent pre-existing `result_object_id` fails closed.
15. Ignoring a task proposal still creates no Task.
16. Proactive task proposal generation still creates Notification only; no Task before acceptance.
17. Accepted Task is readable through Task Profile and derives a valid T3 operational state.
18. If due today/overdue, accepted Task remains compatible with existing T4 Today projection.
19. Existing Notification acceptance API behavior remains compatible.
20. No migration, model-call change, proactive-policy change, auto-discovery, Project entity, ranking, or deploy.

Run:
- `backend/tests/test_notifications.py`;
- relevant task proposal acceptance tests in `backend/tests/test_today.py`;
- `backend/tests/test_proactive_secretary_a.py` / narrowly relevant proactive tests;
- `backend/tests/test_task_operational.py`;
- relevant Task Profile / Task relation tests;
- Ruff/compile touched Python;
- `git diff --check`.

Known unrelated baseline failures must be reported precisely, not hidden or "fixed" opportunistically.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Do not begin automatic Flow-to-Task obligation discovery, proactive-policy expansion, ranking/scoring, project/roadmap semantics, or deploy.
