# Current task — Release People R4-H2-R1: schema-neutral production backend rollout

## Authorization

The human explicitly authorized this People R4-H2 production backend rollout.

## Exact release contract

- Release SHA: `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`
- Rollback SHA: `8cf5f3a14dd2eb70dc754d87b2f90a7589aa8b4f`
- Expected Alembic: `0050`
- Current production/origin-production before rollout: `8cf5f3a14dd2eb70dc754d87b2f90a7589aa8b4f`
- Current main before authorization: `3b4ea789d92496c51481f904141cd9aded4674ae`

Architect GitHub preflight confirms release is a normal descendant of current production: 8 commits ahead, 0 behind, merge-base exactly the rollback SHA. No Alembic revision and no production deploy-harness file is changed between rollback and release.

## Goal

Deploy only the reviewed H2 backend correction so the later human gate can test the new rooted salience behavior against production.

H2 changes rooted Person salience to the same 90-day / 400-row bounded communication scan used by rooted recent Flow. Overview/rank remains on 200. Score formula, provider attribution, candidate semantics, and task semantics remain unchanged.

## Mandatory execution contract

Read and follow:

- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/deploy.py`
- `ops/production/remote_deploy.py`
- `ops/production/target.json`

Use the canonical repository `https://github.com/d-yacenko/secretary-prerelease.git` from a clean current checkout.

Before any production mutation, verify all exact refs and that `origin/production` is still the rollback SHA.

Promote `origin/production` only by non-force fast-forward from the exact rollback SHA to the exact release SHA.

Run only the canonical committed production deployment harness `ops/production/deploy.py` using the exact release SHA, rollback SHA, and expected Alembic above. Do not use direct SSH or manual Compose commands.

If any preflight/harness condition fails, STOP. Do not bypass, repair manually, or retry with alternate production commands.

## Required successful result

A successful rollout must establish:

- release/runtime exactly `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`;
- `origin/production` exactly the release SHA;
- deployment PASS and health PASS;
- Alembic exactly `0050`;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- only api/worker recreated as allowed by the normal harness;
- no migration;
- rollback not used unless the canonical harness itself requires it after failure.

## Boundaries

Do not inspect or mutate real production Person/Flow/Task data.
Do not create synthetic production data.
Do not call providers or an LLM/model.
Do not run sync/discovery/history.
Do not install or replace the client.
Do not change environment/secrets/schema/ontology.
Do not start another People, relationship, Organization, proactive, MCP, G3B, or S3 slice.
No BREAK-GLASS action is authorized.

## Human gate after rollout

After successful backend rollout, STOP.

The human will separately use:

`/tmp/secretary-r4h2-Xe3OQF/secretary-prerelease/client/build/linux/x64/debug/bundle/personal_secretary`

The Executor must not perform or claim the human visual/semantic acceptance.

## Completion

On success:

1. record exact rollout facts in `PROJECT_STATE.md`;
2. return `CURRENT_TASK.md` to HOLD with production/runtime SHA and Alembic;
3. commit and push the documentation-only completion to `main`;
4. report exact refs, health, Alembic, DB/env preservation, rollback status;
5. STOP.

Do not start the next phase.
