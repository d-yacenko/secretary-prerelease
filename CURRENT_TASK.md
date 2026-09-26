# Current task — Task Completion Mode V7A: finite / ongoing + hybrid Direction presentation

V6 near-field local flower is accepted as the current visualization direction.

Before further dandelion geometry tuning, introduce one explicit completion/closure property on canonical Task objects so continuing activity can be shown as a distinct cluster anchor.

Do NOT create a new Direction object kind.

Canonical model remains:
- `kind=task`;
- `completion_mode=finite` for completable work;
- `completion_mode=ongoing` for continuing activity with no natural done state.

User-facing UI may call `ongoing` a “Направление” / “Деятельность”.

Do NOT infer ongoing from missing `due_at`.

No production deploy.

## 1. Database migration

Main currently has migrations through `0049`; production is still at `0047 / 0047`.

Add:
- `0050_task_completion_mode.py`;
- `down_revision = "0049"`.

Add nullable TEXT column:
- `objects.completion_mode`.

Migration upgrade:
- add the column;
- backfill every existing row with `kind='task'` and NULL completion mode to `finite`;
- leave non-task rows NULL;
- add a CHECK constraint allowing NULL or exactly `finite` / `ongoing`.

Do not hardcode any object title/id into the migration.

Downgrade:
- remove the constraint;
- drop the column.

Do not deploy/migrate production in this task.

## 2. Canonical domain semantics

Add a small domain module equivalent to `task_completion.py` with:

- `TASK_COMPLETION_FINITE = "finite"`;
- `TASK_COMPLETION_ONGOING = "ongoing"`;
- allowed-value set;
- helper for effective completion mode.

Rules:

- only `kind=task` may have a non-NULL completion mode;
- canonical new Tasks default to `finite`;
- missing/legacy Task value reads effectively as `finite`;
- non-task completion mode must be NULL;
- `due_at` does not determine completion mode.

Do not introduce a separate Direction class/kind.

## 3. Object/API support

Wire `completion_mode` through:

- SQLAlchemy `Object`;
- `ObjectCreate`;
- `ObjectUpdate`;
- `ObjectOut`;
- `ObjectOut.from_model`.

GraphService:
- new Task + omitted mode => persist `finite`;
- non-task + non-NULL mode => validation error;
- Task accepts only `finite` / `ongoing`;
- changing an object away from `kind=task` must not leave an invalid task-only completion mode.

Do not make completion mode searchable/embedded.

## 4. Task mutation

Extend `TaskPatchRequest` and `TaskMutationService.patch_task_fields` with:
- `completion_mode`.

Changing only completion mode is a valid patch.

Validation:
- `finite` and `ongoing` only;
- setting `ongoing` on a Task currently in `done` or legacy `completed` state is rejected;
- ongoing may be `open`, `in_progress`, `cancelled`, `archived`, or deleted through the existing delete path.

Task status mutation:
- if effective completion mode is `ongoing`, reject setting status `done`;
- do not change existing finite lifecycle behavior.

No operational-priority rewrite in this task.

## 5. Task creation defaults

Every canonical Task creation path must end up with effective/persisted `finite` unless explicitly supplied as ongoing by an authorized direct Task mutation/create path.

At minimum prove:
- normal ObjectCreate task;
- capture Task;
- explicit Notification -> Task acceptance path used by current product.

Do not change proposal acceptance semantics otherwise.

## 6. Client model/API

Extend `SecretaryObject` with:
- `completionMode`.

Parse `completion_mode`.

For a Task, client helper/effective getter may treat missing/null as `finite` for backward compatibility.

Extend client `TaskPatchRequest` / API JSON with optional:
- `completion_mode`.

Do not infer from dates client-side.

## 7. Task editor

In the existing Task edit dialog add a compact explicit control:

- `Задача` => `finite`;
- `Направление` => `ongoing`.

Use a segmented control / radio-like selector.

When switching:
- do not clear `due_at`;
- do not rewrite title/body;
- patch only changed fields.

If current Task is already terminal `done/completed`, selecting ongoing must surface the backend validation cleanly.

Do not add a separate Direction creation screen.

## 8. Status UI for ongoing

For an ongoing Task:
- do not offer `done` as a normal status choice;
- keep open/in-progress/cancel/archive actions consistent with existing UI;
- backend validation remains authoritative.

In Task detail/profile presentation show a concise cue equivalent to:
- `Направление · продолжается`
for ongoing.

Finite Task detail remains current behavior.

## 9. Hybrid graph Direction visual

Refine only the experimental `LOD+fCoSE` renderer.

Current startup renderer stays unchanged.

Finite Task:
- keep current Task card visual.

Ongoing Task:
- render as a distinct circular cluster-anchor node;
- use exact visual size `144 × 144 px`;
- preserve the canonical Task geographic CENTER from the existing 186×100 Task card position;
- use `Icons.all_inclusive` / infinity glyph as the primary completion-mode cue;
- show the title inside, max 3 lines;
- show a small label equivalent to `Направление`;
- use a somewhat stronger theme container/outline than finite Tasks;
- meaning must remain readable by shape + infinity icon, not color alone;
- bookmark cue may remain if currently available.

