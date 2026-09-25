# Current task — Task Refinement T1: canonical Task/Commitment relations + shared profile

Person Graph G1/G1R is architect-accepted. Begin the next major domain stage: Task Refinement.

Implement only the canonical Task/Commitment relation foundation and a shared read profile.

Do not implement automatic task detection from Flow, proactive reminders, project/roadmap UI, recurring-task redesign, organization inference, LLM classification, Task Graph redesign, or production deployment in this task.

## Product model

Secretary's core ontology is:

- Actor / Person — who;
- Task / Commitment — what must happen;
- Flow — what happened / evidence / signals that create or change Tasks;
- Time — cross-cutting dimension.

A Task is a stateful open loop / commitment, not merely a verb or checklist row.

The current user remains the implicit/default owner of their own Task unless an explicit relation adds useful information. Do not require a self-Person edge for ordinary personal tasks.

## Goal

Keep canonical Tasks as existing `Object(kind="task")`.

Add a small, explicit, validated relation vocabulary so a Task can truthfully express:

- who requested it;
- who it is delegated/assigned to;
- who/what it is waiting on;
- which People participate/stakehold where useful;
- which Tasks it depends on;
- which Flow Objects are evidence/context for why it exists or changed.

Expose one bounded **Task Profile** read that both first-party UI and Assistant/MCP can consume semantically, rather than forcing each surface to reinterpret generic graph edges.

No new top-level entity is introduced.

## 1. Canonical Task relation vocabulary

Define task-specific relation constants/invariants in one domain module, e.g. `task_relations.py`.

Required Person-role relations, directed **Task -> Person**:

- `requested_by` — this Actor requested/initiated the commitment;
- `delegated_to` — user delegated/assigned execution to this Actor;
- `waiting_on` — progress/closure currently waits on this Actor;
- `involves` — Actor materially participates/stakeholds but no stronger role is asserted.

Existing relations remain canonical:

- `depends_on`: Task -> Task;
- `references`: Task -> Flow/evidence/context Object.

Do not introduce separate Task subtypes for waiting/delegated/promised/project in T1.

Do not infer any of these roles from names or communication frequency in T1.

### Direction/invariant rules

Validate:
- source of all task-specific actor relations is an active same-user Task;
- target is an active same-user Person;
- `depends_on` is Task -> Task only;
- no self-dependency;
- `references` may point to existing active same-user non-Task evidence/context Objects; preserve existing broader legacy compatibility where needed, but new T1 task-evidence writes must be validated;
- rejected/deleted endpoints fail closed;
- duplicate active same-direction same-type relation is idempotent;
- opposite direction must not be silently treated as equivalent.

Do not reinterpret existing generic `related_to` edges as one of these roles.

## 2. TaskRelationService

Add a shared service for explicit task relation writes/reads, e.g. `TaskRelationService`.

It should support bounded operations such as:
- add Actor relation;
- remove/deactivate Actor relation;
- add dependency;
- remove/deactivate dependency;
- attach evidence/reference;
- list canonical Task relations grouped by semantic role.

Reuse existing Edge rows, provenance state, soft rejection/removal conventions, and dedup helpers.

Do not physically delete historical agent/source relations where current relation-removal policy uses rejected state.

First-party explicit user writes should be `origin="user"`, `state="confirmed"`.

Assistant writes should continue to use existing proposal/approval semantics through DomainToolService / tool gateway.

## 3. Task Profile read model

Add a bounded read DTO/service, e.g. `TaskProfileService`.

Given a Task id, return:

- task object;
- effective lifecycle status;
- due/start/planned timing already present;
- actor relations grouped:
  - requested_by;
  - delegated_to;
  - waiting_on;
  - involves;
- dependencies:
  - depends_on Tasks;
  - dependent Tasks (Tasks that depend on this one);
- bounded evidence/context Objects from `references`;
- counts/truncation flags where lists exceed bounds.

Each Actor item should expose only safe Person presentation:
- person id;
- display name/title;
- optionally compact effective provider/contact cue if already available cheaply;
- never provider secrets/raw session metadata.

Do not infer missing roles.

Task Profile must be same-user, active-read safe, and operationally bounded.

## 4. First-party REST API

Add narrow first-party endpoints, for example:

- `GET /tasks/{task_id}/profile`;
- `POST /tasks/{task_id}/actors`;
- `DELETE /tasks/{task_id}/actors/{edge_id}`;
- `POST /tasks/{task_id}/dependencies`;
- `DELETE /tasks/{task_id}/dependencies/{edge_id}`;
- optional explicit evidence attach endpoint only if existing Task update API cannot safely serve the same first-party use case.

Schemas must use strict enums/UUIDs and forbid extra fields.

Do not expose generic arbitrary edge creation through these Task endpoints.

## 5. Assistant / MCP symmetry

Under **one ontology, two interfaces**, expose the same Task semantics to the model.

Add a READ tool:
- `get_task_profile(task_id)`

It should return the same semantic profile (bounded Actor roles, dependencies, evidence) and not mutate anything.

