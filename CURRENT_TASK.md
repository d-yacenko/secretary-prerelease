# Current task — Task Composition V8B1: canonical part_of semantics + profile/UI observability

V8A-R is accepted.

Introduce canonical Task composition relation `part_of` as the next semantic stage.

This task is intentionally limited to relation semantics, validation, profile/tool/UI observability, and basic map rendering.

Do NOT build hierarchical global layout yet.
Do NOT migrate legacy `contains`.
Do NOT change operational-state semantics.
Do NOT deploy production.

No new dependency.
No database migration is expected: Edge.type is already a string.

## 1. Canonical relation

Add to the canonical Task relation vocabulary:

- `PART_OF = "part_of"`.

Canonical orientation:

- CHILD / SOURCE -> PARENT / TARGET.

Meaning:
- source Task is a compositional child/part of target Task.

Do not introduce:
- `contains` as an inverse canonical relation;
- a second stored parent->child edge.

Children are read by querying incoming `part_of` edges to the parent.

## 2. Composition is a forest

For active/non-rejected composition:

- a Task may have zero or one `part_of` parent;
- a parent may have any number of children;
- self-parent is invalid;
- cycles are invalid.

Treat all non-rejected `part_of` edges as occupying the parent slot for this first stage, including proposed edges. This keeps even proposed composition unambiguous.

Do not allow a second active/proposed parent for the same child.

Cross-cutting semantics should continue to use:
- `related_to`;
- labels;
- `depends_on`;
- other existing relations.

Do not model multiple composition parents in V8B1.

## 3. Completion-mode compatibility

Use V7A completion modes.

Allowed:

- finite child -> finite parent;
- finite child -> ongoing parent;
- ongoing child -> ongoing parent.

Forbidden:

- ongoing child -> finite parent.

Reason:
- a finite parent cannot compositionally contain a child whose work is definitionally continuous.

Validate this whenever a `part_of` edge is created/proposed/confirmed.

## 4. Completion-mode mutation must preserve composition validity

When changing an existing Task's `completion_mode`:

### finite -> ongoing
Reject if the Task currently has an active/non-rejected finite parent.

### ongoing -> finite
Reject if the Task currently has any active/non-rejected ongoing child.

More generally:
- after the proposed mode change, every adjacent active `part_of` edge must still satisfy the compatibility matrix.

Do not silently detach children/parent.
Return a clear validation error.

## 5. Central composition validator

Introduce a small backend domain/service boundary equivalent to:

- `TaskCompositionService` or `task_composition.py`.

It must provide reusable validation for:

- endpoint kinds;
- same-user active endpoints;
- self-link;
- single parent;
- cycle detection;
- completion-mode compatibility;
- completion-mode change compatibility;
- confirmation-time revalidation.

Do not duplicate composition rules independently in:
- REST relation creation;
- assistant tool writes;
- relation confirmation;
- Task mutation.

All composition write paths should call the same rules.

## 6. User REST relation creation

Extend first-party relation creation to allow:

- `part_of`.

When `RelationService.create_relation(..., "part_of")` is called:

- source and target must both be Tasks;
- run canonical composition validation;
- create confirmed user-origin edge only if valid;
- exact duplicate remains idempotent.

If the child already has another active parent:
- reject;
- do NOT silently reparent in this first stage.

User can explicitly remove the old relation before assigning another parent.

Do not auto-reject the old parent edge.

## 7. Generic GraphService safety

Because assistant/domain write paths can create generic edges, ensure `GraphService.create_edge` cannot bypass `part_of` endpoint invariants.

At minimum for `type=part_of`:
- both endpoints must be Task;
- self/cycle/single-parent/completion compatibility must be enforced through the shared validator.

Avoid recursive GraphService <-> composition-service construction.

Refactor cleanly if needed so the validator can query through the SQLAlchemy session directly.

## 8. Proposed relation / confirmation safety

Assistant-origin proposed `part_of` is allowed only if it already satisfies:
- endpoint;
- single-parent;
- cycle;
- completion-mode rules.

At relation decision time:
- revalidate before changing a proposed `part_of` to confirmed;
- another change may have made the old proposal invalid.

If no longer valid:
- confirmation returns validation error;
- do not mutate the proposal to confirmed.

Reject decision remains normal.

## 9. Assistant tool observability/write

The existing generic `link_objects` tool may use:

- `relation_type="part_of"`.

It must receive the same shared validation through the canonical write path.

Update tool description/schema documentation so the model knows:

- `part_of` means child/source -> parent/target;
- both endpoints must be Tasks;
- each child has at most one active parent;
- it is composition, not dependency.

Do not add a second composition tool unless strictly necessary.

Keep existing domain write mode semantics:
- proposed mode -> proposed edge;
- approved-confirmed mode -> confirmed edge.

## 10. Task Profile

Extend Task Profile with explicit composition projection.

Add fields equivalent to:

- `parent_task: TaskLinkOut | None`;
- `child_tasks: list[TaskLinkOut]`;
- `child_tasks_truncated: bool`.

