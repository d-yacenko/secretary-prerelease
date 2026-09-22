# Current task — Telegram Bot API M4BT1R: finish final Stage C verifier Git bootstrap cleanly

## Executor handoff

You are a fresh executor with no prior chat context. Everything needed for this task is in the canonical repository.

Canonical repo:
`https://github.com/d-yacenko/secretary-prerelease.git`

Read before editing:
1. `AGENTS.md`
2. `CURRENT_TASK.md`
3. `PROJECT_STATE.md`
4. `DECISIONS.md`
5. `docs/executor_bootstrap.md`
6. `docs/deploy.md`
7. established production bootstrap in `ops/production/deploy.py`

Do not infer authorization from old commits. This file is the active authorization source.

## Current production facts

Production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Alembic:
`0046`

Telegram Bot lifecycle:
- Bot runtime retired;
- webhook deleted;
- Bot credentials cleared;
- Bot account destroyed;
- Stage C code cleanup deployed;
- MTProto is the sole live Telegram transport;
- historical Bot-derived objects/schema are intentionally preserved.

The final Stage C verifier is read-only.

Two live attempts blocked locally before SSH with:

`M4BR1_BLOCKED=local_production_ref`

No production access or mutation occurred in either blocked attempt.

GitHub independently confirms canonical `production` is exact
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`.

## Problem to solve

The verifier Git bootstrap has accumulated bespoke ref-validation logic and has produced false blockers.

Current specific defect:
- wrapper performs authoritative branch lookup using symbolic local remote name `origin`;
- that lookup happens before local `origin` is proven canonical;
- therefore a wrong/mispointed local `origin` can make the verifier compare the wrong repository and report `local_production_ref`.

Do not add another ad-hoc patch layer.

Review the whole local+remote Git bootstrap for this verifier and make it consistent with the established production deployment trust model.

## Goal

Deliver one clean correction so the Stage C verifier:

1. establishes canonical repository identity first;
2. queries authoritative GitHub refs using an explicit validated canonical URL;
3. never relies on stale remote-tracking refs for production truth;
4. never mutates Git refs merely to verify them;
5. fails with the correct deterministic local/remote stage;
6. remains strictly read-only with respect to production.

CODE/TEST ONLY. No live verifier run.

## Required design

### A. Single explicit canonical remote identity

Use the validated canonical repository URL:

`https://github.com/d-yacenko/secretary-prerelease.git`

Authoritative branch checks must execute equivalent to:

`git ls-remote <canonical-url> refs/heads/<branch>`

not:

`git ls-remote origin ...`

and not:

`rev-parse origin/production`.

Prefer one reusable/testable Python function rather than duplicating Git parsing in shell.

Strictly require:
- canonical URL exact match;
- strict branch-name validation;
- exactly one output line;
- exact lowercase 40-char SHA;
- exact requested ref name;
- malformed/duplicate/unexpected output fails closed;
- raw Git output is never surfaced.

### B. Local wrapper trust order

Before any branch lookup or SSH:

1. validate `target.json`;
2. obtain canonical `origin_url` from validated target;
3. require local repo root/branch/worktree are correct;
4. require local `git remote get-url origin` equals canonical URL;
5. query authoritative `main` via explicit canonical URL;
6. require local HEAD == authoritative main;
7. query authoritative `production` via explicit canonical URL;
8. require production == accepted release;
9. only then perform host pin / SSH.

Wrong local origin must fail as `wrong_local_origin`, not as a branch mismatch.

### C. Remote helper trust order

Before Docker/DB/runtime inspection:

1. require remote repo origin equals canonical URL;
2. require HEAD exact accepted production release;
3. query authoritative production using explicit canonical URL;
4. require authoritative production exact accepted release;
5. require clean tracked worktree;
6. only then continue to read-only runtime verification.

No `git fetch`, tracking-ref update, branch checkout, reset, or ref mutation.

### D. Reuse existing production conventions

Inspect `ops/production/deploy.py` and existing accepted verifier/harness code.

Do not invent another parallel trust model when an existing canonical helper/pattern can be reused or factored safely.

If a small shared read-only Git/target helper can remove duplication without broad refactor risk, that is allowed. Keep the change narrow.

## Required regressions

Prove at minimum:

1. authoritative lookup command uses explicit canonical URL, never symbolic `origin`;
2. malformed/duplicate/unexpected `ls-remote` output fails closed;
3. wrapper validates local origin before authoritative branch lookup;
4. wrong local origin fails before branch comparison and before SSH;
5. authoritative main mismatch rejects stale local main;
6. canonical production mismatch rejects before SSH;
7. stale/missing local remote-tracking refs are irrelevant;
8. remote helper validates origin before authoritative production lookup;
9. remote production mismatch stops before Docker/DB inspection;
10. no `git fetch`, `origin/production`, ref mutation, checkout, or reset is used in verifier ref validation;
11. strict sanitized output and zero-mutation/provider invariants remain intact.

## Preserve exactly

Do not change:
- production release expectation `bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`;
- Alembic `0046`;
- historical Bot existential Inbox-read check;
- route/config/container/MTProto checks;
- exactly one MTProto account;
- active scope count 28;
- `TELEGRAM_MTPROTO_AI_ENABLED=false`;
- bounded health retry;
- strict sanitized parser;
- zero Telegram/provider calls;
- zero DB writes;
- zero env writes;
- zero service restart/recreate;
- no object/account/peer/message IDs or message content in output.

## Validation

Run all of:
- focused Stage C verifier tests;
- Python compile;
- bundled helper compile;
- Bash syntax;
- Ruff;
- `git diff --check`.

Review your own final diff specifically for duplicated Git bootstrap logic and ordering mistakes before committing.

## Authorization

AUTHORIZED:
- local verifier/wrapper/test correction necessary to finish the Git bootstrap cleanly;
- small local refactor of production read-only Git/target helpers if it removes duplication safely;
- update `PROJECT_STATE.md`;
- commit and push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- live verifier retry;
- Telegram/provider calls;
- DB/env writes;
- service restart/recreate;
- deploy/rollback/ref movement;
- schema/data cleanup;
- MTProto behavior/config changes;
- AI enablement.

## Required report

Return:
- commit SHA;
- files changed;
- final trust-order design;
- exact authoritative-ref command shape;
- whether any shared helper was factored;
- regression/test results;
- compile/Ruff/Bash/diff-check results;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BT1R_CANONICAL_REF_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
