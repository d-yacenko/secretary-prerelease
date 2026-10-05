# CURRENT_TASK

ACTIVE

## REL1D-HG2D1.1 — differential production-baseline diagnosis of qualification blockers

REL1D-HG2D1 is correctly BLOCKED.

Frozen candidate:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Production / rollback baseline:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Current D1 evidence:

- candidate Git/schema-neutral invariants: green;
- focused HG2 union: `241 passed / 0 failed`;
- candidate full non-live suite: `716 failed / 3630 passed / 8 errors`;
- candidate repository-wide Ruff: `96 findings`;
- candidate remains NOT QUALIFIED.

The first full run used `--tb=no`, so it does not establish whether the global failures are:

1. regressions introduced by the candidate;
2. pre-existing failures already present at the production baseline;
3. systemic/local-environment failures that affect both SHAs.

This task answers ONLY that differential question.

It does NOT fix tests or Ruff.
It does NOT qualify the candidate.
It does NOT weaken the release gate.
It does NOT touch production.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `docs/rel1d_hg2_release_qualification.md`
- `backend/pyproject.toml`

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Verify exact refs:

- candidate `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`;
- rollback `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
- `origin/production == bc69c6fa5c0735db9509d12dd5f77e6285e45901`.

Do not move any ref.

## Environment comparability gate

Before running differential tests, prove from Git that rollback -> candidate does NOT change the backend dependency/test-runner configuration used here.

At minimum compare:

- `backend/pyproject.toml`;
- any `backend/conftest.py` if present;
- shared pytest configuration;
- requirements/lock/dependency files if present.

Record the exact paths checked.

Use the SAME:

- Python executable;
- Python version;
- installed dependency environment;
- pytest executable/module;
- pytest version;
- Ruff executable;
- Ruff version;
- relevant non-secret local environment variables

for both SHAs.

Do not install a different dependency set for one SHA.

If the dependency/test configuration materially differs between the two SHAs, return HOLD and STOP instead of performing an invalid comparison.

## Exact isolated checkouts

Create two temporary clean worktrees/checkouts from the same canonical clone:

- rollback worktree at exactly `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
- candidate worktree at exactly `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`.

Do not edit either checkout.

Do not reuse pytest cache between them. Use `-p no:cacheprovider`.

Temporary logs/JUnit/JSON may live outside the repository and MUST NOT be committed.

## Differential full-suite run

Run from each exact worktree's `backend/` directory with the same environment:

`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -m "not live" -q --tb=no --junitxml=<temporary-path>`

Run rollback and candidate separately.

Do not use `--maxfail`.

Record for EACH SHA:

- exit code;
- passed;
- failed;
- errors;
- skipped if emitted/represented in JUnit;
- deselected;
- xfailed/xpassed if represented;
- warnings if terminal summary reports them;
- total collected/executed as derivable.

Use the JUnit XML and terminal output only for local analysis. Commit no raw output.

## Required pytest differential

Using a small one-off local standard-library parser or equivalent read-only analysis, compare testcase outcomes.

Produce counts for:

- failing/error test identifiers common to BOTH SHAs;
- rollback-only failing/error identifiers;
- candidate-only failing/error identifiers that also EXIST in rollback collection;
- candidate-only failing/error identifiers from tests/files that do NOT exist at rollback;
- candidate new tests that PASS.

For candidate-only failing/error identifiers, record exact node/test identifiers in the diagnostic artifact.

For common failures, group by normalized failure/error signature where practical and give the top categories with counts. Do not dump hundreds of raw tracebacks.

### Representative traceback rule

If candidate-only common-test failures exist:

- rerun only enough representative candidate-only tests with `--tb=short` to establish root-cause categories;
- maximum 10 representative reruns total;
- if many tests share the same first exception/signature, sample one from that category.

If there are ZERO candidate-only common-test failures, do not perform unnecessary traceback reruns.

If the dominant common failures appear systemic (for example a shared fixture, missing local service, common DB setup, or environment assumption), identify the first concrete exception/root fixture from a small representative sample and state that it affects both SHAs. Do not repair it.

