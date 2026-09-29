# Current task — PT1-H1: terminal-task safety + distinct linked-task count

## State

- PT1-A implementation under review: `4019f7deec5b8c4d83c907c192ca3e4e1e7715ce`.
- Production/runtime/origin-production: `93dd1e923dfd8df2860db390bf81cf8a0cc80802`.
- Alembic: `0051`.
- Person-side canonical Task actor bridge is directionally accepted.
- PT1 is not yet source-ready.
- People Landscape and later roadmap slices remain unauthorized.

## Goal

Close two bounded semantic mismatches without redesigning PT1-A.

## H1A — terminal Task safety

The Person-side `Связать с задачей` picker must not offer Tasks that the Person truth surface will hide immediately after mutation.

Use the canonical task lifecycle semantics from `TERMINAL_TASK_STATUSES_FOR_READS` / `is_terminal_for_reads`.

Do not offer:
- `done`;
- legacy `completed`;
- `cancelled`;
- `archived`;
- `deleted`.

Allow active non-terminal Tasks such as `open`, `in_progress`, and existing null/legacy-active status if current domain rules allow it.

Do not invent a second lifecycle list in Dart if an existing shared label/helper can represent the canonical statuses cleanly; if the client must filter locally, keep the list explicitly aligned with the backend lifecycle contract and cover it in tests.

Do not change canonical Task actor backend semantics beyond what is required for fail-closed consistency.

## H1B — distinct linked Task count

`Связанные задачи · N` must count distinct active linked Task objects, not Edge rows.

Preserve the existing meaning: graph-connected active Tasks for the Person, not only PT1 actor edges.

Requirements:
- two different actor roles on the same Task count as one linked Task;
- an actor edge plus another graph edge to the same Task still count as one Task;
- two different active Tasks count as two;
- rejected edges and inactive/terminal Tasks stay excluded as before;
- `Участие в задачах` still shows separate rows for separate actor roles.

Prefer SQL `count(distinct task.id)` / equivalent bounded query; do not materialize unbounded rows just to dedupe in Python.

## Tests

Backend:
- two roles on one active Task => two involvement rows, linked Task count = 1;
- two distinct active Tasks => count = 2;
- duplicate graph edge kinds to same Task do not inflate count;
- rejected and inactive/terminal Tasks do not count;
- existing involvement boundedness/order remains.

Flutter:
- Person Task picker excludes every terminal status listed above;
- active Task remains selectable;
- existing add/remove/confirm/reject/navigation PT1-A tests remain passing;
- metric after adding a second role to an already-linked Task does not increase the linked Task count.

Run focused backend PT1/Person truth suites, focused Flutter bridge tests, relevant Flutter analyze, Ruff and `git diff --check`.

## Scope

No migration. Alembic remains `0051`.

Do NOT:
- redesign the bridge;
- change Person consolidation;
- add social roles;
- start People Landscape;
- change Secretary/LLM context;
- deploy.

## Completion

Commit/push PT1-H1 to `main`, update `PROJECT_STATE.md`, return this file to HOLD, report SHAs/tests, and STOP.
