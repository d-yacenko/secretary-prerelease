# Current task — Telegram Bot API M4BT1R: remove symbolic-origin ambiguity from final verifier

## Status

The replacement M4BT1 live read-only run again blocked locally before SSH:

`M4BR1_BLOCKED=local_production_ref`

No production access or mutation occurred.

Canonical GitHub `production` is independently confirmed exact:

`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

The consumed live authorization must not be retried in this task.

## Root cause

The previous correction switched to `git ls-remote origin refs/heads/<branch>`, but the local wrapper still performs those calls before validating the local `origin` URL.

Therefore the authoritative check is only authoritative for whatever repository happens to be named `origin` locally.

The observed blocker proves the command succeeded but returned a SHA different from the accepted production SHA.

## Goal

Remove symbolic-remote ambiguity completely.

CODE/TEST ONLY.

## Required correction

### 1. Authoritative branch helper must accept an explicit remote URL

Refactor the helper contract to query:

`git ls-remote <validated-canonical-url> refs/heads/<branch>`

rather than hard-coded symbolic remote name `origin`.

Requirements:
- remote URL must exactly equal
  `https://github.com/d-yacenko/secretary-prerelease.git`;
- branch name strict validation remains;
- exactly one output line;
- exact 40-char lowercase SHA;
- exact expected ref name;
- malformed/duplicate/unexpected output fails closed;
- raw output is never printed.

### 2. Local wrapper ordering

Before any authoritative branch check:

1. load and validate `target.json`;
2. obtain canonical `origin_url` from the validated target;
3. require local `git remote get-url origin` equals that canonical URL;
4. only then query authoritative remote `main` and `production`, passing the canonical URL explicitly;
5. require local HEAD equals authoritative main;
6. require authoritative production equals accepted release;
7. only then continue to host pin / SSH.

Thus a wrong local origin must fail with `wrong_local_origin`, never masquerade as `local_production_ref`.

### 3. Remote helper

The remote helper already validates its configured origin before production-ref inspection.

Still remove symbolic ambiguity there too:
- after requiring remote repo origin exact canonical URL;
- query production using the canonical URL explicitly, not symbolic `origin`.

No fetch/tracking-ref mutation.

### 4. Regression tests

Add tests proving:
- authoritative helper command contains the explicit canonical URL and no symbolic `origin`;
- local wrapper validates target/local origin before authoritative main/production lookup;
- wrong local origin fails before any `ls-remote` branch comparison / SSH;
- explicit canonical production SHA exact => pass even if a hypothetical local remote-tracking ref is stale;
- canonical production mismatch fails before SSH;
- remote helper uses explicit canonical URL after origin validation;
- no `git ls-remote origin` remains in this verifier path.

Static wrapper ordering assertions are acceptable where shell unit tests are impractical.

## Preserve

Do not change:
- production release `bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`;
- Alembic 0046;
- Stage C historical-read existential check;
- strict sanitized protocol;
- route/config/container/MTProto checks;
- bounded health retry;
- zero provider calls;
- zero DB/env writes;
- zero service restart/recreate;
- no IDs/content output.

## Validation

Run:
- focused Stage C verifier tests;
- Python compile;
- bundled helper compile;
- Bash syntax;
- Ruff;
- `git diff --check`.

## Authorization

AUTHORIZED:
- local verifier/wrapper/test correction only;
- update `PROJECT_STATE.md`;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- live verifier retry;
- provider calls;
- DB/env writes;
- service restart/recreate;
- deploy/ref movement;
- schema/data cleanup;
- MTProto changes.

## Required report

Return:
- corrective commit SHA;
- explicit canonical-URL ref mechanism;
- wrapper ordering correction;
- remote helper correction;
- regression results;
- compile/Ruff/Bash/diff-check results;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BT1R_CANONICAL_REF_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
