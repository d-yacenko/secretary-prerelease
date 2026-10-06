# CURRENT_TASK

ACTIVE

## REL1D-HG3.1 — Person task picker disambiguation and mutation feedback

### Context

Human acceptance after accepted HG3 found two client-side Person↔Task UX defects:

1. the specialized Person task/direction picker can show duplicate task titles without the same parent-context disambiguation already used by the generic relation picker;
2. removing a Person task-role can appear visually stale until a later task-role mutation/refresh.

Backend semantics already allow multiple active Task→Person actor edges. This task must not introduce or imply a one-Task-per-Person rule.

### Goal

Make Person↔Task/Direction linking deterministic and unambiguous without changing backend relation semantics.

### Required behavior

#### A. Duplicate Task title disambiguation

1. In the Person action `Связать с задачей / направлением`, duplicate Task titles must use the same display rule as the existing generic relation picker:
   - duplicate detection ignores case and repeated/edge whitespace;
   - if a duplicate Task has a confirmed current `part_of` parent, show:
     `<task title> (<parent title>)`;
   - if no confirmed parent is available, show:
     `<task title> (без родителя)`;
   - unique Task titles remain unchanged.

2. Reuse the existing canonical helper logic in `relation_target_label.dart` rather than creating a second normalization rule.

3. Fetch Task profiles/parent context only for duplicated Task results, as the generic relation picker already does. Do not add an N+1 profile fetch for every search result.

4. The rule applies equally to finite Tasks and ongoing Tasks/Directions.

#### B. Person task-role mutation feedback / serialization

5. Person task-role mutations must not overlap silently. While one add/remove/confirm/reject mutation is in flight for the rooted Person:
   - disable conflicting task-role mutation controls;
   - show a clear in-progress cue on the task-role surface;
   - do not allow a second task-role mutation to race the first.

6. After a successful remove, the authoritative rooted Person data must be reloaded before the mutation is considered complete, so the removed edge disappears without requiring another user action.

7. Removing one Task actor edge must not remove, replace, or hide unrelated actor edges for the same Person.

8. Adding a new Task actor edge must preserve every unrelated existing active Task actor edge. Multiple Tasks per Person are explicitly supported.

9. Mutation failure must be visible and recoverable. Do not silently leave a stale card that looks successful. Preserve authoritative data and allow retry.

### Explicitly out of scope

Do NOT:

- change `TASK_ACTOR_ROLES`;
- change `Task -> Person` storage direction;
- add uniqueness constraints across Person task involvement;
- add new relation types;
- add Person→Person ontology;
- change PersonRole assignments;
- change backend Task actor APIs unless a client test proves a strictly necessary compatibility defect;
- add Alembic/schema changes;
- deploy/install anything;
- touch production data;
- modify role-import image extraction in this task;
- add OCR, image resizing, image tiling, or OpenAI image-detail changes;
- resume historical HG2 repair/backfill.

### Expected implementation scope

Prefer client-only changes.

Likely relevant files:

- `client/lib/graph/graph_workspace_screen.dart`;
- `client/lib/graph/relation_target_label.dart` (reuse, not semantic rewrite);
- existing Person task bridge / relation picker tests.

Keep the change narrowly scoped. Do not refactor unrelated graph UI.

### Required tests

At minimum add/update focused Flutter tests proving:

1. Person task picker duplicate detection is case/whitespace-insensitive.
2. Two duplicate Tasks with confirmed different parents render `title (parent)`.
3. A duplicate without a confirmed parent renders `title (без родителя)`.
4. A unique Task title remains unchanged.
5. Duplicate-parent profile lookups are performed only for duplicated Task results.
6. Ongoing Task/Direction remains selectable and follows the same duplicate-label rule.
7. Two or more Task actor rows for one Person can coexist.
8. Removing one actor edge removes only that edge after the mutation/reload completes.
9. During a delayed actor mutation, conflicting task-role controls cannot start another mutation and an in-progress cue is visible.
10. Adding a new actor edge preserves an unrelated existing actor edge.
11. A failed actor mutation surfaces an error and leaves the authoritative Person task-role state usable.
12. Existing non-Person generic relation picker behavior remains unchanged.

Run the smallest focused Flutter test set covering these contracts plus existing:
- `person_task_bridge_test.dart`;
- duplicate relation-target label/picker tests.

Run Dart formatting/analyzer checks appropriate for touched files and `git diff --check`.

### Separate observed issue — NOT authorized in HG3.1

Human role-import acceptance also found visible mis-transcription of some small Cyrillic names from a raster table screenshot.

Current source review shows:
- the stored raster bytes are hash-checked and forwarded unchanged;
- Secretary does not resize/JPEG-compress the raster before role extraction;
- the OpenAI image input currently omits an explicit `detail` value.

Do not act on this finding in HG3.1. It will receive a separate Architect task after HG3.1 review.

### Completion protocol

When implementation and required checks are green:

1. update `PROJECT_STATE.md` with a concise factual HG3.1 implementation/test entry;
2. replace this file with `HOLD`, recording the implementation commit SHA and test result;
3. commit + push to canonical `main`;
4. STOP.

Do not choose or start the image-extraction follow-up or any other next phase.

Production/backend remains:
`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic remains:
`0054 / 0054`

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
