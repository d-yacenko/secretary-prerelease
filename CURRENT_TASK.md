# Current task — Production rollout: pre-next-feature fix round

## Human authorization

The human explicitly authorized this production rollout.

This authorization covers:
- fast-forwarding `origin/production`;
- the normal server production deploy path via `ops/production/deploy.py`;
- read-only/sanitized production verification.

It does NOT authorize:
- editing production `.env`;
- live paid OpenAI/provider calls;
- direct/manual SSH deployment outside the normal deploy harness;
- Telegram AI activation/provider calls;
- inventing a client binary distribution/install mechanism.

## Exact release

Deploy the current task commit itself as the exact release SHA.

Its parent MUST be exactly:
`efa4bd027500acdf32566282983dc671233b431b`

Accepted implementation chain contained in this release:
- base fix round: `82b27f9f93af489d086344fc443337d23aecd6a0`
- corrective pass: `a2a2e85ed5255cdf9fcf57fad15b222d89e946f6`
- Architect acceptance: `efa4bd027500acdf32566282983dc671233b431b`

Current production / rollback baseline:
`36c2ce9f43e56a9554688f50c60a79d56e469fbe`

Expected Alembic:
`0046`

The production-to-release delta is schema-neutral; normal deploy harness must independently enforce this.

## Important client boundary

The canonical production deployment harness deploys the server Compose runtime (db/api/worker). It does not install or distribute Flutter Android/Linux clients.

Therefore:
- deploy the server release normally;
- do not claim that desktop/mobile UI changes are installed on user devices solely because the server rollout succeeded;
- do not invent ad-hoc APK/Linux binary copying or installation;
- report client UI as SOURCE/RELEASE READY but DEVICE INSTALL/DISTRIBUTION NOT PERFORMED unless an already-established canonical client delivery mechanism is discovered in the repo during bootstrap. If none exists, STOP there for client distribution.

## Required preflight — before production ref movement

1. Bootstrap canonical repository:
   - clean worktree;
   - canonical origin;
   - local branch `main`;
   - fetch/prune;
   - `HEAD == origin/main`;
   - current HEAD is this exact task/release commit;
   - current release commit parent is exactly `efa4bd027500acdf32566282983dc671233b431b`.

2. Confirm:
   - `origin/production == 36c2ce9f43e56a9554688f50c60a79d56e469fbe`;
   - current production runtime reports the same SHA;
   - Alembic is `0046`.

3. Capture sanitized rollback invariants:
   - production DB container identity;
   - production DB volume identity;
   - production `.env` SHA-256 only;
   - API and worker container identities.

4. Confirm no migration infrastructure changes between rollback and release. The normal deploy harness also enforces this; any disagreement is a blocker.

5. Do not print secrets or complete environment contents.

BLOCK before ref movement on any mismatch.

## Authorized rollout sequence

Only if preflight passes:

1. Fast-forward `origin/production` non-force from
   `36c2ce9f43e56a9554688f50c60a79d56e469fbe`
   to the exact current task/release SHA.

2. Deploy ONLY with:

`python3 ops/production/deploy.py --release-sha <EXACT_RELEASE_SHA> --rollback-sha 36c2ce9f43e56a9554688f50c60a79d56e469fbe --expected-alembic 0046`

Do not substitute manual SSH/docker-compose commands.

3. Require normal deploy success and health PASS.

## Post-deploy verification

Confirm:
- `origin/production` equals exact release SHA;
- runtime release SHA equals exact release SHA;
- Alembic remains `0046 / 0046`;
- health PASS;
- DB container identity unchanged;
- DB volume identity unchanged;
- production `.env` SHA-256 unchanged;
- API and worker were recreated as expected;
- rollback was not used unless required by the normal harness;
- `TELEGRAM_MTPROTO_AI_ENABLED` behavior/config was not changed by this rollout.

No authenticated Assistant request is required. Do not issue a live OpenAI/provider call merely to smoke-test the fix.

Where safe with existing unauthenticated/read-only endpoints, verify only infrastructure/API health. Do not improvise credentials.

## Release-specific verification notes

Server-side behavior included in this release:
- temporal exact-revision pre-model idempotency with preserved anchor audit IDs;
- prompt untrusted-data consistency hardening;
- Assistant reference provider/date API fields and canonical primary-date semantics.

Client source included in this release:
- desktop Inbox inline trash;
- mobile swipe unchanged;
- hands-free terminal failure cue regression coverage;
- reference-chip kind/provider/date UI and narrow-width handling;
- Inbox-only action wrapping.

Because the production Compose harness does not distribute Flutter clients, report these client changes separately as code/source included in the release, not as installed-device verification.

## Rollback

If deployment or health verification fails after the production ref moves, use ONLY the rollback behavior provided by the normal production deployment harness to restore:
`36c2ce9f43e56a9554688f50c60a79d56e469fbe`

Do not manually mutate DB, Compose state, nginx, DNS, firewall, env, or credentials.

## Completion

Record sanitized exact results in `PROJECT_STATE.md`, including:
- exact deployed release SHA;
- production ref before/after;
- deploy/health status;
- Alembic;
- DB/container/env invariants;
- rollback used yes/no;
- server runtime status;
- explicit client boundary: whether any canonical client distribution path existed and whether client binaries were actually installed/distributed (do not infer).

Return `CURRENT_TASK.md` to HOLD, commit/push, and STOP.
