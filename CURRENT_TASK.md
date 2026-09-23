# Current task — Authorized production branding rollout

Human authorization is explicit for completing the accepted production rollout.

## Release pin
This task commit is the only authorized release. After canonical bootstrap, require:
- local main equals origin/main;
- HEAD parent is exactly 339bab7a8d541c29133e843adbf38abb33e6a00a;
- the only path changed from that parent to HEAD is CURRENT_TASK.md.

If any check differs, STOP. Define RELEASE_SHA as that exact HEAD.

## Baseline
- current production / rollback: 3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c
- expected Alembic: 0046
- accepted publisher code is included through 3486c830b3b20cfd8f8d7c66c17e9872b6b575fc
- no migration files changed in the accepted delta

## Authorized sequence
1. Canonical bootstrap and authoritative ref fetch.
2. Verify origin/production is the rollback SHA, RELEASE_SHA is a fast-forward, and migration files are unchanged.
3. Move production ref non-force to RELEASE_SHA.
4. Execute the normal schema-neutral production deploy harness for RELEASE_SHA with rollback 3930c4b4c026a2e1fc9acb31c0d8fea1b9422b5c and Alembic 0046.
5. Continue only after DEPLOYMENT=PASS.
6. Execute the repository nginx-root branding publisher for the same RELEASE_SHA.
7. Require publisher PASS, exact branding page/hash and redirect checks, unrelated-path 404, and unchanged DB/volume/env/API/worker identities during branding publication.
8. Record sanitized evidence in PROJECT_STATE.md, return CURRENT_TASK.md to HOLD, commit/push, STOP.

## Not authorized
No Google Cloud/OAuth mutation, fresh OAuth authorization, DNS/firewall change, nginx edit/reload/restart, manual SSH/manual Docker workaround, production env change, unrelated DB write, Telegram change, or any other release.

If canonical bootstrap is blocked, do not move production ref. Record the blocker and STOP.
