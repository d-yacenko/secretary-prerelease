# CURRENT_TASK

ACTIVE

## REL1D-HG3 — Person relation UX cleanup

### Context / Architect decision

The current Person detail surface mixes two different relation vocabularies:

1. generic graph relations:
   `related_to`, `references`, `depends_on` (and `part_of` for Task sources);
2. canonical Task actor roles:
   `requested_by`, `delegated_to`, `waiting_on`, `involves`.

For Person↔Task/Direction interaction, the second vocabulary is canonical.
Task actor edges remain stored in the existing direction `Task -> Person`.
A Direction is still a Task with ongoing completion semantics and does not get a separate actor vocabulary.

The Person detail UI must therefore stop presenting generic graph relation creation as the normal way to relate a Person to work.

This task is UX/semantic cleanup only. It does NOT authorize a new Person social graph.

### Goal

Make the Person detail relation workflow expose one clear, domain-specific action for linking a Person to a Task/Direction through the four existing Task actor roles, while keeping generic relation creation unchanged for non-Person objects.

### Required behavior

1. On a selected/rooted `person`, the relation action must NOT open the generic relation picker containing:
   - `Связано с` / `related_to`;
   - `Ссылается на` / `references`;
   - `Зависит от` / `depends_on`.

2. Instead, the Person surface must expose a clearly named action equivalent to:
   `Связать с задачей / направлением`
   and reuse the existing specialized Person↔Task dialog/flow.

3. That Person↔Task/Direction flow must offer exactly the existing canonical actor roles:
   - `requested_by`;
   - `delegated_to`;
   - `waiting_on`;
   - `involves`.

4. User-facing wording must be consistent between:
   - the role chooser;
   - the Person detail list of existing task involvement;
   - the confirmation/fact summary.
   Preserve the existing role semantics. Do not broaden `delegated_to` into a new generic "responsible" concept.

5. The specialized flow must continue to:
   - search only active `task` objects;
   - include ongoing Tasks/Directions;
   - exclude terminal/deleted tasks using the existing status rules;
   - write through the existing Task actor API;
   - preserve canonical storage direction `Task -> Person`.

6. Generic relation creation for non-Person objects must remain unchanged.

7. Existing stored edges must not be migrated, deleted, reversed, rewritten, or silently reclassified by this task. If legacy generic Person edges are encountered, leave their stored data untouched.

### Explicitly out of scope

Do NOT:

- add new relation/edge types;
- add Person→Person relations such as `manager_of`, `colleague`, `friend`, `works_with`, etc.;
- add Organization ontology or `member_of` / `role_at`;
- change `PersonRoleTerm` / `PersonRoleAssignment` semantics;
- change backend Task actor semantics or direction;
- change `requested_by`, `delegated_to`, `waiting_on`, `involves` storage contracts;
- change generic relation semantics for other object kinds;
- add schema/Alembic migrations;
- modify production data;
- deploy/install anything;
- run provider/model calls;
- resume historical HG2 repair/backfill.

### Expected implementation scope

Prefer a client-only change.

Likely relevant existing surfaces include:

- `client/lib/graph/graph_workspace_screen.dart`;
- `client/lib/ui/domain_labels.dart`;
- existing Person↔Task bridge tests;
- existing generic relation picker tests.

Do not broaden scope merely because nearby graph/relation code could be refactored.

### Required tests

At minimum add/update focused tests proving:

1. Person detail does not offer the generic `related_to/references/depends_on` creation choices.
2. Person detail opens the specialized Task/Direction link flow.
3. The specialized flow exposes exactly the four canonical actor roles.
4. An ongoing Task/Direction remains selectable.
5. A terminal Task remains excluded.
6. Creating a Person↔Task role still calls the existing Task actor endpoint with the selected role and Person.
7. Existing Person task-role presentation uses the same user-facing vocabulary as the chooser.
8. A non-Person object still receives the existing generic relation picker unchanged.

Run the smallest focused Flutter test set that covers these contracts, including the existing Person task bridge and relation-picker coverage. Run formatting/analyzer checks appropriate for the touched Dart files and `git diff --check`.

### Completion protocol

When implementation and required checks are green:

1. update `PROJECT_STATE.md` with a concise factual HG3 implementation/test entry;
2. replace this file with `HOLD`, recording the implementation commit SHA and test result;
3. commit + push to canonical `main`;
4. STOP.

Do not choose or start the next phase.

Production/backend must remain:
`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic must remain:
`0054 / 0054`

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
