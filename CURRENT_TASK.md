# Current task — HOLD

GR1-R1 production rollout is Architect-reviewed and ACCEPTED FOR HUMAN GATE.

Accepted implementation:
- `0719e9bf5af75a8065a9916d8e27c0247a3921ec`

Accepted rollout:
- Executor rollout/HOLD commit: `d9dfb40df1b822591a0d55204d433e4f0cacae5f`
- production fast-forward: `1b6943ba4f7cc49df1465791d812d45db6d26b52` → `0719e9bf5af75a8065a9916d8e27c0247a3921ec`
- canonical deploy harness exit: 0
- `RELEASE_HEAD=0719e9bf5af75a8065a9916d8e27c0247a3921ec`
- `HEALTH=PASS`
- `ALEMBIC=0052`
- `DB_CONTAINER_UNCHANGED=true`
- `DB_VOLUME_UNCHANGED=true`
- `ENV_FILE_UNCHANGED=true`
- `API_RECREATED=true`
- `WORKER_RECREATED=true`
- `DEPLOYMENT=PASS`
- rollback not used
- no application data modified for validation
- desktop client not replaced

Production runtime, `origin/production`, and production branch ref are all:
`0719e9bf5af75a8065a9916d8e27c0247a3921ec`

Production Alembic remains:
`0052 / 0052`

Canonical Task layout remains:
`task-map-v2.2`

## Human gate

Run the workstation-local GR1 debug client manually:

`/home/d.yacenko/tmp/gr1-0719e9b-artifact/bundle/personal_secretary`

Do not install/replace the desktop client automatically.

Verify on existing live data:

1. Old confirmed removable agent-created relations now show “Удалить связь” in the inspector.
2. Removing one such relation makes it disappear from the active map/inspector while preserving provenance as rejected.
3. A wrong directed edge can be removed, then recreated in the correct direction using the existing “Добавить связь” flow.
4. A proposed endpoint such as `Program_DYSC.pdf` is already visible on the same canvas as its Task without opening the inspector first.
5. Proposed Confirm / Reject controls still work.
6. Truly off-area relations, if encountered, are labeled `вне текущей области` and remain navigable.
7. TL2.2 flower geometry and SW2-A whole-component pagination remain coherent.

GR1 is not HUMAN-ACCEPTED until the user reports this check.

Do not deploy again, run Alembic, alter production data for validation, install the client, start SW2-B, or begin another Graph-cleanup slice until the human gate result is recorded. STOP.
