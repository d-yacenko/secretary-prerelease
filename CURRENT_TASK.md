# CURRENT_TASK

HOLD

## REL1D-HG3.1 — Person task picker disambiguation and mutation feedback

ARCHITECT ACCEPTED.

Implementation: `daf3cde7b0bcecd459b11583db9a0ee5a053d650`.

Architect acceptance ledger: `5e8d983da406f365d5e816d4a5f8ccb0ed151556`.

Focused Flutter tests: 20 passed, 0 failed (`person_task_bridge`, `person_truth_surface`, `relation_target_label`, `graph_relation_target_disambiguation`, `graph_part_of_dialog`). `dart analyze` on the touched files exited 0 with 7 pre-existing info notices in the generic relation dialog. `git diff --check` was clean.

Production/backend remains `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`.

Alembic remains `0054 / 0054`.

No Executor coding task is active.

Human recheck should now verify in a rebuilt client:
1. duplicate Task/Direction labels are disambiguated with confirmed parent context;
2. removing one Person Task actor edge disappears immediately after the mutation finishes and leaves unrelated Task actor edges intact.

Then continue Person Refining / role-import human acceptance using only correctly transcribed grounded rows.

The observed small-Cyrillic raster role-import transcription issue remains a separate deferred follow-up. Do not start that or any other coding phase without fresh Architect authorization.
