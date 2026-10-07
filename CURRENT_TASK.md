# CURRENT_TASK

HOLD

## REL1D-HG3.2 — instant Person task-role feedback with stale-response protection

ARCHITECT ACCEPTED.

HG3.2 implementation:
`462a4c5102e68153c5dd6e320383b8585f3b85d3`

HG3.2.1 corrective:
`72c9f50f8a8fba1c3719f6ae3939b5afbf0fa4c8`

HG3.2.2 corrective:
`15dfa13345595abdda77fabdd70a60dd308e763f`

Architect acceptance ledger:
`3cffba1f0293048457a5c59063da1156fac14242`

Latest focused Flutter tests: 28 passed, 0 failed (`person_task_bridge`, `relation_target_label`, `graph_relation_target_disambiguation`). `dart analyze` on touched files exited 0 with pre-existing info notices only. `git diff --check` clean.

Production/backend remains:
`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic remains:
`0054 / 0054`

No Executor coding task is active.

Human recheck in a rebuilt client should verify:
1. Person Task-role add/remove becomes visible immediately after the mutation response rather than after the heavy People-workspace refresh;
2. unrelated Task actor rows remain;
3. duplicate Task titles remain disambiguated;
4. no stale actor row reappears after delayed reconciliation, Person switching, or rooted-detail loading.

After that, continue Person Refining / role-import human acceptance on correctly transcribed rows.

The small-Cyrillic raster role-import transcription issue remains a separate parked follow-up. Historical HG2 repair/backfill remains deferred.

No next coding phase without fresh Architect authorization.
