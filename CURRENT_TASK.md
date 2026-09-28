# Current task — People R4-H2: rooted salience truthfulness correction

## State

- Current `main` before this authorization is `e8e2aca73e550c0dc1dea31ea464cf3cf91a4736`.
- H1 diagnostic commit is `0f062515687d0a9170a086bf530bb2ce9e4e100f`.
- Read `docs/people_r4_salience_truth_diagnostic.md` before changing code.
- Production/runtime and `origin/production` remain `8cf5f3a14dd2eb70dc754d87b2f90a7589aa8b4f`.
- Rollback remains `1b851f91bd37d0e79531ef740b02febb3c3af69d`.
- Alembic remains `0050`.

H1 proved a rooted truth inconsistency:

- rooted recent communication count / recent Flow can inspect up to 400 newest in-window communication Objects;
- rooted salience currently scores only the newest 200;
- a Person communication at global row 201 therefore remains visible but contributes zero communication-derived salience;
- `salience.truncated` is already returned and parsed but the rooted UI does not show it.

Row 200 is currently scored. Row 201 is the first divergent row. Row 401 is outside both rooted communication and salience truth under the current 400-row rooted boundary.

## Goal

Make the rooted Person activity surface truthful and internally consistent without changing the overview/ranking model.

A communication that is inside the bounded rooted communication truth set must not be omitted from rooted salience merely because the generic overview salience scan is smaller.

When the rooted activity calculation is incomplete because of a bounded scan or existing hit caps, the UI must say so instead of rendering the numbers as if they were complete.

## Core invariants

1. **Rooted truth aligns with rooted truth.** The rooted Person salience calculation must use the same 90-day / 400-row communication examination boundary as rooted recent communications.
2. **Overview remains unchanged.** `PersonSalienceService.rank()` and People overview ordering stay on the existing 200-row communication scan.
3. **The salience model is unchanged.** Do not change score weights, decay, direct/public classification, reciprocity, frequency cap, attention points, task/calendar points, tiers, or the 90-day window.
4. **Attribution semantics are unchanged.** Do not change Gmail/Yandex/Telegram/Teams/Mattermost direction, identity, or exposure rules.
5. **Bounded evidence stays explicit.** If rooted salience is truncated, the first-party UI must visibly disclose that the activity calculation is based on a limited set.
6. **No inferred work relation.** `task_calendar` continues to depend on an explicit Person-work edge. Do not infer it from titles, bodies, names, or email strings.

## Backend correction

Implement the smallest maintainable separation between:

- overview/ranking salience: existing 200-row scan;
- rooted Person salience: 400-row scan matching the rooted Person communication boundary.

Preferred shape: introduce a clearly named rooted evaluation path or an internal evaluator that accepts the already-defined rooted scan limit. Do not silently change the meaning of `rank()`.

Avoid duplicating attribution logic. Rooted scoring must continue through the existing canonical `attribute_communication` / `score_person` semantics.

Do not increase any boundary above the existing rooted communication maximum of `MAX_PERSON_SCAN_ROWS = 400`.

It is acceptable for rooted salience to perform its own deterministic query with the same ordering/boundary, or to reuse preloaded rows if that produces a smaller/cleaner diff. Do not introduce cross-service mutable state or a cache in this slice.

Preserve the existing meaning of `PersonSalience.truncated`:

- true when the rooted communication examination is incomplete because more than 400 in-window communication Objects exist;
- true when existing per-person hit caps truncate scored evidence;
- otherwise false.

Do not hide truncation merely because some hits were successfully scored.

## Rooted People integration

Only the rooted Person truth projection should use the new rooted salience evaluation.

Overview/search behavior, candidate discovery, routes, task involvement, recent Flow projection, and communication counts remain unchanged except as needed to call the corrected rooted evaluator.

Do not create new Person<->Flow edges or any persistent salience state.

## Flutter truthfulness

The client model already carries `salience.truncated`. Keep that contract.

In the rooted `Активность` section, when `person.salience.truncated == true`, render one compact human-readable disclosure after the existing activity disclaimer and before/near the component values.

Use wording equivalent to:

`Показана часть активности: расчёт ограничен доступной выборкой коммуникаций.`

The exact Russian wording may be adjusted for UI fit, but it must communicate **incompleteness**, not an error and not a probability.

When `truncated == false`, do not add noise.

Do not replace individual numeric zeros with guessed values, dashes, or "unknown". The correction is to align the rooted scan and disclose the remaining boundedness.

## Required regression coverage

### Backend

Add durable regression tests for the corrected invariant. At minimum prove:

1. a rooted Person communication at global row 200 contributes to rooted salience;
2. a rooted Person communication at global row 201 also contributes after H2;
3. a rooted Person communication at global row 400 contributes after H2;
4. a communication at global row 401 is outside the rooted communication truth set and does not need to contribute;
5. rooted `salience.truncated` is true when more than 400 in-window communication rows exist;
6. overview/rank still uses the existing 200-row scan and does not expand to 400;
7. existing Yandex attribution semantics are unchanged;
8. `task_calendar` still requires an explicit Person-work edge.

The regression should assert product invariants after the fix, not encode the old broken 200-vs-400 behavior.

Run the relevant existing suites for:

- Person salience;
- Person Assistant communication attribution/counting;
- rooted Person truth surface;
- People workspace.

### Flutter

Add focused coverage that:

- rooted Activity renders the truncation disclosure when `salience.truncated=true`;
- it does not render the disclosure when false;
- existing activity component values and disclaimer still render;
- no candidate/identity/task controls change.

Run the relevant People/Graph tests and touched-file analyzer.

## Build

Produce a Linux debug bundle for human verification.

The later human check should only need to confirm:

- the same real rooted Person no longer shows a recent attributable message while all communication-derived activity remains zero solely because the message was between global rows 201..400;
- if the rooted 400-row boundary is itself incomplete, the activity section visibly says the calculation is partial.

The Executor must not perform or claim the human acceptance.

## Out of scope

- No production deploy.
- No migration or schema change.
- No cap above 400.
- No change to overview/rank scan size.
- No salience formula redesign.
- No new score component.
- No candidate/identity rule change.
- No provider lookup.
- No model/LLM call.
- No sync/discovery/history.
- No Person relationship persistence.
- No Organization ontology.
- No proactive behavior.
- No MCP work.
- No G3B.
- No S3.
- No production data/log inspection.

## Verification hygiene

Use synthetic fixtures only. Do not inspect production or real user rows.

Run Ruff / formatting / `git diff --check` for touched files.

If implementation reveals that the rooted truth cannot be aligned to 400 without materially changing shared salience semantics or overview ordering, STOP and report the blocker instead of widening scope.

## Completion

1. Commit the implementation and focused regression tests.
2. Record exact behavior, checks, and implementation SHA in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - concise H2 behavior summary;
   - Linux debug bundle path;
   - production/runtime unchanged at `8cf5f3a14dd2eb70dc754d87b2f90a7589aa8b4f`;
   - Alembic unchanged at `0050`.
4. Push implementation + HOLD to `main`.
5. Report exact SHAs, test results, analyze result, bundle path, and STOP.

Do not deploy and do not start the next People/relationship/Organization slice.
