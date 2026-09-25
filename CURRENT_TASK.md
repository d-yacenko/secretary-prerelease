# Current task — Task Refinement T4: operational projection in Today

Task Refinement T1/T1R, T2, and T3 are architect-accepted.

Implement only the integration of the canonical T3 Task operational/actionability projection into the existing Today task surface.

Do not implement automatic Task discovery from Flow, proactive notifications, importance scoring, a new focus dashboard, project/roadmap semantics, new persisted Task state, LLM classification, provider calls, or production deployment.

## Product intent

Today already chooses a bounded set of non-terminal Tasks by due date. T4 must make that existing list easier to interpret by reusing the same canonical operational truth already shown in Task Profile.

There must not be a second client-side definition of blocked/waiting/delegated/actionable/overdue.

## Goal

For every Task already returned in `GET /today`:

- return the canonical T3 operational projection;
- show one compact operational cue in the existing Today Task row;
- use the shared T3 overdue truth instead of Today's separate client-only overdue calculation;
- keep the current Today inclusion rule and due-date ordering unchanged.

T4 is an integration/refinement step, not a new ranking system.

## 1. Preserve Today membership semantics

Do not broaden the Today Task query in T4.

The existing server rule remains authoritative:
- active same-user Task;
- non-terminal lifecycle;
- has `due_at`;
- due today or overdue according to the existing Today day window;
- existing `TODAY_MAX_TASKS` bound;
- existing due-time ordering.

Do not add Tasks merely because they are actionable, waiting, delegated, blocked, or planned for today.

Do not change calendar-event or notification membership.

## 2. Reuse canonical T3 projection

Reuse `TaskOperationalProjectionService` / the canonical T3 conversion shape.

Do not reimplement operational precedence in `TodayService`, API route code, or Flutter.

For the bounded Today Task result, derive projections in batch rather than issuing one profile/projection query per Task.

The batch must stay bounded by the existing Today Task cap and the T3 projection service contract.

If the current T3 internal batch cap is lower than the Today cap, resolve this deliberately without an N+1 fallback:
- either support a bounded chunked projection helper internally; or
- align a safe internal bound with the existing Today cap.

Do not expose an unnecessary new public batch endpoint.

## 3. Today API shape

Extend the Today Task item with one nested `operational` object using the same schema/field semantics as canonical Task Profile.

Prefer a Today-specific response model that preserves the existing Task object fields and adds `operational`, rather than changing generic `ObjectOut` globally.

The operational nested shape must remain semantically identical to T3:
- `operational_state`;
- `is_overdue`;
- `is_scheduled_later`;
- `is_planned_now`;
- time fields;
- bounded blocking/waiting/delegation summaries;
- `reason_codes`.

Do not add a second Today-specific operational vocabulary.

## 4. One coherent `now`

A single Today snapshot must use one coherent reference instant for:
- local day boundaries;
- T3 operational derivation.

Do not call `datetime.now()` independently per Task.

When `reference_at` is supplied in tests/service calls, pass that same instant into operational projection.

## 5. Overdue semantics

The Today UI must stop deriving its own overdue truth from `day_start`.

Use `operational.is_overdue` from T3.

This intentionally fixes the semantic gap where a Task due earlier today is already overdue at the current instant even though it is not before local midnight.

Do not change the server Today membership rule: a task due earlier today was already a Today member; only its displayed overdue truth becomes canonical.

Terminal Tasks still cannot be operationally overdue, though Today should already exclude them.

## 6. Today UI

In the existing Today Task row, show the same compact operational labels already used by Task Profile:
- blocked -> `Заблокировано`;
- waiting -> `Ждём`;
- delegated -> `Поручено`;
- scheduled_later -> `Запланировано позже`;
- actionable -> `Можно действовать`;
- terminal -> no extra operational cue.

If `operational.is_overdue` is true, show the existing concise `Просрочено` cue separately.

Reuse the shared `operationalStateLabel` helper.

Do not render reason-code lists, actor lists, blocker lists, scores, or a new Task Profile inside Today.

Keep existing Task tap, bookmarks, labels, action row, and delete behavior unchanged.

## 7. Client model

Parse Today Tasks with their nested operational projection.

Avoid maintaining two incompatible Task operational model classes. Reuse the existing `TaskOperationalProjection` model.

If a compatibility fallback is required for an older server response without `operational`, it may be visually silent, but it must not recreate operational/overdue logic client-side.

## 8. Determinism and boundedness

Required invariants:
- no N+1 Task Profile calls;
- no per-Task REST calls from Flutter;
- no all-Task scan beyond the existing bounded Today query;
- no recursive dependency traversal;
- proposed/rejected relations still do not affect Today operational cues;
- operational presentation summaries remain bounded exactly as in T3;
- current Today due-date ordering is preserved.

## Focused proof

Add tests proving at minimum:

1. Today API Task items include the canonical nested operational projection.
2. A plain due-today active Task can return `actionable`.
3. Confirmed waiting/delegated/dependency relations produce `waiting` / `delegated` / `blocked` in Today.
4. Proposed waiting/dependency relation does not change the Today operational state.
5. A completed dependency does not block the Today Task.
6. A Task due earlier on the same local day but before `now` has `operational.is_overdue=true`.
7. A Task due later today has `is_overdue=false`.
8. Existing Today membership remains due-today + prior overdue only; future-day Tasks remain excluded.
9. Existing Today due-at ordering remains unchanged regardless of operational state.
10. Operational projection for the Today list is batch/bounded and does not use one profile/projection query per Task.
11. Flutter Today renders the correct compact operational cue.
12. Flutter Today renders `Просрочено` from `operational.is_overdue`.
13. Flutter no longer determines overdue from `day_start`.
14. Proposed relation data cannot alter a server-provided actionable cue.
15. Existing Today calendar/notification/task interactions remain green.
16. Existing T3 Task Profile tests remain green.
17. No migration, new persisted operational field, new public focus endpoint, scoring, auto-discovery, proactive notification, Project entity, provider call, or deploy.

Run:
- `backend/tests/test_today.py`;
- `backend/tests/test_task_operational.py`;
- relevant Today API/schema tests;
- `client/test/today/today_test.dart`;
- T3 Task Profile UI/domain-label tests;
- Flutter analyze touched files;
- Ruff/compile touched Python;
- `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- push to `origin/main`;
- STOP.

Do not begin automatic Flow-to-Task obligation discovery, proactive attention/notifications, scoring/ranking, project/roadmap semantics, or deploy.
