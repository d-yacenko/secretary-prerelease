# Current task — Verify Telegram summary self-authorship correction locally

## Architect review

Commit:

`8ae75dc9e2b6b05e8caa4b966caafc7bbcb63574`

implements the requested separation of Telegram marker membership from base self-authorship.

Architect static review accepts the code shape:

- `self_authored_block()` requires canonical MTProto, matching account, outbound direction, present sender/account Telegram identity, and sender == connected Telegram user id;
- it does not require `TG_SELF_E2E_0922A`;
- `message_identity_block()` layers the marker requirement on top for selected E2E messages;
- `prove_cohort()` still uses the marker-bearing proof;
- `prove_summary_cohort()` uses the base self-authorship proof;
- the remote `docker compose exec` acceptance path is unchanged;
- focused regression tests cover the self-authored outbound non-marker neighbor and fail-closed identity cases.

The prior live authorization is consumed. No live E2E is authorized.

## Required local verification

From a clean canonical checkout at exact `8ae75dc9e2b6b05e8caa4b966caafc7bbcb63574`, run only local code/test checks.

At minimum:

```bash
cd ~/work/secretary-prerelease
git switch main
git pull --ff-only
git fetch --prune origin
test "$(git rev-parse HEAD)" = "8ae75dc9e2b6b05e8caa4b966caafc7bbcb63574"

cd backend
pytest -q tests/test_telegram_self_authored_e2e.py
python -m py_compile ../ops/production/telegram_self_authored_e2e.py tests/test_telegram_self_authored_e2e.py
ruff check ../ops/production/telegram_self_authored_e2e.py tests/test_telegram_self_authored_e2e.py
ruff format --check ../ops/production/telegram_self_authored_e2e.py tests/test_telegram_self_authored_e2e.py
cd ..
git diff --check
```

If the repository's standard command uses `uv run ruff` rather than a direct `ruff` executable, use the existing project-local standard without changing dependencies.

Do not modify code unless a check fails.

## Report

Return:

- exact HEAD;
- focused pytest result;
- py_compile result;
- Ruff check result;
- Ruff format-check result;
- git diff --check result;
- any failure output, sanitized.

Then STOP.

## Hard stop

No production SSH.
No production Docker/Compose.
No remote wrapper execution.
No live E2E.
No provider calls.
No Telegram transport/session access.
No production DB writes.
No deploy/restart/recreate.
No production env changes.
No production ref movement.

A new live attempt requires Architect acceptance of the verification result and fresh explicit human authorization.
