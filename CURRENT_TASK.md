# CURRENT_TASK

HOLD

## REL1D-HG5B — shared semantic windows for Task and People projections

Implementation: `64f72a19cbf549022f99efd0b5fe8c482e0fe3e5`

Unrooted People overview uses the canonical Task semantic window. Anchored People are projected into every window touched by their qualifying Task actor anchors. Complete unanchored People appear in every People semantic window. One shared client window index covers Task and People modes.

Checks:

- `pytest tests/test_person_graph_workspace.py` — 19 passed
- Flutter `people_overview_window_test.dart` + `graph_semantic_window_test.dart` + `people_landscape_overview_test.dart` + `person_rename_test.dart` + `person_task_bridge_test.dart` — 63 passed
- Ruff clean on touched Python
- `dart analyze` on touched Dart — 0 errors, pre-existing infos only
- `git diff --check` clean

No schema/Alembic change and no production deploy.

Production remains:
`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

Alembic remains:
`0054 / 0054`
