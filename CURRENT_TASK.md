# Current task — HOLD

Visual Task Map V2R ELK geometry spike is recorded. Implementation `d43b2932f758014b1033ba94f20aef20902f4984`.

Do not start islands, Areas, or compound semantic grouping.
Do not choose a final graph technology from this result.
Do not fix `dart_duckdb`.

- Dependency: `elk` 0.2.0. Lock delta is only that package. `graphview` stays 1.5.1. The current Graph renderer remains the default. V1 stays available as `Эксперимент`. V2 is a third Task renderer, `ELK`. People mode stays on the current renderer.
- `package:elk` is imported only by `client/lib/graph/elk_task_map_engine.dart`. Canonical models stay free of ELK types. The product scene for a selected Task is the loaded center, its direct neighbors, and existing edges. `TaskMapScene.groupIds` stays empty.
- Flower fixture, selected center: 16 nodes, 15 edges, layout succeeded. Overlaps 0. Routed edges 15. Edges with a bend 14. Unrelated-node intersections 0. Repeatable. Adding one evidence leaf moved 16/16 common nodes.
- Cluster fixture, full scene: 8 Tasks, 20 evidence nodes, 28 nodes, 30 edges, layout succeeded. Overlaps 0. Routed edges 30. Edges with a bend 22. Unrelated-node intersections 0. Repeatable. Adding one evidence leaf moved 28/28 common nodes.
- `ElkNode.x` / `ElkNode.y` with `ElkCycleBreaking.interactive` did not pin nodes. Replaying the computed coordinates moved 0 nodes, and shifting every prior to `(4000, 4000)` also moved 0 nodes away from the unhinted layout.
- ELK 0.2.0 is viable as a geometry engine for a later visual experiment. This spike does not select it, GraphView, or another engine. One-leaf movement still covers the whole measured field, and the public prior-position API is not a fixed-node constraint.
- Checks on Flutter 3.47.5 / Dart 3.13.4: `flutter pub get` exit 0. New V2 files analyze with no issues. V2 tests 7 passed. V1 Task Map tests 19 passed. Existing graph workspace, controller, layout, proposed-relation, people, and Task Profile tests: 67 passed, 3 failed. Those three remain `Details delete refreshes overview without deleted task`, `Details delete current root falls back to overview`, and `Details Ask Secretary does not refresh disposed Graph screen`. Linux debug succeeded: `build/linux/x64/debug/bundle/personal_secretary`. `git diff --check` clean.
- Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.
