# Current task — HOLD

GFX-B is complete at `cf812130c59c45eee25a3a96720c0f0fe99b3c29`.

Tasks mode can drag the existing `part_of` relation from a Task-card handle. The dragged Task is the child and the drop Task is the parent. The request is `{"source_id","target_id","type":"part_of"}`. A solid directed preview follows the pointer and is discarded on release. A valid drop uses the existing relation create and topology refresh. A rejected drop shows the backend message and leaves the graph unchanged. A second completion while one request is in flight is ignored. People mode, Person nodes, and non-Task nodes do not show these handles. «Добавить связь» is unchanged, including GFX-A duplicate-title disambiguation and the other relation types.

No new relation type, schema, Alembic, production deploy, or further Graph polish. GUX1 remains paused. STOP.
