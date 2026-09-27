# Current task — Release People R4-R1: schema-neutral production backend rollout

## Authorization

The human explicitly authorized this production rollout.

This is a production deployment task. Execute only the exact release below using the normal committed production deployment contract.

## Exact identities

- Authorized release SHA: `8cf5f3a14dd2eb70dc754d87b2f90a7589aa8b4f`
- Authorized rollback SHA: `1b851f91bd37d0e79531ef740b02febb3c3af69d`
- Expected Alembic revision: `0050`
- Current production/origin-production before rollout: `1b851f91bd37d0e79531ef740b02febb3c3af69d`

GitHub comparison before authorization shows the release is 9 commits ahead, 0 behind, with the rollback SHA as merge base. The cumulative diff contains R4 presentation/service/test/client changes plus documentation; no Alembic revision or deployment-harness file is changed.

## Why this rollout exists

People R4 is accepted/source-ready on `main`, but the R4 Linux client cannot perform a meaningful human gate against the older production backend because that backend does not yet return:

- separated source-derived `identity_candidates`;
- candidate reasons/resolution;
- source Flow previews;
- reversible rejected candidate projection.

This rollout makes the accepted R4 backend projection available to the already-built R4 client. It does not authorize a new People phase.

## Mandatory procedure

Read and follow:

- `AGENTS.md`
- `docs/executor_bootstrap.md`
- `docs/deploy.md`
- `ops/production/deploy.py`
- `ops/production/remote_deploy.py`
- `ops/production/target.json`

Do not modify the deployment harness.

### 1. Deterministic bootstrap

Use the canonical repository exactly:

`https://github.com/d-yacenko/secretary-prerelease.git`

Use a clean current local `main` matching `origin/main`. If the existing checkout is dirty, stale, wrong-origin, or unrelated, leave it untouched and use a fresh temporary clone.

Verify the exact authorized release and rollback commits locally before any production action.

### 2. Release preflight before promotion

Before moving `origin/production`, verify:

- rollback SHA resolves exactly;
- release SHA resolves exactly;
- release is a descendant of rollback;
- `origin/production` is still exactly the rollback SHA;
- migration infrastructure paths checked by `ops/production/deploy.py` are unchanged from rollback to release;
- no new Alembic revision is part of this release;
- expected revision remains `0050`.

If any check fails, STOP without moving `origin/production`.

### 3. Promote production ref

Fast-forward `origin/production` from exactly:

`1b851f91bd37d0e79531ef740b02febb3c3af69d`

to exactly:

`8cf5f3a14dd2eb70dc754d87b2f90a7589aa8b4f`

Requirements:

- non-force fast-forward only;
- do not move `main`;
- do not merge/rebase/cherry-pick a release branch;
- if `origin/production` is no longer the exact rollback SHA, STOP and report the mismatch.

### 4. Run only the canonical deploy harness

From the clean canonical local `main` checkout, set literal values:

```bash
RELEASE_SHA=8cf5f3a14dd2eb70dc754d87b2f90a7589aa8b4f
ROLLBACK_SHA=1b851f91bd37d0e79531ef740b02febb3c3af69d
EXPECTED_ALEMBIC=0050
```

Then run only:

```bash
python3 ops/production/deploy.py \
  --release-sha "$RELEASE_SHA" \
  --rollback-sha "$ROLLBACK_SHA" \
  --expected-alembic "$EXPECTED_ALEMBIC"
```

No direct production SSH or Compose commands are authorized.

If the harness blocks or fails, obey its fail-closed/automatic rollback behavior and STOP. Do not bypass, repair manually, probe alternate hosts, or retry with alternate commands.

## Required successful result

A successful rollout must report/establish:

- `RELEASE_HEAD=8cf5f3a14dd2eb70dc754d87b2f90a7589aa8b4f`
- `DEPLOYMENT=PASS`
- health PASS;
- Alembic exactly `0050`;
- DB container unchanged;
- DB volume unchanged;
- `.env` unchanged;
- api recreated;
- worker recreated;
- `origin/production` exactly equals the release SHA;
- production checkout/runtime exactly equals the release SHA.

No migration runs.

## Runtime scope

The backend runtime change is the already accepted People R4 projection:

- existing source-derived Person identity candidates are exposed separately from known identities;
- candidate reasons/resolution and bounded source Flow previews are returned;
- rejected unattached candidate feedback is reversible in the first-party projection;
- confirm/reject/retract still use the existing identity-correction semantics;
- no automatic attach/merge is introduced;
- no provider/model lookup is introduced;
- Telegram model-facing privacy gates remain unchanged.

The release also contains client source files, tests, and documentation in Git, but this deployment task does NOT install or replace any desktop/mobile client.

## Additional boundaries

- Do not inspect or mutate production user data.
- Do not create synthetic production People, identities, Flow, Tasks, or relations.
- Do not confirm/reject/retract any real candidate for the user.
- Do not make live LLM/provider calls.
- Do not run Telegram discovery/history/sync.
- Do not install the R4 client.
- Do not change `.env`, credentials, secrets, DB container, or DB volume.
- Do not change Person/Task/social ontology.
- Do not start relationship/context persistence, Organization ontology, proactive work, MCP work, G3B, or S3.
- No BREAK-GLASS action is authorized.

## Human gate after rollout

After successful deployment, STOP.

The human will launch the already-built R4 Linux bundle:

`/tmp/secretary-r4-FjxjHf/secretary-prerelease/client/build/linux/x64/debug/bundle/personal_secretary`

and inspect real rooted People for:

1. known contacts remaining separate from possible contacts;
2. automatically discovered source-derived candidates where stored evidence exists;
3. understandable reasons and source Flow previews;
4. confirmation moving a valid endpoint into known contacts;
5. rejection removing a bad candidate and `Вернуть` restoring reviewability;
6. no unrelated endpoint silently becoming attached.

The Executor must not perform this human acceptance.

## Completion

On success:

1. record exact rollout facts in `PROJECT_STATE.md`;
2. return `CURRENT_TASK.md` to HOLD with exact production/runtime SHA and Alembic revision;
3. commit and push those documentation-only completion changes to `main`;
4. report release identity, production ref/runtime, Alembic, health, DB/env preservation, and whether rollback was used;
5. STOP.

Do not authorize or start any next phase.
