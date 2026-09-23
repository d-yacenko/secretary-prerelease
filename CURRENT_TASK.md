# Current task — Authorized Search Console verification tag production rollout

## Human authorization

The human explicitly authorized production deployment of the accepted Search Console verification tag.

This task commit is the only authorized release for this rollout.

## Self-pinned release rule

After canonical bootstrap, the Executor MUST require all of the following:

- local branch is `main`;
- `HEAD == origin/main`;
- `HEAD^` is exactly `6d37e146b789aa940e8a738c6dc5aeb4f80d6870`;
- the only path changed by `6d37e146b789aa940e8a738c6dc5aeb4f80d6870..HEAD` is `CURRENT_TASK.md`.

If any condition differs, STOP. Do not infer authorization for a newer commit.

After those checks pass, define the exact literal release for this run as the resulting 40-character `HEAD` SHA and use that same SHA for the production ref, deploy harness, and branding publisher.

## Accepted baseline

- Current production runtime/ref before this task: `caab6f1825f69635f88724207ccf173b808dafa4`.
- Rollback SHA: `caab6f1825f69635f88724207ccf173b808dafa4`.
- Expected Alembic: `0046`.
- Parent `6d37e146b789aa940e8a738c6dc5aeb4f80d6870` contains Architect acceptance of the Search Console verification tag.
- Implementation commit: `f334fd69ba70df152a5ccdfeaa015017f5a336e2`.
- The accepted delta from current production contains no Alembic/migration files.

## Required sequence

1. Bootstrap from a fresh canonical clean checkout according to `AGENTS.md` and `docs/executor_bootstrap.md`.
2. Fetch authoritative `origin/main` and `origin/production`.
3. Perform the self-pinning checks above. Then set:
   - `RELEASE_SHA` = exact 40-character `git rev-parse HEAD`;
   - `ROLLBACK_SHA=caab6f1825f69635f88724207ccf173b808dafa4`;
   - `EXPECTED_ALEMBIC=0046`.
4. Verify:
   - `origin/production == ROLLBACK_SHA`;
   - `RELEASE_SHA` is a clean fast-forward descendant of `ROLLBACK_SHA`;
   - no Alembic/migration files changed in `ROLLBACK_SHA..RELEASE_SHA`.
5. Move canonical `production` ref non-force from `ROLLBACK_SHA` to exact `RELEASE_SHA`.
6. Run only the normal schema-neutral deploy harness:
   `python3 ops/production/deploy.py --release-sha "$RELEASE_SHA" --rollback-sha "$ROLLBACK_SHA" --expected-alembic "$EXPECTED_ALEMBIC"`
7. Require `DEPLOYMENT=PASS`. If deploy fails or blocks, record one sanitized result and STOP. Do not run the branding publisher.
8. After deploy PASS, run only:
   `python3 ops/production/public_web_rollout.py --release-sha "$RELEASE_SHA"`
9. Require branding publisher PASS with all accepted invariants:
   - DB container unchanged;
   - DB volume unchanged;
   - production `.env` unchanged;
   - API container unchanged during branding publication;
   - worker container unchanged during branding publication;
   - home page 200;
   - `/privacy` 301 to exact same-host `/privacy/`;
   - `/privacy/` 200 with authorized body hash;
   - `/terms` 301 to exact same-host `/terms/`;
   - `/terms/` 200 with authorized body hash;
   - unrelated branding path 404.
10. Verify live `https://web-itx.duckdns.org/` contains exactly one `google-site-verification` meta tag with content:
    `hTkY_ZxfZrzsygn-3oU4wxH6zraiRWo28hGXZF_U1Is`
    Do not print the page body.
11. Record sanitized deploy + publisher + live-tag evidence in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, commit/push, and STOP.

## Not authorized

- Google Cloud or Search Console mutation;
- clicking Search Console Verify;
- OAuth consent-screen/publishing-mode changes;
- OAuth reauthorization;
- DNS/firewall changes;
- nginx configuration edit/test/reload/restart;
- manual/direct SSH or manual Docker/Compose outside repository harnesses;
- production env changes;
- unrelated DB writes;
- Telegram changes;
- any release other than the uniquely self-pinned task commit described above.

If canonical bootstrap cannot run, do not move the production ref and do not use a workaround. Record/report the blocker and STOP.
