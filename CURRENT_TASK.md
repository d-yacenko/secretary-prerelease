# Current task — Task Refinement T3: derived operational/actionability projection

Task Refinement T1/T1R and T2 are architect-accepted.

Implement only a deterministic, read-only operational projection for Tasks so Secretary can distinguish what requires the user's action now from what is waiting, delegated, blocked, scheduled later, or terminal.

Do not implement automatic task discovery from Flow, proactive notifications, importance scoring, project/roadmap semantics, new mutable Task statuses, LLM classification, provider calls, or production deployment.

## Product intent

Secretary should reduce attention load.

The canonical lifecycle status (`open`, `in_progress`, `done`, etc.) answers whether a Task is open/closed.

It does **not** answer whether the user can or should act on it now.

T3 introduces a derived projection only. It must never become another independently editable source of truth.

## Goal

Given one canonical Task and current time, derive:

- lifecycle state;
- operational/actionability state;
- blocking/waiting/delegation reasons;
- time pressure signals;
- a compact explanation based only on confirmed canonical facts.

This projection should be shared by:
- Task Profile REST;
- Assistant/MCP `get_task_profile`;
- first-party Task Profile UI;
- later Today/focus ranking.

## 1. No new persisted operational status

Do NOT add a DB column or metadata field such as `operational_status`, `attention_state`, or `blocked=true`.

Create a pure/domain read model, e.g.:
- `TaskOperationalState`;
- `derive_task_operational_state(...)`;
- `TaskOperationalProjectionService`.

The result is recomputed from canonical state.

No migration.

## 2. Canonical inputs

Use only active same-user canonical facts:

### Task lifecycle/time
- Task `status`;
- `due_at`;
- `planned_start_at`;
- `planned_end_at`.

### Confirmed Task relations only
For operational truth, use only `state="confirmed"` relations:
- `waiting_on`;
- `delegated_to`;
- `depends_on`.

Do not let a merely `proposed` relation change derived operational state.

`requested_by`, `involves`, and `references` may explain context but do not directly change actionability in T3.

## 3. Operational state vocabulary

Use a deliberately small derived vocabulary:

- `terminal`
- `blocked`
- `waiting`
- `delegated`
- `scheduled_later`
- `actionable`

This is not Task lifecycle. It is a read projection.

### Precedence

Apply deterministic precedence:

1. **terminal**
   - canonical/legacy terminal lifecycle according to existing Task lifecycle helpers.

2. **blocked**
   - at least one confirmed `depends_on` target Task is still non-terminal and active.

3. **waiting**
   - at least one confirmed active `waiting_on` Person relation.

4. **delegated**
   - at least one confirmed active `delegated_to` Person relation.

5. **scheduled_later**
   - Task has `planned_start_at > now`.

6. **actionable**
   - none of the above.

Rationale: blocking dependency is stronger than waiting/delegation; explicit waiting is stronger than general delegation. A Task may have several underlying signals, but one primary operational state keeps the focus surface simple.

Also return the underlying reason collections/flags so information is not lost.

## 4. Dependency semantics

A dependency blocks only when:
- relation is confirmed and effective;
- target is an active same-user Task;
- dependency Task lifecycle is non-terminal.

A dependency that is:
- done/completed;
- cancelled;
- archived;
- deleted/tombstoned/rejected;
does not block.

Do not mutate or auto-remove the `depends_on` edge when the dependency completes.

Return bounded blocking dependency summaries:
- task id;
- title;
- lifecycle status.

Do not recursively traverse the dependency graph in T3. Direct dependencies only.

## 5. Waiting/delegation semantics

A Person counts for operational state only when:
- relation edge is confirmed;
- Person is active/same-user/not rejected/deleted.

Return bounded Person summaries for:
- confirmed waiting_on;
- confirmed delegated_to.

Do not infer that delegated work is completed from messages.
Do not clear waiting/delegation automatically.

If both confirmed `waiting_on` and `delegated_to` exist, primary state is `waiting`.

## 6. Time signals

Return orthogonal deterministic time fields:

- `is_overdue`: non-terminal Task with `due_at < now`;
- `due_at`;
- `planned_start_at`;
- `planned_end_at`;
- `is_scheduled_later`: non-terminal and `planned_start_at > now`;
- optionally `is_planned_now`: planned interval contains now, if both bounds exist.

Do not invent “due soon” thresholds in T3.

Overdue is orthogonal:
- a waiting/delegated/blocked Task may also be overdue;
- do not force overdue into the primary operational-state precedence.

## 7. Derived explanation/reasons

Expose machine-readable reasons, not an LLM-written sentence.

Example fields:
- `operational_state`;
- `is_overdue`;
- `blocking_dependencies`;
- `waiting_on`;
- `delegated_to`;
- `reason_codes`.

Suggested reason codes:
- `terminal_lifecycle`;
- `open_dependency`;
- `waiting_on_person`;
- `delegated_to_person`;
- `planned_start_in_future`;
- `no_external_blocker`;
- `overdue`.

