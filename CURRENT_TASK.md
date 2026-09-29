# Current task — PT1-H2: make Person-side actor roles directionally unambiguous

## State

- PT1 source/deploy is live at exact production SHA `02855ee49cc2fe31cd68f4649235d61665dbbcb1`.
- PT1-HG1 exact-release bundle passed source/build checks.
- Human gate exposed a semantic UX blocker: the Person-side role label `Поручено` was naturally interpreted as “this Person assigned the task to me”, while canonical `delegated_to` means “this Task is assigned/delegated to this Person”.
- PT1 is NOT human-accepted.
- People Landscape and all later roadmap slices remain unauthorized.

## Goal

Fix only the Person-side role wording/confirmation so a user cannot reasonably write the opposite Task↔Person fact by misunderstanding direction.

Do NOT change canonical backend role names or edge direction:
- `requested_by`: Task was requested/asked by this Person;
- `delegated_to`: Task is delegated/assigned to this Person;
- `waiting_on`: Task is waiting on this Person;
- `involves`: this Person participates in the Task.

## Person-side add dialog

In `Связать с задачей`, replace ambiguous bare role choices with wording that is explicit relative to the current Person.

The UI must make the direction clear before POST. Acceptable wording pattern:

- `requested_by`: `Этот человек попросил выполнить`
- `delegated_to`: `Задача поручена этому человеку`
- `waiting_on`: `Ждём от этого человека`
- `involves`: `Этот человек участвует`

Equivalent concise Russian is acceptable only if equally unambiguous.

Also show an explicit selected-role summary before the final `Добавить` action, using the current Person title and selected Task title where practical, so the user can verify the fact before mutation. Example semantic meaning:
- `Ольга Володько — попросила выполнить задачу …`
- or `Задача … — поручена Ольге Володько`

Do not infer gender. Avoid wording that requires grammatical gender if the Person title is arbitrary.

## Person involvement tile

Replace ambiguous compact labels such as `Делегировано` with person-relative wording that preserves direction.

At minimum:
- `requested_by` must read as the Person requested/asked for the Task;
- `delegated_to` must read as the Task being assigned to the Person;
- `waiting_on` must read as waiting on the Person;
- `involves` must read as the Person participating.

Keep task navigation and mutation actions unchanged.

## Task-side UI

Do not redesign Task Profile in this slice unless a shared label helper requires a minimal safe adjustment. Its canonical semantics remain unchanged.

## Data / backend safety

- No migration.
- No backend ontology change.
- No role-direction change.
- No production data edits by Executor.
- No automatic repair of the human tester's mistaken relation; the human tester will remove it manually.
- Do not start People Landscape.

## Tests

Add focused Flutter coverage proving:

1. Person-side role picker exposes all four canonical roles with directionally explicit meanings.
2. Selecting `delegated_to` visibly states that the Task is assigned to the current Person before the POST.
3. Selecting `requested_by` visibly states that the current Person requested/asked for the Task before the POST.
4. The resulting Person involvement tile for `delegated_to` cannot reasonably be read as “the Person delegated the Task away”.
5. Existing add/remove/confirm/reject/navigation/idempotency/terminal filtering tests remain passing.
6. No API endpoint or role payload changes.

Run focused Flutter PT1 bridge tests, relevant analyze, and `git diff --check`.

## Completion

Commit/push PT1-H2 to `main`, record exact SHA/tests in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, and STOP.

Do not deploy and do not build a new human-gate bundle until separately authorized.
