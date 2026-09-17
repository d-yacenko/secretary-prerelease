# Current task — Telegram Integration Gate I1R baseline attribution

## Status

- Telegram A4.1–A4.4: ACCEPTED.
- Integration merge `origin/main` -> `review/telegram-depth-a4-folder-scope` completed at `2a4da0cf7d1bb1cfd2e83c39b3b4dd1e24a938b4`.
- Architect independently verified that merge commit has parents `db8c0d196666f3ffb2a32db6e60c284fda31d12a` and `1be75b6d4329e25baaf158b9c61dafa3029b0184`, with zero first-parent content diff. The merge itself introduced no file-content changes.
- Telegram focused suite after merge: 137 passed.
- Full backend run reported `2935 passed, 98 failed, 8 errors, 3 skipped`.
- `ruff check app tests` reported 107 violations.
- The Executor called those full-suite/Ruff results baseline, but that attribution has not yet been proven against the pre-Telegram `main` tree.
- I1 is therefore PENDING, not rejected. `main` fast-forward is NOT authorized yet.

## Objective

Prove whether the full pytest failures/errors and Ruff violations already exist on the `main` baseline, or whether any are introduced/exposed by the accepted Telegram A3/A4 tree.

This is an evidence-only integration gate. Do not modify application/runtime/test/migration code.

## Fixed refs

Use these exact refs for comparison:

- integrated review candidate: `2a4da0cf7d1bb1cfd2e83c39b3b4dd1e24a938b4`;
- pre-integration main baseline: `1be75b6d4329e25baaf158b9c61dafa3029b0184`;
- pre-merge review first parent: `db8c0d196666f3ffb2a32db6e60c284fda31d12a`.

The integrated candidate and pre-merge review have identical trees; do not waste time rerunning both unless needed to diagnose nondeterminism.

## Required method

Work from the review worktree, clean state, and use a temporary **detached Git worktree** for exact main SHA `1be75b6d...`. Do not move/reset/rebase the review branch.

Use the same local development PostgreSQL/runtime environment for both refs so the comparison is apples-to-apples. Do not touch production.

### 1. Capture exact review failure signature

At integrated review candidate, run the same full command:

`pytest -q`

Capture the complete terminal output to a temporary local file outside the repository (for example `/tmp/telegram_i1r_review_pytest.txt`). Do not commit logs.

Extract/report:

- every FAILED nodeid;
- every ERROR nodeid / collection/setup error identity;
- summary counts.

If rerun counts/signatures differ materially from the prior `98 failed, 8 errors`, report nondeterminism explicitly and STOP before any code change.

### 2. Capture exact main baseline failure signature

In a detached temporary worktree at exact `1be75b6d4329e25baaf158b9c61dafa3029b0184`, run:

`pytest -q`

Capture output outside both repositories.

Report every FAILED/ERROR identity and counts.

Compare signatures by common test nodeid/error identity:

- failures/errors present in both => baseline;
- present only on integrated review => candidate regression/blocker;
- present only on main => not a Telegram blocker, but report.

Do not treat count equality alone as proof; compare identities.

### 3. Ruff attribution

Run on integrated review candidate:

`ruff check app tests --output-format concise`

Capture exact violations outside repository.

Run the same command at exact main baseline worktree.

Normalize by `path:line:column code` (message may also be reported) and compare.

Report:

- common baseline violations;
- review-only violations;
- main-only violations.

Any review-only violation in A3/A4-added/modified files is an I1 blocker until Architect decides otherwise.

### 4. No changes

Do not edit code/tests/migrations to make failures disappear during I1R.

If a review-only pytest or Ruff issue exists, report the exact nodeid/file/rule and STOP. Architect will authorize the smallest integration correction separately if required.

If all review failures/errors and Ruff violations are proven baseline (or review has fewer), report that evidence and STOP. Architect will then decide I1 acceptance and main fast-forward.

## Verification / hygiene

Also report:

- current review HEAD;
- `git status --short` before and after;
- detached main worktree exact HEAD;
- confirmation no repository-tracked files changed;
- confirmation no commits/pushes were made for test evidence;
- confirmation no production/UI/A4.5 work occurred.

Temporary worktree and `/tmp` logs may be removed after extracting the report.

## Completion marker

Final line exactly:

`TELEGRAM_INTEGRATION_GATE_I1R_ATTRIBUTION_READY`

Then STOP.
