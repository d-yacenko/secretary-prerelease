# CURRENT_TASK

HOLD

## REL1D-HG2D1.1 — differential production-baseline diagnosis of qualification blockers

Diagnostic artifact:

`docs/rel1d_hg2_release_baseline_diagnostic.md`

Evidence classification:

`NO_CANDIDATE_REGRESSION_PROVEN__BASELINE_GLOBAL_GATES_ALREADY_RED`

Rollback pytest totals, exit 1:

`721 failed, 3519 passed, 3 deselected, 170 warnings, 8 errors`

Candidate pytest totals, exit 1:

`716 failed, 3630 passed, 3 deselected, 170 warnings, 8 errors`

JUnit differential: 724 common failing/error identifiers, 5 rollback-only, 0 candidate-only. 109 candidate-only node ids passed.

Ruff totals, both exit 1: 96 findings on rollback and 96 findings on the candidate. Line-robust comparison: 0 candidate-only and 0 rollback-only.

Candidate `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6` remains NOT QUALIFIED.

Production remains:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

No deploy, ref move, source/test fix, data repair, or client action without fresh Architect authorization.
