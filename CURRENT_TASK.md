# Current task — Release People R2/R3-R1: schema-neutral production backend rollout

## Authorization

The human explicitly authorized this production rollout.

This is a production deployment task. Execute only the exact release below using the normal committed production deployment contract.

## Exact identities

- Authorized release SHA: `1b851f91bd37d0e79531ef740b02febb3c3af69d`
- Authorized rollback SHA: `7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`
- Expected Alembic revision: `0050`
- Current production/origin-production before rollout: `7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`

The release is a descendant of the rollback SHA and is schema-neutral with respect to the normal deployment harness.

## Why this rollout exists

The accepted R3 Linux client is currently talking to the older production backend. That backend does not yet return the rooted People R2 truth projection and does not expose the R3 explicit email-binding endpoint, so the human cannot complete the R2/R3 visual gate on real data.

This rollout makes the already accepted backend/runtime code available in production. It is not a new feature phase.

The cumulative backend delta includes:

- accepted Harness H2D MCP Task actor/dependency schema parity;
- accepted People R2 rooted Person truth projection;
- accepted People R3 explicit user-confirmed exact email binding.

H2D remains fail-closed for MCP writes exactly as accepted. No new MCP approval transport is authorized.

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
- the migration infrastructure paths checked by `ops/production/deploy.py` are unchanged from rollback to release;
- no new Alembic revision is part of this release;
- expected revision remains `0050`.

If any of these checks fail, STOP without moving `origin/production`.

### 3. Promote production ref

Fast-forward `origin/production` from exactly:

`7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4`

to exactly:

`1b851f91bd37d0e79531ef740b02febb3c3af69d`

Requirements:

- non-force fast-forward only;
- do not move `main`;
- do not create a release merge/rebase/cherry-pick;
- if `origin/production` is no longer the exact rollback SHA, STOP and report the mismatch instead of choosing another base.

### 4. Run the canonical deploy harness

From the clean canonical local `main` checkout, set literal values:

```bash
RELEASE_SHA=1b851f91bd37d0e79531ef740b02febb3c3af69d
ROLLBACK_SHA=7f549c6fb4a3497f8d22b1784ee3cd5e26cafaa4
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

If the harness blocks or fails, obey its fail-closed/automatic rollback behavior and STOP. Do not repair, bypass, retry with alternate commands, or probe alternate hosts.

## Required successful result

A successful rollout must report/establish all of the following:

- `RELEASE_HEAD=1b851f91bd37d0e79531ef740b02febb3c3af69d`
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

## Additional boundaries

- Do not inspect or mutate production user data.
- Do not create synthetic production People, Tasks, Flow, identities, or relations.
- Do not bind the human's real email for them.
- Do not make live LLM/provider calls.
- Do not run Telegram discovery/history/sync.
- Do not install or replace the desktop/mobile client.
- Do not change `.env`, credentials, secrets, DB container, or DB volume.
- Do not change Task/Person/social ontology.
- Do not start relationship persistence, Organization ontology, proactive work, MCP approval transport, G3B, or S3.
- No BREAK-GLASS action is authorized.

## Human gate after rollout

After a successful rollout, STOP.

The human will use the already-built R3 Linux client to:

1. root the existing Olga Person;
2. confirm that R2 sections and `Добавить email` now appear;
3. bind the known exact real email;
4. verify expected stored Flow becomes attributable and unrelated Flow does not;
5. inspect the R2 Task/Flow/salience truth surface.

The Executor must not perform that human acceptance.

## Completion

On success:

1. record exact rollout facts in `PROJECT_STATE.md`;
2. return `CURRENT_TASK.md` to HOLD, recording the exact production release/runtime SHA and Alembic revision;
3. commit and push those documentation-only completion changes to `main`;
4. report the implementation/release identity, production ref/runtime, Alembic, health, DB/env preservation, and whether rollback was used;
5. STOP.

Do not authorize or start any next phase.
