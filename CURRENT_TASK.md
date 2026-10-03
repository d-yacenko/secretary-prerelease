# Current task — HOLD

REL1B-A grounded known-Person role evidence is complete.

- Implementation: `0859fc4ebeb49db06f9ab12efc2f9acb552ecab9`
- Evidence version: `2`
- Schema head: `0054`
- Production backend/source: `6f802d6959aca40758376a83d5bdfcbbd77fc537`
- Production Alembic: `0054 / 0054`
- Installed client source: `6f802d6959aca40758376a83d5bdfcbbd77fc537`

Changed files:

- `backend/app/personal_relevance/models.py`
- `backend/app/personal_relevance/known_people.py`
- `backend/app/services/personal_relevance_evidence_service.py`
- `backend/tests/test_rel1b_person_role_relevance_evidence.py`
- `backend/tests/test_workflow_intelligence_personal_relevance_e_b.py`

Known People enter a snapshot only through an exact active current-user PersonIdentity. Active role display text and optional context are included. Proactive seed context and instructions do not receive those fields.

Checks: REL1B-A, REL1A, personal-relevance E-B, person identity, and the focused consolidation test together 84 passed, 0 failed. Ruff passed. `git diff --check` clean. The proactive personalization and proactive secretary files reported 22 failures, each an absolute notification count shifted by 5 pre-existing bootstrap notifications. Those rows were not deleted.

No deploy, migration, client install, model call, or provider call. REL1B-B was not started.