For writes, prefer extending existing Task tools rather than adding a parallel task engine.

### create_task

Extend `CreateTaskInput` minimally with optional bounded explicit relation fields such as:
- `requested_by_person_id` optional;
- `delegated_to_person_ids` bounded list;
- `waiting_on_person_ids` bounded list;
- `involved_person_ids` bounded list;
- `depends_on_task_ids` bounded list;
- existing `evidence_object_ids` stays.

All supplied ids must come from same-turn known/exposed objects under existing ToolRunner budget rules where applicable.

Creation remains one internal-write operation with the existing proposed/approved state behavior.

### update_task

Extend `UpdateTaskInput` only for **additive** relation attachment in T1:
- add Actor role relations;
- add Task dependencies;
- existing evidence attachment stays additive.

Do not make omission remove anything.

Removal remains an explicit exact-edge operation, either through:
- a task-specific remove tool, or
- existing `remove_relation(edge_id)` if relation-removal safety supports these new edge types.

If using existing `remove_relation`, update its allowlist/invariants deliberately and test exact-edge semantics.

Do not let model invent arbitrary Person/Task ids.

## 6. Role conflicts / semantics

T1 should preserve truth rather than over-normalize.

It is allowed for one Person to have multiple roles on the same Task when reality warrants it, e.g. requester + participant.

However:
- duplicate same role is idempotent;
- `delegated_to` and implicit user ownership are not contradictory;
- `waiting_on` is a current relation, not a permanent historical fact; explicit removal/rejection means no longer waiting;
- do not automatically change Task lifecycle status when actor roles change;
- do not automatically mark done when dependencies complete;
- do not auto-clear waiting_on from new messages in T1.

Those are later Task-state automation.

## 7. Legacy compatibility

Existing Tasks may have only:
- status;
- due_at;
- `references`;
- `depends_on`;
- generic `related_to`.

They must continue to work unchanged.

Task Profile should:
- show existing canonical `depends_on` and `references`;
- ignore generic `related_to` for semantic Actor roles unless/until explicitly converted by the user in a later task;
- never mutate legacy edges merely by reading.

No migration is preferred; Edge rows + existing Object fields should be sufficient.

## 8. Graph implications

Do not redesign the Graph UI in T1.

Existing graph rendering may naturally show new edge types if it already renders arbitrary edge labels, but:
- add human-readable labels for the four Task->Person role edges where necessary;
- do not add project/roadmap visualization yet;
- do not change task seeding/layout logic yet.

The next Task Refinement phases can use Task Profile as the canonical source for UI improvements.

## 9. Safety / boundedness

Required:
- all reads/writes same-user;
- active/rejected/deleted endpoint validation;
- bounded relation counts;
- deterministic ordering;
- no N+1 unbounded scans over all Objects/Edges;
- no LLM/provider calls;
- no Person creation/merge;
- no Flow mutation;
- no external side effects.

## Focused proof

Add tests proving at minimum:

1. Task -> Person `requested_by` creates one confirmed user edge.
2. Duplicate same actor-role write is idempotent.
3. Task -> Person `delegated_to`, `waiting_on`, `involves` each validate endpoint kinds.
4. Person -> Task reversed actor-role direction is rejected through Task relation APIs/services.
5. Cross-user Person fails closed.
6. Rejected/deleted Person fails closed.
7. Task -> Task `depends_on` works; non-Task target and self-dependency fail.
8. Existing dependency edge appears in Task Profile.
9. Reverse/dependent Task list is included separately.
10. Existing `references` evidence appears in Task Profile.
11. Generic `related_to` does not become an Actor role.
12. Task Profile groups Actor roles correctly and is bounded/truncated.
13. User removal/deactivation removes current `waiting_on` without deleting history.
14. Existing task lifecycle/status is unchanged by role mutations.
15. `get_task_profile` Assistant/MCP READ exposes the same role/dependency semantics.
16. `create_task` can atomically/additively attach explicit Actor roles, dependencies, and evidence under existing write-state semantics.
17. `update_task` adds roles/dependencies without removing omitted existing ones.
18. Invalid/invented/cross-user ids fail closed.
19. Existing `create_task`, `update_task`, `set_task_status`, `delete_task` behavior stays backward compatible.
20. Existing Capture `depends_on_ids` / context references remain green.
21. Person Graph rooted view may surface a Task through an actual new Task->Person role edge without special-case inference.
22. No migration, auto-detection, proactive logic, project entity, UI redesign, provider call, or deployment.

Run:
- new Task relation/profile tests;
- `tests/test_task_lifecycle.py`;
- `tests/test_direct_tasks_api.py`;
- `tests/test_task_materialization.py`;
- Assistant task reuse/tool gateway tests;
- Graph workspace + Person Graph tests;
- Capture tests using dependencies/context;
- Ruff/compile touched Python;
- relevant Flutter graph label tests only if Dart labels change;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not begin Task auto-detection, Task Graph redesign, project/roadmap semantics, proactive attention, or deploy.