Keep deterministic ordering.

Do not call an LLM to explain the state.

## 8. Task Profile integration

Extend canonical `TaskProfileOut` / tool schema with one nested operational projection.

The same shape must be returned by:
- `GET /tasks/{task_id}/profile`;
- Assistant/MCP `get_task_profile`.

Do not create a second competing endpoint for the same Task semantics unless a small batch endpoint is needed for bounded list views.

Existing actor/dependency/evidence lists remain unchanged.

Important:
- Task Profile may still show proposed relations for transparency;
- operational projection must ignore proposed relations.

## 9. Optional bounded batch read for focus surfaces

If needed to avoid N+1 reads in Today/Graph later, add a bounded batch service/API now, e.g.:
- `POST /tasks/operational-projections` with max N task ids;
or an internal batch method only.

If no current caller needs it in T3, keep it internal and tested rather than exposing unnecessary API.

Do not scan all Tasks just to derive one profile.

## 10. First-party UI

In the existing Task Profile section, show one compact operational cue.

Suggested Russian labels:
- terminal -> lifecycle label already expresses closure; no extra noisy badge required;
- blocked -> `Заблокировано`;
- waiting -> `Ждём`;
- delegated -> `Поручено`;
- scheduled_later -> `Запланировано позже`;
- actionable -> `Можно действовать`.

If overdue, add a separate concise cue:
- `Просрочено`.

Requirements:
- no dashboard of scores;
- no duplicated list of all reasons if the existing role/dependency sections already explain them;
- primary cue should help orientation, not add visual noise;
- proposed relations must not change the cue.

## 11. Assistant contract

Update `get_task_profile` description so the model understands:

- `status` = lifecycle;
- `operational.operational_state` = derived current actionability;
- operational state is read-only and deterministic;
- proposed relations do not affect it;
- `overdue` may coexist with waiting/delegated/blocked.

Do not add a write tool for operational state.

## 12. Boundedness

Operational derivation must use bounded queries.

For one Task:
- direct confirmed dependencies only;
- bounded direct waiting/delegated Person relations;
- no recursive graph traversal;
- no all-Task scan.

If profile lists are truncated, the operational state must still be correct:
- state detection should use EXISTS/count-style queries or enough bounded logic to know whether a confirmed blocker/waiter/delegate exists even if presentation list is capped.

Do not derive state only from the truncated presentation arrays.

## 13. Truth and precedence examples

Required examples:

### Plain open Task
- open;
- no confirmed blocker/wait/delegate;
- no future planned start;
=> `actionable`.

### Future planned Task
- open;
- planned_start_at tomorrow;
=> `scheduled_later`.

### Waiting Task
- open;
- confirmed waiting_on Olga;
- future planned start also exists;
=> `waiting`.

### Delegated Task
- open;
- confirmed delegated_to Ivan;
=> `delegated`.

### Blocked Task
- open;
- confirmed dependency Task is open;
- also waiting_on someone;
=> `blocked`.

### Completed dependency
- dependency becomes done;
=> no longer blocks; derive from remaining signals without changing edge.

### Proposed waiting edge
- edge is agent/proposed;
=> does not change actionability.

### Overdue blocked Task
- due_at in past + open dependency;
=> operational `blocked`, `is_overdue=true`.

## Focused proof

Add tests proving at minimum:

1. Plain active open Task derives `actionable`.
2. Terminal Task derives `terminal`.
3. Future planned start derives `scheduled_later`.
4. Confirmed waiting_on derives `waiting`.
5. Proposed waiting_on does not change `actionable`.
6. Confirmed delegated_to derives `delegated`.
7. Waiting + delegated derives `waiting`.
8. Open confirmed dependency derives `blocked`.
9. Blocked + waiting derives `blocked`.
10. Done/completed dependency does not block.
11. Cancelled/archived/deleted dependency does not block.
12. Rejected dependency edge does not block.
13. Proposed dependency edge does not block.
14. Overdue is true for non-terminal past-due Task regardless of blocked/waiting/delegated.
15. Terminal past-due Task is not operationally overdue.
16. Task Profile REST includes the operational projection.
17. Assistant/MCP `get_task_profile` includes the same shape.
18. UI shows the correct compact Russian operational cue.
19. UI can show `Просрочено` independently of primary operational state.
20. A proposed relation visible in profile does not alter the UI operational cue.
21. Truncated relation presentation does not make operational detection incorrect.
22. Existing Task relation/profile tests remain green.
23. Existing T2 Flutter Task Profile tests remain green.
24. No migration, mutable operational-state field, LLM call, auto-detection, proactive notification, Project entity, or deploy.

Run:
- new operational-state domain/service tests;
- `tests/test_task_relations.py`;
- Task Profile REST/tool tests;
- relevant ToolRunner/Assistant contract tests;
- T2 Flutter Task Profile tests;
- domain label tests;
- Flutter analyze touched files;
- Ruff/compile touched Python;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not begin automatic obligation discovery, proactive attention/notifications, project/roadmap semantics, or deploy.
