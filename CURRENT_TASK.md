# CURRENT_TASK

HOLD

## REL1D-HG5C — schema-neutral production rollout for shared Task/People semantic windows

ARCHITECT ACCEPTED.

Production runtime / release:
`0031f531d1215970093bea7add44fcd2259ec71b`

Rollback:
`50c64dd8d16c1a1b4ec8fec2ff7e9f272944114f`

Architect acceptance ledger:
`ca34ae2de44c3d12b84cb6734f3cbd0865b79707`

Deploy result:
- `DEPLOYMENT=PASS`
- `HEALTH=PASS`
- Alembic `0054`
- DB container unchanged
- DB volume unchanged
- environment file unchanged
- API/worker recreated
- rollback unused
- GitHub `production`, runtime HEAD, and runtime `origin/production` equal the release SHA
- OpenAPI preserves optional `window_index` on `GET /graph/workspace` and `GET /graph/people-workspace`
- OpenAPI preserves strict title-only `PATCH /graph/people/{person_id}`

No Executor coding/deploy task is active.

Human verification now requires a rebuilt client from current `main`:

1. Open Tasks in semantic area 1, switch to People, and verify People remains in area 1.
2. Navigate to semantic area 2 in either mode and switch modes both directions; verify the area index remains 2.
3. Verify People UI reads `Люди · область N из M`.
4. Verify anchored People visually correspond to the Tasks of that semantic area.
5. Verify unanchored People remain on the global shelf and do not acquire an artificial Task location.
6. Visit/root/search a Person, return to overview, and verify the remembered semantic area is restored.

The separate Person identity-candidate/email discovery issue remains deferred until this topology acceptance is human-confirmed.

No next coding phase without fresh Architect authorization.