Parent:
- outgoing `part_of` from Task;
- at most one due to invariant.

Children:
- incoming `part_of` to Task.

Keep:
- `depends_on` / `dependent_tasks` separate.

Do not merge composition and dependency.

## 11. Client Task Profile

Parse the new fields.

In Task Profile UI add separate sections equivalent to:

- `Входит в` — parent Task;
- `Состав` — child Tasks.

Do not call dependency a parent/child.

Clicking parent/child should navigate/re-root using the existing Task navigation behavior.

Show edge provenance/state using existing conventions where practical.

## 12. Relation labels / audit panel

Add a human label for `part_of`, equivalent to:

- `часть` / `входит в`.

In the relation audit panel it must still expose canonical orientation:

`Child —[входит в]→ Parent`.

If Parent is selected, do NOT reverse canonical direction merely for wording.

The selected endpoint may be shown as `Этот объект`, but source -> target truth remains.

## 13. Tasks-map edge presentation

Add explicit `part_of` presentation.

Render:

- structural solid line;
- clear arrowhead source/child -> target/parent;
- stronger than light `references`;
- not dashed like `depends_on`.

Do not orient by visual center/root.
Do not change layout positions in V8B1.

It is acceptable that the parent is spatially anywhere in the current stable geography.

V8B2 will evaluate hierarchy-aware geography separately.

## 14. Legacy contains

Do NOT:

- migrate `contains` edges;
- reinterpret them as `part_of`;
- reverse them;
- automatically create `part_of` from them.

Legacy `contains` keeps its current semantics and map arrow.

Record in PROJECT_STATE that future cleanup/migration, if any, requires human review.

## 15. No automatic status semantics yet

In V8B1, `part_of` does NOT:

- block parent completion;
- auto-complete parent;
- auto-complete child;
- inherit status;
- inherit due dates;
- change operational state;
- change Today inclusion;
- propagate archive/delete.

This is deliberate staging.

Only completion-mode compatibility is enforced now.

## 16. No automatic parent inference

Do not infer `part_of` from:

- title;
- due dates;
- proximity in graph;
- shared Flow;
- shared labels;
- LLM classification without an explicit relation write.

Secretary may create/propose it only through the canonical relation tool/write.

## 17. Focused backend proof

Add tests proving at minimum:

1. `PART_OF` is canonical Task relation vocabulary.
2. finite child -> finite parent allowed.
3. finite child -> ongoing parent allowed.
4. ongoing child -> ongoing parent allowed.
5. ongoing child -> finite parent rejected.
6. non-Task endpoint rejected.
7. self-parent rejected.
8. second non-rejected parent rejected.
9. cycle A->B, B->C, C->A rejected.
10. duplicate same child->same parent is idempotent where existing relation API is idempotent.
11. proposed `part_of` occupies the one-parent slot.
12. confirmation revalidates composition.
13. completion-mode change cannot invalidate parent compatibility.
14. completion-mode change cannot invalidate child compatibility.
15. RelationService user create supports `part_of`.
16. assistant `link_objects` supports `part_of` with child/source -> parent/target.
17. Task Profile returns parent_task.
18. Task Profile returns child_tasks.
19. dependency fields remain separate and unchanged.
20. no operational-state/Today behavior changes.

## 18. Focused client proof

Add/update tests proving:

1. client Task Profile parses parent/children.
2. profile shows `Входит в` separately.
3. profile shows `Состав` separately.
4. clicking parent/child uses normal Task navigation.
5. relation audit text for `part_of` is child -> parent.
6. map `part_of` arrow is source -> target.
7. `part_of` line is structural/solid, not dependency dashed.
8. focus/root changes do not flip it.
9. finite/ongoing map behavior remains V7 baseline.
10. V8A-R existing relation grammar remains unchanged for other types.

## 19. Scope exclusions

Do not implement:

- hierarchy-aware layout/repositioning;
- automatic root placement;
- tree collapse/expand;
- status completion propagation;
- parent done guard;
- due-date inheritance;
- operational-state inheritance;
- multiple parents;
- Direction kind;
- migration of `contains`;
- far semantic zoom;
- new layout dependency;
- production deploy;
- DuckDB fix.

## Run

Run at minimum:

- focused Task composition backend tests;
- RelationService tests;
- RelationDecisionService tests;
- DomainToolService/link_objects tests;
- Task mutation completion-mode tests;
- Task Profile backend tests;
- Today/operational regression tests;
- client Task Profile tests;
- V8A-R relation presentation tests;
- V7A/V7B graph regression tests;
- Flutter analyze touched files;
- `flutter build linux --debug`;
- `git diff --check`.

## Completion

When complete:

- record implementation SHA;
- record exact `part_of` orientation;
- record forest/single-parent/cycle rules;
- record completion-mode compatibility matrix;
- record confirmation-time revalidation behavior;
- record Task Profile fields;
- record that operational/status semantics were intentionally NOT changed;
- record that legacy `contains` was untouched;
- do not begin hierarchy-aware layout automatically;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Architect/human review decides V8B2 hierarchy-aware map projection next.
