# Current task — HOLD

Task Refinement T2 is implemented and awaiting architect review.

Implementation: `38122f71193af61d703d0e8bef5e0ab6b16c692d`

The existing Graph `Задачи` detail panel loads `GET /tasks/{id}/profile` for an active Task. The section shows actor roles, outgoing and incoming dependencies, and evidence from that profile. Empty groups stay hidden. A proposed agent relation is labelled `Предложено секретарём` and is confirmed or rejected through the existing relation-decision endpoint, then the profile reloads. A known Person is added from People search by canonical id. A dependency is chosen from existing Tasks, and the current Task cannot be selected as its own dependency. Removal uses the exact actor or dependency edge id. Opening a Person switches to `Люди` and re-roots. Opening a dependency Task re-roots in `Задачи`. Opening evidence uses the existing object detail. A late profile response does not replace a newer selection. No migration, auto-detection, proactive behavior, or Project entity.

Checks:

- `client/test/graph/task_profile_ui_test.dart`: 9 passed.
- `client/test/graph/graph_proposed_relation_test.dart`: 4 passed.
- `client/test/ui/domain_labels_test.dart`: 5 passed.
- Graph screen, graph controller, People workspace, and task-management tests together: 46 passed. Three graph detail tests still fail on the unmodified task commit: `Details delete refreshes overview without deleted task`, `Details delete current root falls back to overview`, and `Details Ask Secretary does not refresh disposed Graph screen`. `delete cancel sends no DELETE` and `delete confirm sends DELETE /tasks/{id}` still look for a text button `Удалить` that `TaskManagementActions` does not render; that file was not changed.
- `tests/test_task_relations.py`: 9 passed.
- `tests/test_direct_tasks_api.py`: 14 passed. `test_deleted_task_cannot_be_edited` and `test_deleted_task_cannot_change_status` still return 404.
- Flutter analyze of touched files reports no errors. `git diff --check` clean.
- No Python changes.

No migration. Production remains exact `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`. Development migrations `0048/0049` remain unapplied. Do not start the next phase.