## Differential Ruff run

Using the SAME Ruff binary/version, run in each exact `backend/` worktree:

`ruff check app tests --output-format json`

Capture JSON outside the repository.

Record for EACH SHA:

- exit code;
- total findings;
- counts by Ruff code.

Compare findings in a line-number-robust way.

At minimum report:

- findings in files unchanged rollback -> candidate;
- findings in files modified rollback -> candidate;
- findings in candidate-added files;
- candidate-only finding counts by path/code/message;
- rollback-only finding counts by path/code/message.

Do not treat simple line-number movement as a new finding.

Do not auto-fix anything.

## Changed-file context

From Git, classify rollback -> candidate backend Python/test files as:

- added;
- modified;
- unchanged.

For every candidate-only pytest or Ruff blocker, state whether its source/test path is added/modified/unchanged in the candidate delta.

This is evidence only; do not infer causality solely from path classification.

## Required diagnostic artifact

Create exactly one new non-ledger artifact:

`docs/rel1d_hg2_release_baseline_diagnostic.md`

It must contain:

### 1. Identity and environment

- rollback SHA;
- candidate SHA;
- current `origin/main`;
- current `origin/production`;
- Python version;
- pytest version;
- Ruff version;
- confirmation same environment was used;
- dependency/test-config comparison result.

### 2. Pytest rollback result

Exact command and totals.

### 3. Pytest candidate result

Exact command and totals.

### 4. Pytest differential

- common failures/errors count;
- rollback-only count;
- candidate-only common-test count;
- candidate-only new-test count;
- passing candidate-added test count;
- concise signature families;
- exact candidate-only identifiers, if any;
- representative root causes only where required.

### 5. Ruff differential

- rollback totals by code;
- candidate totals by code;
- candidate-only vs rollback-only findings using line-number-robust comparison;
- candidate-added/modified/unchanged file classification for any candidate-only findings.

### 6. Architect-decision evidence

Choose only the evidence classification supported by results:

- `CANDIDATE_REGRESSION_PRESENT`
- `NO_CANDIDATE_REGRESSION_PROVEN__BASELINE_GLOBAL_GATES_ALREADY_RED`
- `SYSTEMIC_ENVIRONMENT_COMPARISON_BLOCKED`
- `MIXED__CANDIDATE_AND_BASELINE_FAILURES`

Do NOT write `QUALIFIED`.

Do NOT recommend moving production.

State explicitly that the Architect must separately decide whether:
- candidate-specific issues require corrective work; or
- qualification policy may use a production-baseline no-regression gate for historical global debt.

### 7. Release boundary

Explicitly state:

- candidate remains NOT QUALIFIED;
- no source/test fix was made;
- no deploy/ref move occurred;
- no SSH/provider/production DB access occurred;
- no data repair/client rollout occurred;
- human REL1D acceptance remains paused.

## Source mutation prohibition

Do not change:

- `backend/app/`
- `backend/tests/`
- `backend/alembic/`
- `backend/pyproject.toml`
- dependency files;
- `ops/production/`;
- client source.

The only non-ledger file allowed to be added/changed is:

`docs/rel1d_hg2_release_baseline_diagnostic.md`

Do not modify the existing D1 qualification artifact except to leave it as the immutable record of the failed first qualification.

## Completion protocol

On successful differential diagnosis:

1. add `docs/rel1d_hg2_release_baseline_diagnostic.md`;
2. append compact factual `REL1D-HG2D1.1` evidence to `PROJECT_STATE.md`;
3. replace `CURRENT_TASK.md` with HOLD stating:
   - D1.1 diagnostic artifact path;
   - evidence classification;
   - exact rollback and candidate pytest totals;
   - exact rollback and candidate Ruff totals;
   - candidate remains NOT QUALIFIED;
   - production remains `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - no deploy/ref move/fix/data repair/client action without fresh Architect authorization;
4. commit + push to `main`;
5. STOP.

On diagnostic blocker:

- record the exact comparability/environment blocker in the artifact;
- return HOLD;
- do not mutate source/tests;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
