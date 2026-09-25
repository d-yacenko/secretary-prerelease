# Current task — Task Refinement T1R: proposal-state truth + Task Profile tool symmetry

Architect review of Task Refinement T1 implementation `2f6f1954e0414657a6eb5892cc5f2b8682493d26` confirms the core model:
- Task remains `Object(kind="task")`;
- Task->Person roles are `requested_by`, `delegated_to`, `waiting_on`, `involves`;
- Task->Task dependency is `depends_on`;
- Task->Flow/context evidence is `references`;
- no new top-level entity or migration;
- Graph labels and bounded Task Profile direction are correct.

T1 is not yet architect-accepted because four narrow proposal/state/tool-boundary defects remain. Fix only these.

Do not start Task auto-detection, proactive behavior, project/roadmap semantics, Task Graph redesign, or deploy.

Known unrelated baseline failures remain outside this task, including the deleted-task expectations, `DECISIONS.md` taxonomy expectation, and rooted deleted-task Graph expectation already present on the T1 task commit.

## 1. Explicit user confirmation must not be swallowed by a proposed duplicate

Current `TaskRelationService._add_edge()` treats every existing edge with `state != rejected` as an idempotent duplicate.

This creates an incorrect case:

1. Assistant creates/proposes `Task -> Person requested_by`, edge is `origin=agent, state=proposed`;
2. user explicitly adds the exact same relation through first-party Task API;
3. service returns the existing proposed edge unchanged.

The explicit user fact therefore never becomes confirmed.

### Required state-aware deduplication

For the same exact `source_id + target_id + type`:

- existing **confirmed active** relation + any equivalent add -> idempotent, no duplicate;
- existing **proposed active** relation + another proposed add -> idempotent;
- existing **proposed active** relation + explicit first-party `origin=user, state=confirmed` add:
  - the resulting current relation must be confirmed;
  - preserve truthful history/provenance;
  - preferred behavior: mark/supersede the old proposed edge as rejected and create one new `origin=user, state=confirmed` edge;
  - do not silently mutate an agent proposal into a user-origin historical fact;
- existing confirmed relation + later agent proposal -> return the confirmed relation, do not create a proposed duplicate;
- rejected historical rows do not block a new active relation.

Apply the same semantics to:
- Actor roles;
- dependencies;
- evidence references handled by `TaskRelationService`.

At most one effective active edge for one exact direction/type should remain after an explicit user confirmation.

Do not reinterpret the opposite direction as equivalent.

## 2. Task Profile must preserve relation state/provenance

Current Task Profile includes all edges with `state != rejected`, but `TaskActorOut` / `TaskLinkOut` expose only IDs/title/kind.

Therefore a `proposed` Assistant relation is presented indistinguishably from a `confirmed` user relation.

### Required

Extend Task Profile relation items with bounded semantic provenance, at minimum:
- `edge_state`;
- `edge_origin`;
- `edge_confidence` when present/useful.

Applies to:
- requested_by;
- delegated_to;
- waiting_on;
- involves;
- depends_on;
- dependent_tasks;
- evidence.

Rules:
- confirmed and proposed active relations may both be returned because the profile is shared by UI and Assistant/MCP;
- rejected relations stay excluded from the effective profile;
- consumers can always distinguish proposed from confirmed;
- do not make first-party UI and Assistant use different hidden interpretations of the same profile;
- update Assistant tool contract/serialization schemas accordingly;
- no new Task state is introduced.

The task Object already exposes its own `state`; keep that unchanged.

## 3. `get_task_profile` must be a complete same-turn READ source

`get_task_profile` is registered with `ToolPermission.READ`, and `reference_ids.py` already knows how to parse its object IDs, but ToolRunner currently omits it from `_READ_TOOLS`.

As a result, Person/Task/evidence IDs seen in the profile are not promoted into `_seen_object_ids`.

Also `collect_seen_edge_ids_from_bounded_tool()` does not collect Task Profile edge IDs.

This makes the model able to read a Task Profile but unable to safely act on what it just saw.

### Required

- add `get_task_profile` to the normal bounded READ path in ToolRunner;
- after model-visible output is committed, profile IDs become same-turn seen object IDs:
  - task id;
  - actor Person ids;
  - dependency/dependent Task ids;
  - evidence object ids;
