# CURRENT_TASK

HOLD

## REL1D-HG4F — schema-neutral production rollout for accepted Person rename

ARCHITECT ACCEPTED.

Production runtime / release:
`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

Rollback:
`a9221699b4b725888213ff38e6673495a512042c`

Architect acceptance ledger:
`d6e20de4fb6c11852247ddc6c14ced568e6a7862`

Deploy result:
- `DEPLOYMENT=PASS`
- `HEALTH=PASS`
- Alembic `0054`
- DB container unchanged
- DB volume unchanged
- environment file unchanged
- API/worker recreated
- rollback unused
- deployed OpenAPI exposes strict `PATCH /graph/people/{person_id}` title-only body
- deployed OpenAPI still exposes optional `window_index` on `GET /graph/people-workspace`

No Executor coding/deploy task is active.

Human verification now requires a rebuilt client from current `main`:

1. Rename the previously tested Person and verify the new title appears immediately in the Person detail.
2. Verify global Search returns/displays the new persisted title.
3. Verify the Task actor edge remains visible in `Участие в задачах` but is no longer duplicated in generic `Связи`.
4. Verify ordinary non-actor generic relations remain visible.

The shared Task/People topology-window mismatch and Person identity-candidate/email scan depth remain separate recorded follow-ups.

No next coding phase without fresh Architect authorization.
