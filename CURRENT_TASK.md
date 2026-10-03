# Current task — HOLD

## REL1B-A.1 — close v2 stale-authority race and make Proactive regressions data-independent

Corrective implementation: `9d13d9ec36b10b0861e002c25ba5715e5ed48ec7`.

- Personal Relevance evidence version remains `2`.
- Schema head remains `0054`.
- `PersonRoleService.assign` and `retract`, `PersonIdentityService.attach`, `detach`, and `reassign`, and `PersonConsolidationService.apply` and `undo` take the user serialization gate before reading or mutating. Search, resolve, list, `create_person`, and consolidation preview stay unlocked.
- `acquire_personal_relevance_authority` locks the initial snapshot's known Person rows `FOR UPDATE` in UUID byte order. `ProactiveReviewService` passes those ids. A missing or changed Person fails the existing fresh-snapshot comparison.
- Before-authority mutations commit and discard the pending notification as stale. After-authority role, identity, Person-title, and consolidation apply/undo writes block until the authority transaction finishes.
- Tests: REL1B-A, REL1A, personal-relevance E-B, Person identity, and the consolidation identity/role move test together 84 passed, 0 failed. `test_workflow_intelligence_proactive_personalization_e_c.py` 41 passed, 0 failed. `test_proactive_secretary_c.py` 63 passed, 0 failed. The five existing bootstrap notifications were not deleted or edited.
- Production backend/source and the installed Linux client remain `6f802d6959aca40758376a83d5bdfcbbd77fc537`.
- Production Alembic remains `0054 / 0054`.
- No deploy, migration, client install, model call, provider call, or data cleanup.
- REL1B-B was not started.

Do not start REL1B-B from HOLD.
