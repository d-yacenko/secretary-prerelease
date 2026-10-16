# CURRENT_TASK

## HOLD

REL1D-HG6A is implemented. No further Executor work is authorized.

Implementation: `82f47d2f0e53da1069709186df051f8d543c43c5`

Client-only. An unrooted Person with an overview presentation opens immediately while rooted detail hydrates in the background. Role assign/retract patches the returned assignment locally. Context is a deterministic client visual and local packing signal inside the existing Task-anchor cluster and the unanchored shelf.

Checks, all passed:

- `person_authoring_test.dart` 7
- `person_context_packing_test.dart` 7
- `person_roles_section_test.dart` 9
- `people_landscape_overview_test.dart` 13
- `people_overview_window_test.dart` 6
- `person_rename_test.dart` 9
- `person_task_bridge_test.dart` 34
- `people_landscape_screen_test.dart` 5
- `graph_semantic_window_test.dart` 1

Total 91. `dart analyze` on touched Dart: 0 errors, pre-existing infos only. `git diff --check` clean.

No backend, schema, production, identity-candidate, Task topology, or Agent/harness change.

Production remains:
`0031f531d1215970093bea7add44fcd2259ec71b`

Alembic remains:
`0054 / 0054`

Do not deploy. Do not start the next phase.
