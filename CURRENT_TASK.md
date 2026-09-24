# Current task — PRODUCTION rollout: persistent Assistant conversations 0046 -> 0047

The user has explicitly authorized this production deployment.

This task is runtime rollout only. Do not implement or redesign product code.

## Exact authorized identities

- Release SHA: `296b4735f9473ea60ef22f1827ed94260603128e`
- Rollback/current production SHA: `42db393be50a4c3f20ce86dadc280d77bada3959`
- Current Alembic: `0046`
- Target Alembic: `0047`
- Reviewed migration harness implementation: `748949f5816c3eb6f1ec031d42b887a73c205a65`
- Harness closure/HOLD: `a30837874cfd1d728e0384a9e21fdf00f7998f58`

The release SHA is intentionally older than the harness commits: the harness runs from canonical current `main` and streams its remote helper, while production must receive the exact accepted application release above.

## Authorization and hard boundaries

Authorized:
- fast-forward `origin/production` from the exact rollback SHA to the exact release SHA;
- run the dedicated Assistant migration harness;
- migrate production DB exactly `0046 -> 0047`;
- recreate only api/worker as performed by the harness;
- let the harness perform its defined safe rollback if rollout fails.

Not authorized:
- force push;
- any release other than the exact SHA above;
- normal `deploy.py` for this schema-changing rollout;
- direct/ad-hoc production SSH or Compose commands;
- manual DB edits;
- deleting Assistant rows to permit rollback;
- changing production `.env`, DB container/volume, credentials, Telegram settings, or provider settings;
- live provider/LLM calls;
- any new feature work.

## Procedure

1. Perform the mandatory Executor bootstrap from `AGENTS.md` / `docs/executor_bootstrap.md` in the same work cycle.
2. Verify current `origin/production` is exactly:
   `42db393be50a4c3f20ce86dadc280d77bada3959`
   If not, STOP and report the mismatch.
3. Verify the exact release is a descendant of that production SHA and that the dedicated harness still has its reviewed exact-SHA contract.
4. Fast-forward `origin/production` non-force to exactly:
   `296b4735f9473ea60ef22f1827ed94260603128e`
   Then fetch/verify `origin/production` equals that SHA exactly.
5. Run exactly:

```bash
python3 ops/production/migrate_assistant_0047.py \
  --release-sha 296b4735f9473ea60ef22f1827ed94260603128e \
  --rollback-sha 42db393be50a4c3f20ce86dadc280d77bada3959 \
  --from-alembic 0046 \
  --to-alembic 0047
```

6. Do not bypass any harness preflight or rollback guard.
7. Treat success only as exit code 0 with `ASSISTANT_MIGRATION_DEPLOYMENT=PASS`, `ALEMBIC=0047`, and all preservation/recreation booleans PASS/true.
8. If the harness returns `BREAK_GLASS_REQUIRED=true`, STOP immediately. Do not attempt repair, downgrade, data deletion, alternate SSH, or another deploy.
9. If any preflight/bootstrap failure occurs before the remote migration starts, STOP and report the sanitized blocker; do not improvise.

## Completion record

On success:
- record exact production release SHA, Alembic `0047 / 0047`, harness PASS output, and whether rollback was unused;
- record DB container/volume and `.env` preservation facts exposed by the harness;
- state explicitly that no live provider/LLM call was made and Telegram MTProto AI activation/quarantine was not changed;
- update `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- commit/push the documentation-only closure to `main`;
- STOP. Do not select the next phase.

On failure:
- record only sanitized facts allowed by the runbook;
- preserve the actual runtime state reported by the harness;
- return/leave task state consistent with the blocker;
- STOP.
