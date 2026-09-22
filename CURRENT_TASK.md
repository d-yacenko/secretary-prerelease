# Current task — Telegram Bot API M4BS1R: fix authoritative Git ref verification

## Status

The first authorized M4BS1 live read-only run blocked locally with:

`M4BR1_BLOCKED=local_production_ref`

No SSH connection was made and no production state was read or changed.

Canonical GitHub `production` remains exact:

`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

The previous live authorization is consumed. No retry is authorized in this task.

## Root cause

The verifier uses explicit fetches such as:

`git fetch --prune origin main production`

and then trusts local remote-tracking refs such as:

`origin/production`.

With explicit command-line fetch refs and no destination refspec, Git does not guarantee that the corresponding remote-tracking ref is refreshed. A stale local `origin/production` can therefore cause a false blocker even when the authoritative GitHub branch is correct.

The remote helper has the same pattern for `production` and must be corrected too.

## Goal

Make Git branch verification authoritative and read-only without relying on remote-tracking ref mutation.

CODE/TEST ONLY. Do not run the verifier against production.

## Required correction

### 1. Authoritative remote branch helper

Implement a strict helper that executes:

`git ls-remote origin refs/heads/<branch>`

and:
- requires exactly one matching branch line;
- requires exact 40-char lowercase SHA;
- rejects malformed/duplicate/unexpected output;
- returns only the SHA in memory;
- never prints raw command output.

Use it for authoritative branch checks.

### 2. Local wrapper

Do not use local `origin/production` as the source of truth.

The wrapper must:
- keep canonical origin/clean main checks;
- verify local HEAD against authoritative remote `main` SHA;
- verify authoritative remote `production` SHA equals
  `bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`;
- perform these checks before SSH;
- avoid mutating remote-tracking refs merely for verification.

It is acceptable to add helper CLI commands to
`verify_telegram_bot_stage_c.py` so the shell wrapper can consume sanitized SHA-only output.

### 3. Remote helper

Before any runtime/DB inspection:
- require current HEAD exact accepted production release;
- query authoritative `refs/heads/production` via `git ls-remote`;
- require it equals the accepted release;
- do not depend on local `origin/production`;
- do not mutate Git tracking refs for this check.

Use deterministic sanitized failure stages for remote-ref lookup/mismatch.

### 4. Regression tests

Add tests proving:
- stale/missing local `origin/production` cannot cause failure when authoritative remote production SHA is exact;
- authoritative production mismatch fails before SSH/runtime inspection;
- malformed/duplicate `ls-remote` output fails closed;
- authoritative main mismatch makes local wrapper refuse stale local main;
- remote authoritative production mismatch causes zero runtime/DB/provider/write/recreate work;
- no `git fetch ... production` / `rev-parse origin/production` dependency remains in this verifier path.

If shell behavior is hard to unit-test directly, factor the ref parsing/checking into the Python helper and test that contract, plus static wrapper assertions.

## Preserve

Do not change:
- accepted production release `bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`;
- Alembic 0046;
- strict sanitized protocol;
- historical-read existential check;
- route/config/container/MTProto checks;
- bounded health retry;
- zero Telegram/provider calls;
- zero DB/env writes;
- zero service restart/recreate;
- no object identifiers/content output.

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
- Telegram/provider calls;
- DB/env writes;
- service restart/recreate;
- deploy/ref movement;
- schema/data cleanup;
- MTProto changes.

## Required report

Return:
- corrective commit SHA;
- exact authoritative-ref mechanism;
- local wrapper correction;
- remote helper correction;
- regression test results;
- compile/Ruff/Bash/diff-check results;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BS1R_REF_CHECK_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
