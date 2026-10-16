# CURRENT_TASK

HOLD

## REL1D-HG6D — single-flight Person hydration and visible role API failures

### Status

Implementation complete. No backend, pool, schema, HTTP timeout, production, or follow-on phase is included.

Implementation:
`3ab15474e7bfd6c5e427b713d8c49092b08b684b`

### Behavior

Background rooted Person hydration is latest-target single-flight: one active `GET /graph/people-workspace` and at most one replaceable pending Person. Overview selection still opens the summary immediately. Generations are captured when that request starts. Rename, role, and Task-actor generations stay independent. Task-actor reconciliation remains its own single-flight path.

Role-term search failures show the sanitized API message, clear stale suggestions, and keep `Использовать роль «…»` for a non-empty typed role. Assign and retract failures keep the current role state and show the sanitized API message. Successful mutations still patch the returned assignment locally.

### Checks

Flutter, all passed (103):

- `person_authoring_test.dart` 12
- `person_roles_section_test.dart` 14
- `person_rename_test.dart` 9
- `person_task_bridge_test.dart` 34
- `person_context_packing_test.dart` 9
- `people_landscape_overview_test.dart` 13
- `people_landscape_screen_test.dart` 5
- `people_overview_window_test.dart` 6
- `graph_semantic_window_test.dart` 1

`dart format` on touched Dart. `dart analyze` on touched Dart: 0 errors, pre-existing infos only. `git diff --check` clean.

### Stop

Do not deploy and do not start backend optimization from this HOLD.
