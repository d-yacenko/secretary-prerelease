# CURRENT_TASK

HOLD

## REL1D-HG5B.1 — bound shared People semantic projection without changing topology semantics

Implementation: `3bbf8759f1778b5302aeec58c6d60e0601071737`

HG5B topology and the client shared semantic window stay as implemented. People overview now packs canonical Task windows once per request, checks incomplete/unmapped anchors with bounded SQL, and applies the completeness ceiling before loading the Person rows.

Checks:

- `pytest tests/test_person_graph_workspace.py` — 21 passed
- Flutter `people_overview_window_test.dart` + `graph_semantic_window_test.dart` + `people_landscape_overview_test.dart` + `person_rename_test.dart` + `person_task_bridge_test.dart` — 63 passed
- Ruff clean on touched Python
- `git diff --check` clean

No schema/Alembic change and no production deploy.

Production remains:
`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

Alembic remains:
`0054 / 0054`
