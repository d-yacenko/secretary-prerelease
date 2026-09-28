# Current task — HOLD

People R4-H1 diagnostic is `0f062515687d0a9170a086bf530bb2ce9e4e100f` in `docs/people_r4_salience_truth_diagnostic.md`.

A visible recent communication with every communication-derived salience component at zero is the confirmed 200-versus-400 scan split: salience scores only the newest 200 in-window messages, while the rooted communication projection examines 400. Row 201 stays on the card, sets `salience.truncated`, and still renders as a definitive zero because the UI does not show that flag. Yandex folder rules are shared and do not cause that shape. `task_calendar = 0` means no explicit Person-to-work edge; mentions in title or body do not count. The next slice, not started, is to score rooted communication salience from the rows the rooted projection already examines, leave overview ranking on the 200-row scan, and show truncation.

Production/runtime and `origin/production` remain `8cf5f3a14dd2eb70dc754d87b2f90a7589aa8b4f`. Rollback remains `1b851f91bd37d0e79531ef740b02febb3c3af69d`. Alembic remains `0050`.

Do not deploy. Do not implement the salience correction until it is explicitly authorized.
