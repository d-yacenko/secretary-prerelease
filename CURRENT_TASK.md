# Current task — HOLD

People R4-H2 implementation is `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`.

Rooted Person salience now uses the same 90-day / 400-row communication bound as rooted recent Flow. Overview `rank()` stays on the 200-row scan. Score weights, attribution, candidate rules, and task semantics are unchanged. When `salience.truncated` is true, rooted activity shows `Показана часть активности: расчёт ограничен доступной выборкой коммуникаций.` A message inside the 400-row bound contributes; row 401 does not. More than 400 in-window rows, or an existing hit cap, keeps truncation visible even when some hits are scored. `task_calendar` still requires an explicit Person-work edge.

Linux debug bundle for later human review: `/tmp/secretary-r4h2-Xe3OQF/secretary-prerelease/client/build/linux/x64/debug/bundle/personal_secretary`. Human acceptance was not performed.

Production/runtime and `origin/production` remain `8cf5f3a14dd2eb70dc754d87b2f90a7589aa8b4f`. Rollback remains `1b851f91bd37d0e79531ef740b02febb3c3af69d`. Alembic remains `0050`.

Do not deploy. Do not start the next People, relationship, or Organization slice.