Do not persist the center-preserving display offset.

## 10. Hybrid geometry must understand ongoing node size

In `LOD+fCoSE` geometry/presentation:

- finite Tasks remain fixed at 186×100;
- ongoing Tasks are fixed 144×144 presentation obstacles centered on the same canonical Task center;
- presentation bounds must use the actual ongoing 144×144 rect;
- Flow flower / compact halo placement must avoid the actual ongoing circle bounding rect;
- fCoSE still may move Flow only, never Tasks.

Task drift is measured by canonical Task center and must remain 0 px.

## 11. Shape-aware edge endpoints

Hybrid Task-to-Task edge drawing:

- finite endpoint uses current rectangle boundary;
- ongoing endpoint should meet the circle boundary, not the invisible 144×144 square corner;
- arrows/direction remain canonical.

Do not add a router.

Hairlines to compact Flow around an ongoing anchor should start at the circle boundary.

## 12. Ongoing focus semantics

This distinction is important.

When selected Task is `finite`:
- keep V6 behavior;
- its compactable direct Flow opens into the local medium-card flower.

When selected Task is `ongoing`:
- do NOT expand its compactable Flow into medium/full Flow cards;
- keep directly attached Flow compact in its dandelion halo;
- Task-to-Task neighbors remain visible/emphasized through existing focus behavior.

Goal:
- Direction focus shows activity structure;
- finite Task focus shows working evidence/context.

Do not introduce hierarchy/part_of yet.

## 13. Existing data

Do NOT hardcode or automatically mutate:
- “Публикации в научной прессе”
or any other user title/id in migration/code/tests.

The normal editor/API must make it possible for the human to switch that existing Task to `Направление` after applying the migration in the development environment.

Record the exact manual UI action in `PROJECT_STATE.md`.

Do not mutate production user data.

## 14. Fixtures / proof cases

Add focused cases:

### A. Finite default
Existing/new Task without explicit mode reads/persists as finite.

### B. Ongoing mutation
Patch finite -> ongoing -> finite.

### C. Lifecycle
Ongoing rejects `done`; archived/cancelled remain allowed.

### D. Direction visual
One ongoing central Task with several finite Task neighbors.

Expected:
- round 144×144 ongoing node;
- finite neighbors remain rectangular;
- center stays at canonical geography;
- edges hit circle boundary.

### E. Ongoing focus
Ongoing selected with direct Flow + Task neighbors.

Expected:
- Flow remains compact;
- Task neighbors stay normal;
- no local full-Flow flower.

### F. Finite focus
Finite selected under an ongoing cluster.

Expected:
- finite Task opens the current V6 local Flow flower.

## 15. Scope exclusions

Do not implement:
- `part_of` / `contains`;
- Direction object kind;
- automatic LLM classification into ongoing;
- automatic title-based backfill;
- dandelion radial/angle polish beyond adapting to the ongoing circle;
- far-horizon semantic zoom;
- Areas/islands;
- Graphviz;
- new layout dependency;
- production deploy;
- DuckDB fix.

The dandelion distribution polish is the NEXT separate task after human visual review of ongoing centers.

## Focused proof

At minimum prove:

1. Alembic chain `0049 -> 0050` is valid.
2. Migration backfills existing task rows to finite and leaves non-task NULL.
3. New canonical Task defaults to finite.
4. Invalid/non-task completion mode is rejected.
5. ObjectOut/client model carry completion mode.
6. Task PATCH can change completion mode only.
7. Ongoing rejects status done.
8. Finite status behavior remains unchanged.
9. Existing notification-to-Task acceptance still produces finite Task.
10. Task editor sends explicit mode and does not infer from due date.
11. Ongoing status menu does not offer done.
12. Current renderer remains startup/default and unchanged visually.
13. Hybrid finite Task stays rectangular.
14. Hybrid ongoing Task renders 144×144 circular with infinity cue.
15. Ongoing visual center equals canonical Task center.
16. Hybrid edges/hairlines meet ongoing circle boundary.
17. Ongoing selection keeps Flow compact.
18. Finite selection keeps V6 local selected flower.
19. Task center drift stays 0 px across finite/ongoing focus changes.
20. Existing V1/V2/V3B/V4/V5/V6 relevant tests remain at known baseline.
21. No hierarchy/backend behavior beyond completion mode and no deploy.

Run:
- backend migration tests / Alembic upgrade proof through 0050 on test DB;
- focused GraphService/Object schema tests;
- Task mutation/status tests;
- notification acceptance Task tests;
- backend Task Profile/Today regression tests;
- client API model/Task edit/status tests;
- current Graph tests;
- V4/V5/V6 hybrid tests;
- new ongoing hybrid visual/projection tests;
- Task Profile UI tests;
- Flutter analyze touched files;
- `flutter build linux --debug`;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA;
- record migration revision and exact backfill behavior;
- record completion-mode lifecycle rules;
- record ongoing node visual dimensions/style;
- record Task center-drift proof;
- record that user data was NOT title/id-hardcoded;
- record how the human can switch an existing Task to “Направление” in the editor;
- do not begin dandelion polish automatically;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Human real-data visual review decides the next dandelion/radial geometry task.
