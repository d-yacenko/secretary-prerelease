# Current task — HOLD

Task completion mode V7A is recorded. Implementation `ae476abad7ff00b90c23c3cc4769dfd9d15d2a08`.

Do not start dandelion/radial polish from this result.
Do not start `part_of` or a separate Direction object kind.

- Alembic `0050` revises `0049`. Existing task rows with a NULL mode are backfilled to `finite`. Non-task rows stay NULL. No title or id is hardcoded. Production was not migrated.
- Ongoing is still `kind=task`. It rejects `done` / `completed` and may stay open, in progress, cancelled, archived, or deleted. Finite lifecycle is unchanged. A missing mode reads as `finite`. `due_at` is not the signal.
- In `LOD+fCoSE`, an ongoing Task is a 144×144 circle centered on the canonical Task center, with an infinity glyph and the label `Направление`. Its direct Flow stays compact. A finite Task still opens the local V6 flower. Canonical Task center drift is 0 px.
- A person switches an existing Task from the editor: «Редактировать», then «Направление», then «Сохранить». That patch sends only `completion_mode`.
- Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.
