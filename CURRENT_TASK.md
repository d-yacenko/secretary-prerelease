# CURRENT_TASK

HOLD

## REL1D-HG2D1 — offline qualification of the frozen HG2 backend release candidate

Qualification artifact:

`docs/rel1d_hg2_release_qualification.md`

Candidate `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6` is not qualified.

The full non-live backend suite exited 1: 716 failed, 3630 passed, 3 deselected, 170 warnings, 8 errors.

`ruff check app tests` exited 1 with 96 errors.

The focused HG2 union passed: 241 passed, 0 failed.

Production remains:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

No deploy, ref move, data repair, client rollout, or human REL1D acceptance without fresh Architect authorization.
