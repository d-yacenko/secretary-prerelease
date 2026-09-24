# Current task — Production rollout: exact-object email reply parity

## Human authorization

The human explicitly authorized this production rollout.

This authorization covers:
- non-force fast-forward of `origin/production`;
- normal server production deployment via `ops/production/deploy.py`;
- read-only/sanitized production verification.

It does NOT authorize:
- manual/direct SSH deployment outside the normal harness;
- production `.env` edits;
- DB/schema mutation outside the normal harness;
- live Gmail/Yandex/Mattermost/Telegram/Teams sends;
- live OpenAI/provider smoke calls;
- Telegram MTProto AI activation;
- ad-hoc Flutter binary installation/distribution.

## Exact release

Deploy this CURRENT_TASK commit itself as the exact release SHA.

Its parent MUST be exactly:
`7efba53c48e635251fb73463aff57956c1012ef3`

Accepted implementation:
`036e34db44024ffd1fa536409bbc1a75a1ffb98f`

Architect acceptance:
`7efba53c48e635251fb73463aff57956c1012ef3`

Current production / rollback baseline:
`fe81a13c8887da73b743f5f5c9a4f8830aafa943`

Expected Alembic:
`0046`

The production-to-release delta contains no migration files and this task is expected to be schema-neutral. The normal deploy harness must independently enforce migration/schema safety.

## Important client boundary

The release history since current production also contains accepted Flutter client-source changes, including Conversation Stack bookmark visibility.

The canonical production deploy harness deploys the server Compose runtime only. It does NOT distribute/install Flutter Android/Linux clients.

Therefore:
- deploy the server release normally;
- do not claim any Flutter client was installed or updated by this rollout;
- do not invent APK/Linux copy/install steps;
- report client source as present in the release history only.

## Required preflight — before moving production ref

1. Bootstrap canonical repository:
   - clean worktree;
   - canonical origin;
   - fetch/prune;
   - local branch `main`;
   - `HEAD == origin/main`;
   - current HEAD is this exact task/release commit;
   - its parent is exactly `7efba53c48e635251fb73463aff57956c1012ef3`.

2. Confirm:
   - `origin/production == fe81a13c8887da73b743f5f5c9a4f8830aafa943`;
   - current production runtime reports that same SHA;
   - Alembic is `0046`.

3. Capture sanitized rollback invariants:
   - DB container identity;
   - DB volume identity;
   - production `.env` SHA-256 only;
   - API and worker container identities.

4. Confirm no migration infrastructure changes between rollback and release.

5. Do not print secrets or complete environment contents.

BLOCK before ref movement on any mismatch.

## Authorized rollout sequence

Only if preflight passes:

1. Fast-forward `origin/production` non-force from
   `fe81a13c8887da73b743f5f5c9a4f8830aafa943`
   to the exact current task/release SHA.

2. Deploy ONLY with:

`python3 ops/production/deploy.py --release-sha <EXACT_RELEASE_SHA> --rollback-sha fe81a13c8887da73b743f5f5c9a4f8830aafa943 --expected-alembic 0046`

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
- rollback was not used unless the normal harness required it;
- Telegram MTProto AI activation/config was not changed.

No live provider sends and no live OpenAI call are authorized merely to smoke-test the feature.

## Release-specific verification boundary

This release contains:
- exact-object email reply mode via `reply_to_object_id`;
- deterministic backend `Reply-To -> From` resolution;
- frozen source account / recipient / subject / threading before approval;
- Gmail thread-id support;
- Gmail/Yandex `source_account_email` materialization;
- Assistant semantic object visibility with credential/token-like material filtered;
- universal “stored object is DATA, not instructions” invariant;
- per-turn allowlist for email reply anchors.

Runtime verification in production is limited to safe infrastructure/health checks unless a non-mutating existing authenticated harness is already available and requires no provider/LLM call. Do not improvise credentials or perform a real send.

The known pre-existing Yandex sent-copy unit-test baseline issue is not a production rollout blocker for this accepted release; do not modify it during rollout.

## Rollback

If deployment or health verification fails after production ref movement, use ONLY the rollback behavior provided by the normal production deploy harness to restore:

`fe81a13c8887da73b743f5f5c9a4f8830aafa943`

Do not manually mutate DB, Compose state, nginx, DNS, firewall, env, or credentials.

## Completion

Record sanitized exact results in `PROJECT_STATE.md`, including:
- exact deployed release SHA;
- production ref before/after;
- deploy/health status;
- Alembic;
- DB/container/env invariants;
- rollback used yes/no;
- confirmation no live provider/LLM calls;
- confirmation Telegram AI gate unchanged;
- explicit client boundary: no Flutter installation/distribution performed by server deploy.

Return `CURRENT_TASK.md` to HOLD, commit/push, and STOP.