- collect all visible `edge_id` values from Task Profile into the same-turn seen-edge allowlist;
- this must allow a subsequent valid `remove_relation(edge_id)` from the same profile;
- this must allow a subsequent `create_task` / `update_task` to reference an Actor/dependency just exposed in the profile;
- invented/unseen object or edge IDs remain blocked;
- preserve the existing requirement that the target task id itself must have been exposed before `get_task_profile`.

Do not broaden generic mutation allowlists.

## 4. Prevalidate all explicit create-task relation targets before mutation

Current `DomainToolService.create_task()` creates the Task first and then validates/attaches Actor/dependency relations incrementally.

Interactive Assistant sessions roll back failures externally, but the domain service itself should not depend on every caller remembering to roll back a partially-mutated session.

### Required

Before creating the Task Object, validate and deduplicate all supplied:
- `requested_by_person_id`;
- `delegated_to_person_ids`;
- `waiting_on_person_ids`;
- `involved_person_ids`;
- `depends_on_task_ids`;
- existing `evidence_object_ids`.

Validation must ensure:
- same user;
- expected kind;
- active/not rejected/not deleted;
- bounded input caps already defined;
- no provider/LLM lookup.

Only after all supplied endpoints are valid should Task creation and edge attachment begin.

A failed relation target must leave:
- no newly created Task;
- no newly created Task relation/evidence edges;
when the caller uses the service in the same session and catches the error.

For `update_task`, avoid partial relation attachment when one supplied target in the same request is invalid: prevalidate the full relation batch before adding any of its edges.

Field edits/evidence/relation updates should preserve existing transaction semantics; do not create a new transaction manager inside the domain service.

## 5. Existing removal semantics

Keep:
- exact edge removal/rejection;
- historical row preservation;
- role changes do not alter Task lifecycle;
- source/system structural edges remain protected;
- new Task relation types remain removable only under the existing origin/type safety policy.

When a proposed relation is superseded by an explicit user-confirmed relation, the historical proposed edge must not remain effective in Task Profile.

## Focused proof

Add/extend tests proving at minimum:

1. Agent/proposed Actor role + first-party explicit same role -> old proposal no longer effective, one confirmed user-origin relation is current.
2. Same behavior for dependency.
3. Same behavior for evidence reference through `TaskRelationService`.
4. Repeating the explicit confirmed write is idempotent.
5. Existing confirmed relation + later proposed add does not create a second active edge.
6. Proposed + proposed duplicate is idempotent.
7. Task Profile returns `edge_state` and `edge_origin` for Actor relations.
8. Task Profile returns state/origin for dependency/evidence links.
9. Rejected historical edge is absent from current profile.
10. A proposed relation remains visibly `proposed`, not silently represented as confirmed.
11. `get_task_profile` output promotes visible Actor/Task/evidence IDs into same-turn seen-object IDs after commit.
12. A subsequent `update_task` can use a Person/dependency id learned only from `get_task_profile`.
13. Task Profile edge IDs become same-turn seen-edge IDs.
14. A subsequent `remove_relation(edge_id)` can target an exact removable edge learned only from `get_task_profile`.
15. An invented object id remains rejected after profile read.
16. An invented edge id remains rejected after profile read.
17. `create_task` with one invalid Actor/dependency among otherwise valid relation inputs leaves no newly created Task or edges when the service error is caught in the same session.
18. `update_task` with one invalid relation target creates none of that request's new relation edges.
19. Existing Task relation/profile T1 tests remain green.
20. Existing Task lifecycle/direct API/materialization/tool gateway/domain tool/Capture/Graph/Person Graph tests remain green except documented baseline failures.
21. No migration, auto-detection, proactive logic, project entity, UI redesign, provider call, or deploy.

Run:
- `tests/test_task_relations.py`;
- `tests/test_tool_gateway.py`;
- `tests/test_domain_tools.py`;
- `tests/test_task_lifecycle.py`;
- `tests/test_direct_tasks_api.py`;
- `tests/test_task_materialization.py`;
- Capture tests;
- Graph workspace + Person Graph tests;
- relevant Assistant reference-id/tool-output tests;
- Ruff/compile touched Python;
- relevant Flutter domain-label tests only if Dart changes;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose the next Task Refinement phase and do not deploy.
