# Current task — HOLD

No Executor task is authorized.

People PL1-G1 is implemented at `afdf088a87c0d5f5285b5cfed0c46ef4362daeb1`. Migration `0052_task_layout_positions` is the repository head. It stores one user-scoped Task layout revision and finite Task center coordinates outside `Object.metadata`. `TaskLayoutService` can read, replace a complete snapshot for the expected topology revision, and invalidate that revision without deleting stored centers. Stale or invalid snapshots fail closed. No public API, UI, relation-mutation wiring, or production migration. `tests/test_task_layout.py`: 9 passed. Production remains `666683134797948871266e84fd105f0ca0c43476`, Alembic `0051 / 0051`.

Do not begin PL1-G2 or any later slice without a new explicit authorization in this file.
