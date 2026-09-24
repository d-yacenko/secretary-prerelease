# Current task — Complete verification for unified generative model selector

## Review state

Implementation `6b22bdc94e5c993a44d6d9b719a1dbbbcbfea529` is functionally accepted by Architect review, but is NOT YET marked DEPLOY-READY because two required verification results were not explicitly recorded:

- `py_compile`;
- Ruff format check.

Production remains exact `54888ed5797b4b84fa663ff8be11b8b74c64e2a6`, Alembic `0046`.

## Authorization

Verification-only. No production mutation. No live OpenAI/provider calls.

## Required sequence

1. Bootstrap from current canonical `origin/main`; require clean worktree.
2. Verify implementation SHA `6b22bdc94e5c993a44d6d9b719a1dbbbcbfea529` remains an ancestor of current main and no implementation code has changed since its ledger commit except task/state ledger files.
3. Run Python compile verification for every Python file changed by `6481afec6794206e71d6882b163208b87622a976..6b22bdc94e5c993a44d6d9b719a1dbbbcbfea529`.
4. Run `ruff format --check` on every Python file changed in that same implementation delta.
5. If Ruff format check passes, record PASS.
6. If Ruff format check fails:
   - do not reformat immediately;
   - determine whether each failing file also failed the same format check at the exact parent baseline `6481afec6794206e71d6882b163208b87622a976`;
   - if failure is pre-existing and implementation did not worsen it, record that bounded evidence;
   - if implementation introduced a new format failure, fix only that implementation-caused formatting issue, rerun the relevant focused tests/checks, commit the minimal correction, and report the new implementation SHA.
7. Re-run `git diff --check` and `docker compose config --quiet`.
8. Do not run paid/live OpenAI requests.
9. Record exact sanitized verification results in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, push, and STOP.

## Not authorized

No production deploy/ref movement/env change, DB mutation outside tests, Google/OAuth, Telegram, nginx, DNS/firewall, or unrelated code work.
