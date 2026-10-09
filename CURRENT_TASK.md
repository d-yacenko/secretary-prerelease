# CURRENT_TASK

HOLD

## REL1D-HG4D — schema-neutral production rollout for accepted People fixes

ARCHITECT ACCEPTED.

Production runtime / release:
`a9221699b4b725888213ff38e6673495a512042c`

Rollback:
`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Architect acceptance ledger:
`79fe213dae09d4029990e42073fd6bc49208f1e1`

Deploy result:
- `DEPLOYMENT=PASS`
- `HEALTH=PASS`
- Alembic `0054`
- DB container unchanged
- DB volume unchanged
- environment file unchanged
- API/worker recreated
- rollback unused
- deployed OpenAPI exposes optional `window_index` on `GET /graph/people-workspace`

No Executor coding or deploy task is active.

Human verification now requires a rebuilt client from current `main`:

1. In People overview, verify page controls appear when more than 12 People exist and navigate to the later page containing the previously hidden Person.
2. Select a Person from the normal unrooted People overview and verify Task actor add/remove becomes visible immediately after the server mutation response.
3. Reproduce Person rename once on the rebuilt client and verify both the Person detail and global search display the new title.

The Person rename / generic object PATCH / embedding finding remains a separate suspected defect. Do not start HG4E unless rename still fails on the rebuilt client.

No next coding/deploy phase without fresh Architect authorization.
