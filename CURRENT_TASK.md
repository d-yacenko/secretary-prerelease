# Current task — ACTIVE

## AH2-FIN2 — deterministic temporal display facts for post-approval finalization

Architect review before this authorization:

- AH2-FIN1 implementation: `130066cfecb18bb1ee177c8256483f4c3a2142fc`
- AH2-FIN1 HOLD: `47acbaa4c8d539bc34157b9606597838c1e32ba2`
- AH2-FIN1: **ARCHITECT SOURCE-ACCEPTED**
- production remains `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- Alembic remains `0052 / 0052`

AH2-FIN1 acceptance basis:

- persisted finalization resolves the initiating user turn by `pending_action_plan_id` + matching `client_turn_id`;
- language sample is user-scoped, bounded to 500 chars, and labelled as data only;
- finalization instructions preserve execution effects as authoritative and keep the text-only finalizer tool-free;
- no persisted anchor falls back without inventing user text;
- repeated resume returns the stored result without a second finalizer call;
- `success=true` with `changed=false` remains a no-op;
- focused conversation/action-plan tests are green, with no schema, model, network, deploy, or production change.

## Problem observed in manual AH2 acceptance

Two temporal narration defects remain after otherwise-correct approved execution.

### M1 — scheduled activity representation

The user staged:

- `Напомни завтра в 9 позвонить в издательство`

Staging correctly represented 09:00 in the initiating local representation.

After approval, the created Scheduled Activity represented the same instant as 08:00 at another offset, and finalization narrated that server/default-zone representation instead of the wall-clock time the user had approved.

The evidence is consistent with a **representation shift of the same instant**, not proven instant corruption.

### M2 — Task due-date calendar date

The user staged:

- planned interval Tuesday 10:00–12:00;
- due date Friday.

The persisted Task data was correct in the UI:

- planned interval: 2026-10-06 10:00–12:00;
- due date: 2026-10-09 23:59 local.

But finalization narrated the due date as October 10.

This is a user-facing calendar-date error caused by allowing the finalizer to infer date/time semantics from raw execution timestamps / alternate timezone representations.

## Goal

Make post-approval finalization receive deterministic **temporal display facts** so it does not re-derive user-facing wall-clock times or calendar dates from raw UTC/server-offset timestamps.

Execution/persistence remains authoritative for the instant and state change.

The frozen approved action remains authoritative for the user-approved temporal representation **only when it denotes the same instant as the execution output**.

## Core contract

### A. Separate instant truth from display truth

For temporal fields:

- execution result is authoritative for whether the action succeeded and what object/state was persisted;
- frozen approved action arguments capture the temporal representation the user approved;
- when frozen and executed timestamps represent the **same instant**, finalization should present the frozen/user-approved wall-clock representation rather than a server/default-zone rendering;
- when they do **not** represent the same instant, do not hide the mismatch and do not assert the frozen representation as execution truth.

Do not treat a different offset for the same instant as a different scheduled time.

### B. Task due date is a user calendar date

For an approved `update_task` with `due_at`:

- if the execution output's `object.due_at` is the same instant as the frozen `due_at`;
- derive the user-facing due **calendar date** from the frozen approved datetime representation;
- expose that calendar date as a deterministic finalization fact;
- instruct the finalizer not to convert the raw execution timestamp to another timezone and then narrate a different date.

For the M2-shaped case, the finalization fact must preserve **2026-10-09**, not roll to October 10.

Do not change the stored deadline to make narration pass.

### C. Planned interval

For an approved `update_task` with both `planned_start_at` and `planned_end_at`:

- verify each frozen timestamp is the same instant as the corresponding execution-output field;
- expose the approved local start/end representation as deterministic finalization facts;
- preserve the local calendar date and wall-clock interval.

The M2-shaped case must retain Tuesday 10:00–12:00 in the approved representation.

### D. One-shot Scheduled Activity

For `create_scheduled_activity`:

- compare frozen `run_at` to execution output `object.due_at`;
- if they are the same instant, expose the frozen approved local representation for narration;
- finalization must not switch 09:00 to 08:00 merely because execution output was serialized in another zone/offset.

Do not alter the scheduled job instant in this slice.

### E. Recurring Scheduled Activity

If directly adjacent to the implementation, also cover `create_recurring_scheduled_activity` conservatively:

- `local_time` + explicit IANA `timezone` are the user-facing recurring schedule semantics;
- `run_at` / output `due_at` are occurrence instants;
- do not replace the recurring local schedule with a server-zone occurrence representation.

Do not broaden into recurrence redesign.

### F. Mismatch fails safe

If frozen temporal input and execution output differ by instant:

- do not produce a deterministic fact saying the frozen time/date was applied;
- keep execution output authoritative;
- make the mismatch visible to the finalization contract or suppress the derived display fact rather than lying.

If implementation investigation proves that current approved execution actually changes the instant, not merely its representation, **STOP and report** before broadening this task into execution-semantics repair.

## Preferred implementation shape

Keep this in the finalization boundary.

A reasonable shape is a small deterministic helper, for example under `backend/app/assistant/`, that builds temporal finalization facts by pairing each frozen action with its corresponding execution result.

The helper should:

- pair actions/results by order and verify `tool_name`;
- parse only bounded ISO datetimes;
- require timezone-aware values for same-instant comparison;
- compare by UTC instant;
- emit compact machine-generated facts for user-facing narration;
- never execute tools or query unrelated data.

Then include a section such as:

`Temporal display facts (authoritative for user-facing date/time wording; execution results remain authoritative for state/instant)`

before raw execution-result JSON in the finalization context.

Update `FINALIZATION_INSTRUCTIONS` so that when temporal display facts are present, the model must use them for user-facing date/time wording and must not re-derive a different date/time from raw execution timestamps.

Preserve AH2-FIN1 language-source behavior.

## Important boundary

Do **not** fix this by:

- hard-coding a timezone;
- converting everything to `Europe/Amsterdam`;
- assuming UTC is the user's display zone;
- using the current server timezone as the initiating user's timezone;
- trusting frozen arguments when execution produced a different instant;
- removing raw execution facts from the finalizer.

The raw execution result remains evidence. The new temporal display facts disambiguate how an equivalent instant should be spoken to the user.

## Scope

Expected files may include:

- `backend/app/assistant/execution_effects.py` or a new focused temporal-finalization helper;
- `backend/app/services/assistant_service.py`;
- `backend/app/llm/openai_assistant_provider.py`;
- focused finalization/action-plan tests;
- preserved AH2-M / planned-interval tests if directly affected;
- ledger files.

Avoid changes to domain execution unless a deterministic test first demonstrates an actual instant mutation.

## Explicit non-goals

Do not in AH2-FIN2:

- change Task due dates or planned intervals in storage;
- change job scheduling semantics;
- redesign Scheduled Activity;
- add Scheduled Activity to Today/Week/mobile notifications;
- change approval-card rendering;
- fix the A1 pre-approval wording;
- change Person resolution;
- change T3 unsupported-relation behavior;
- change Task/Person/Flow ontology;
- add schema/Alembic migration;
- run real OpenAI/model evaluation;
- deploy or install a client.

A wider end-to-end timezone contract for Today/Week/mobile remains a later product slice.

## Required deterministic tests

At minimum prove:

1. **M1 same instant / different offset**
   - frozen `run_at = 2026-10-02T09:00:00+03:00`;
   - execution output `object.due_at = 2026-10-02T08:00:00+02:00`;
   - helper recognizes the same instant;
   - temporal display fact preserves 09:00 +03:00 for user-facing narration;
   - no claim that execution time changed.

2. **M2 due calendar date**
   - frozen `due_at` is end-of-day on 2026-10-09 in its approved offset;
   - execution output contains the same instant in another offset/UTC representation;
   - finalization fact explicitly preserves calendar date `2026-10-09`;
   - no derived October 10 date.

3. **M2 planned interval**
   - frozen planned interval is 2026-10-06 10:00–12:00 in the approved representation;
   - execution output has equivalent instants in another offset;
   - finalization facts preserve 10:00–12:00 on 2026-10-06.

4. **calendar-day boundary**
   - use an instant whose UTC/server-zone date differs from the frozen local date;
   - prove the user-facing calendar date comes from the approved representation only after same-instant verification.

5. **actual instant mismatch**
   - frozen and output values differ by instant;
   - no "approved temporal representation applied" fact is emitted;
   - finalization context does not instruct the model to state the frozen value as execution truth.

6. **no-op update**
   - `update_task changed=false` does not generate wording that implies a temporal change was applied;
   - existing no-op effect remains authoritative.

7. **context priority / bounds**
   - temporal display facts survive the bounded finalization context ahead of raw execution JSON;
   - AH2-FIN1 language sample remains present and bounded;
   - total context stays within `MAX_ACTION_PLAN_FINALIZATION_CONTEXT_CHARS`.

8. **instruction contract**
   - finalization instructions explicitly distinguish state/instant truth from user-facing temporal representation;
   - raw execution timestamps must not override verified temporal display facts for narration;
   - untrusted-data protections remain.

9. **stored resume idempotency**
   - existing resume result behavior remains unchanged.

No real model call is required.

## Required checks

Run at least:

- `backend/tests/test_assistant_action_plans.py`;
- relevant finalization helper/unit tests;
- `backend/tests/test_assistant_conversations.py` if finalization context plumbing is touched;
- `backend/tests/test_ah2t_planned_interval.py`;
- relevant M1/M2 deterministic eval tests in `backend/tests/test_ah2m_eval_runner.py` if their contracts are touched;
- preserved finalization security/no-op tests;
- `git diff --check`.

Record exact counts.

Model calls: 0.
Real network calls: 0.

## Acceptance criteria

AH2-FIN2 is complete only when:

- M1-equivalent same-instant timezone representation no longer invites 09:00 -> 08:00 narration;
- M2-equivalent due date deterministically remains the user's approved calendar date;
- M2 planned interval remains the approved local interval;
- actual instant mismatches fail safe;
- no-op truthfulness and AH2-FIN1 language continuity remain intact;
- no storage/job/schema semantics are silently changed;
- tests are green;
- production is untouched.

## Completion protocol

After implementation:

1. append a compact factual AH2-FIN2 result to `PROJECT_STATE.md`;
2. record AH2-FIN1 Architect source acceptance in the same ledger update;
3. return `CURRENT_TASK.md` to HOLD with:
   - implementation SHA;
   - changed files;
   - temporal display-fact contract;
   - same-instant vs mismatch behavior;
   - M1/M2 deterministic evidence;
   - exact test counts;
   - confirmation of no schema/model/network/deploy;
4. commit + push to `main`;
5. STOP.

Do not start approval-card UX, Scheduled Activity product integration, or any other remediation item from HOLD.
