# REL1D-HG2D1 offline release qualification

Result: **NOT QUALIFIED**.

Qualification is local evidence only. It does not authorize deployment.

## Blocker

The frozen candidate failed two required checks:

- `ruff check app tests` from `backend/` exited 1. Ruff 0.16.5 reported 96 errors. Counts: I001 38, F401 36, UP017 3, SIM117 3, RUF059 3, BLE001 2, SIM102 2, F811 2, F841 2, SIM222 1, FURB162 1, SIM114 1, ISC004 1, RUF012 1. Findings were not auto-fixed.
- The full non-live backend suite exited 1. Emitted summary: `716 failed, 3630 passed, 3 deselected, 170 warnings, 8 errors in 280.36s (0:04:40)`. The summary line does not report skipped or xfailed tests.

The suite command, from `backend/`, was:

`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -m "not live" -q --tb=no`

No runtime, test, or Ruff fix was applied.

## Identity

- Candidate SHA: `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`
- Rollback/production SHA: `bc69c6fa5c0735db9509d12dd5f77e6285e45901`
- Expected Alembic revision: `0054`
- `origin/main` at qualification: `83eb3dfd8380047a93078f8634a9c6b2020cd712`
- `origin/production` at qualification: `bc69c6fa5c0735db9509d12dd5f77e6285e45901`

## Git safety

- `bc69c6fa5c0735db9509d12dd5f77e6285e45901` is an ancestor of `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`.
- The candidate is in canonical `main` history.
- The candidate is 56 commits ahead of the rollback SHA.
- Rollback to candidate changes 37 files.
- Migration infrastructure changes (`backend/alembic/versions/`, `backend/alembic/env.py`, `backend/alembic.ini`, `backend/alembic/script.py.mako`): 0.
- `ops/production/` changes: 0.
- `git diff --quiet f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6 origin/main -- backend` succeeded. Commits after the candidate do not change `backend/`.

## Test evidence

- Full non-live command and totals: see Blocker. Exit code 1.
- Focused HG2 union, from `backend/`:

`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -q --tb=line tests/test_rel1d_hg2a_scan_window.py tests/test_phase_27b_mattermost.py tests/test_rel1d_hg2b2_mail_recipients.py tests/test_rel1d_hg2b3_mtproto_sender.py tests/test_rel1d_hg2c2_mtproto_sender_repair.py tests/test_rel1d_hg2c3_mattermost_author_repair.py tests/test_rel1d_hg2c4_teams_sender_kind_repair.py tests/test_rel1d_hg2c5_gmail_recipient_repair.py tests/test_rel1d_hg2c6_yandex_mail_recipient_repair.py tests/test_rel1d_role_import_participants.py tests/test_telegram_mtproto_a3.py tests/test_telegram_mtproto_a4.py tests/test_telegram_mtproto_a4_2.py`

Emitted summary: `241 passed, 11 warnings in 17.74s`. Exit code 0. Failed count 0.

- Ruff: failed, 96 errors, as in Blocker.
- `git diff --check bc69c6fa5c0735db9509d12dd5f77e6285e45901 f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6` exited 0.
- Local Alembic script graph heads: `['0054']`. Exactly one head.

## Release boundary

The candidate is not QUALIFIED. Git ancestry, the empty migration and `ops/production` deltas, the single Alembic head `0054`, whitespace check, and the focused HG2 union are green. The full non-live suite and Ruff are not.

Qualification is not deployment authorization. `production` was not moved. No SSH, provider call, production database access, data repair, or client rollout occurred. Human REL1D acceptance remains paused. Release authorization requires a fresh Architect decision after review.
