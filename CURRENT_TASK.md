# Current task — HOLD

No Executor task is authorized.

People PL1-G2 is implemented at `63524b0896fa2ded98c1b2b2fcba5521817f8bd5`. Canonical Task geography is readable and replaceable at `GET`/`PUT /graph/task-layout`, and `GET /graph/task-layout/topology` returns the complete eligible Task set plus map-affecting Task↔Task edges. A snapshot is usable only when it matches the current topology revision and covers every current eligible Task. Affecting relation changes and a newly eligible Task advance an existing revision; actor links, evidence, and ordinary Task edits do not. Alembic head remains `0052`. Focused backend tests: 34 passed. Production remains `666683134797948871266e84fd105f0ca0c43476`, Alembic `0051 / 0051`.

Do not begin PL1-G3 or any later slice without a new explicit authorization in this file.
