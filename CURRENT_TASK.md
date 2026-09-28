# Current task — People R4-H1: salience truth diagnostic

## State

- Current `main` before this authorization is `5678713189f436a058415fb09a7d3f8f8fc33a92`.
- Production/runtime and `origin/production` remain `8cf5f3a14dd2eb70dc754d87b2f90a7589aa8b4f`.
- Rollback remains `1b851f91bd37d0e79531ef740b02febb3c3af69d`.
- Alembic remains `0050`.
- People R4 is deployed and the human visual/semantic gate is in progress.
- The R4 rooted Person surface is visually acceptable so far. Absence of source-derived candidate contacts for one real Person is not by itself a failure: R4 only exposes candidates grounded by the existing conservative candidate rules.

The human gate exposed a trust discrepancy on one real rooted Person:

- the Person has one confirmed email identity;
- rooted detail shows `Недавние коммуникации: 1`;
- `Недавние сообщения` shows one stored Yandex communication from the recent past;
- salience `user_attention` / confirmation contributes 20;
- communication-derived salience components shown in the UI are all zero: directness, reciprocity, frequency, recency, and public exposure;
- `task_calendar` is also zero despite the human remembering Tasks/calendar context involving this Person.

Current code inspection already gives one concrete hypothesis:

- `PersonAssistantService` communication reads use `PERSON_LOOKBACK_DAYS = 90` and may inspect up to `MAX_PERSON_SCAN_ROWS = 400` communication Objects;
- `PersonSalienceService` uses the same 90-day conceptual window but only `MAX_SCAN_ROWS = 200` global communication Objects;
- salience returns a `truncated` flag;
- the current Flutter rooted Person detail renders the numeric salience components but does not surface `salience.truncated`.

Therefore a Person communication ranked between global communication rows 201..400 could plausibly appear under rooted recent communications while contributing nothing to salience, with the UI presenting zeros without explaining that the salience scan was bounded.

This is a hypothesis, not yet an accepted diagnosis.

## Goal

Determine exactly why the existing People truth surface can show attributable recent communication while communication-derived salience appears as zero, and determine whether the current UI can present bounded/unknown evidence as an apparently definitive zero.

This task is **diagnostic only**.

Do not implement the product fix in this task.

## Questions to answer

### A. Reproduce or falsify the 400-vs-200 hypothesis

Using synthetic test data only, construct a deterministic case in which:

1. an active Person has one effective exact identity;
2. one recent communication is attributable to that Person;
3. enough newer unrelated communication Objects exist that the Person communication falls outside the salience scan but remains inside the Person Assistant scan;
4. rooted People detail is read through the real service/API code paths.

Record whether the resulting rooted presentation has:

- `recent_communication_count > 0`;
- a non-empty `recent_communications` projection;
- zero communication-derived salience components;
- `salience.truncated == true`.

Use the smallest deterministic boundary needed to prove the behavior. Do not weaken or enlarge production caps merely to make the reproduction convenient.

Also check the adjacent boundaries around row 200/201 so the finding is not an off-by-one guess.

### B. Compare attribution semantics

Trace the actual attribution paths used by:

- `PersonAssistantService.find_communications`;
- `PersonAssistantService.count_attributable_communications`;
- `PersonSalienceService.evaluate` / `rank`;
- `domain.person_salience.attribute_communication`.

For email/Yandex specifically, determine whether an Object that is accepted as an attributable direct communication by the rooted communication path can still be rejected by salience for a reason other than scan position/truncation.

Check at least:

- inbound Yandex folder semantics;
- outbound Yandex folder semantics;
- sender/from normalization;
- recipients/to/cc normalization;
- direct vs public exposure.

Do not change these semantics in H1.

### C. Establish the meaning of `task_calendar = 0`

Trace `_task_calendar_people` and the rooted Task involvement projection.

State precisely what is required for the Person to receive task/calendar salience.

Verify with synthetic data whether:

- merely having a Task or calendar Object whose title/body happens to mention the Person or their email does **not** count;
- an explicit active graph edge between the Person and a `task|event|calendar_event` does count;
- Task actor roles already materialized as canonical Task->Person edges count according to the current service.

If `task_calendar = 0` is semantically correct when no explicit Person-work edge exists, record that clearly. Do not invent a relationship from textual co-occurrence.

### D. UI truthfulness

Inspect the current rooted Person Flutter presentation.

Confirm whether `salience.truncated` is available in the API/client model and whether the UI communicates it to the human.

If the flag is available but hidden, state exactly how the current UI can make bounded evidence look like a definitive zero.

Do not implement wording or UI changes in H1.

### E. Candidate section

Do not treat the absence of `Возможные контакты` on the observed real Person as a bug unless code-level evidence proves a valid source-derived candidate should have been produced under the existing R4 rules.

R4 must remain conservative:

- no fuzzy auto-attach;
- no new provider lookup;
- no model inference;
- no widening of candidate semantics.

## Required verification

Use existing test infrastructure and synthetic fixtures only.

At minimum run focused coverage for:

- Person salience;
- Person Assistant communication attribution/counting;
- rooted Person truth surface;
- People workspace.

A temporary local diagnostic test/script may be used to establish the boundary, but do not commit a regression test that permanently asserts misleading product behavior merely because it exists today.

If a durable regression test can be written around an invariant that should remain true independent of the eventual fix, it may be committed; otherwise keep the reproduction temporary and record the result in the diagnostic report.

Run Ruff / formatting / diff-check for any committed files.

## Deliverable

Create:

`docs/people_r4_salience_truth_diagnostic.md`

The report must contain:

1. exact current code paths and limits;
2. deterministic reproduction steps and result;
3. whether the 400-vs-200 hypothesis is confirmed, falsified, or only one of multiple causes;
4. any other attribution mismatch found;
5. exact meaning of `task_calendar`;
6. whether hidden `salience.truncated` creates a human trust problem;
7. the smallest plausible correction options, without implementing or selecting a broad redesign;
8. a recommendation for the next narrow implementation slice.

Do not include real person's name, email, Object IDs, message titles/bodies, production row counts, or other user data in the report.

## Production and privacy boundary

This task authorizes **zero production inspection or mutation**.

Do not:

- SSH to production;
- query the production database;
- inspect production logs;
- inspect real Person/Flow/Task rows;
- call any provider;
- call an LLM/model;
- run sync/discovery/history;
- change `origin/production`;
- deploy;
- change `.env`, secrets, containers, volumes, or services;
- create synthetic data in production.

All diagnosis must come from repository code and local synthetic tests.

## Out of scope

- No production deploy.
- No DB migration.
- No schema change.
- No product behavior fix yet.
- No salience cap change yet.
- No candidate/identity semantic change.
- No Person relationship persistence.
- No Organization ontology.
- No proactive behavior.
- No MCP work.
- No G3B.
- No S3.
- No new People feature slice.

If the diagnosis reveals that fixing the discrepancy requires a larger semantic decision rather than a narrow truthfulness correction, STOP and report it; do not expand scope.

## Completion

1. Commit the diagnostic report and any narrowly justified diagnostic/invariant tests.
2. Record the H1 findings and verification in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD with the exact diagnostic commit SHA and one-paragraph conclusion.
4. Push the report/state/HOLD commits to `main`.
5. Report the exact SHAs and the recommended next narrow implementation slice.
6. STOP.

Do not implement the recommended next slice until the Architect explicitly authorizes it.
