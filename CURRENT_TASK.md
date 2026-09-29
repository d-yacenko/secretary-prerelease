# Current task — HOLD

People PL1-C is implemented at `6babdd490cdc4bc64a60eeb762967a383f9c19b1`.

The People workspace read now carries a separate Task context: `landscape_tasks`, `landscape_task_edges`, and `landscape_task_context_complete`. Complete Person anchor sets expand to full confirmed `part_of` constellations. The cap is `PEOPLE_LANDSCAPE_TASK_CONTEXT_CAP = 500`. Overflow and an unresolved anchor fail closed with empty arrays and `complete=false`.

People UI, coordinates, a new endpoint, and production were not changed.

No next slice is authorized.
