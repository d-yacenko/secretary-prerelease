# Current task — HOLD

AH2-CLI1 installed the Linux client built from production source `2314bf72101fbd83d50a7b264154d73740e28db1`. AP1/STG1 human client regression is now PASS. The next action belongs to the human tester. Do not start another Executor slice from this HOLD.

## AH2-CLI1 — exact-production Linux client

- Client source and production backend: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Alembic remains `0052 / 0052`
- Flutter 3.47.5, Dart 3.13.4
- Focused tests: 101 passed, 0 failed
- Analyze of the seven remediation libraries: 0 errors, 1 pre-existing warning, 7 pre-existing infos
- Staged artifact: `/home/d.yacenko/tmp/cli1-2314bf7-artifact/bundle`
- Installed bundle: `/home/d.yacenko/.local/share/personal-secretary-preview/19228c9d84bbc0350b78e2d0600710dc3ddf368f/bundle`
- Startup smoke: process alive, window present
- Config, secure storage, API URL, and tokens were not read or changed
- No backend deploy, migration, or production-ref change

## Human client regression — accepted so far

### AP1 semantic approval presentation — PASS

On a fresh Task `test1`, the accepted PER1/CTX1 flow was exercised:

1. user: `Жду ответ от Оли Володько по черновику`
2. Secretary suggested candidate `Ольга Володько` without mutation;
3. user confirmed `Да, Ольга Володько.`;
4. a pending approval card appeared with semantic copy:
   - `Изменить задачу: test1`
   - `Ожидает: Ольга Володько`

Observed acceptance facts:

- raw UUID was not the primary approval label;
- the correct Task title was visible;
- the typed waiting-on Person was visible;
- no generic `Update task: <UUID>` fallback was used.

### STG1 pre-approval truth — PASS

On the same staged mutation:

- no free-form model prose claimed the mutation had already happened;
- the pending approval card remained visible;
- execution still awaited explicit human approval.

This satisfies the manual AP1/STG1 client gate.

## Next human gate — UX-CAP1 fresh capture isolation

Executor does not perform this gate.

Goal: prove that abandoned contextual capture state does not leak into a later global fresh Task capture.

Perform exactly this sequence:

1. Open any existing object (Task is sufficient).
2. Start a contextual Task capture from that object using the contextual capture affordance.
3. Enter a recognizable draft title, for example:
   `CTX abandoned draft`
4. If the contextual capture UI visibly shows the source/context, leave it intact.
5. Abandon/close the contextual capture **without submitting it**.
6. From the global navigation, press `+ Задача` to open a fresh Task capture.
7. Do not submit anything yet.

Expected fresh-capture state:

- title is empty;
- description is empty;
- no prior source/context chip or hidden contextual object is carried over;
- no `CTX abandoned draft` text remains;
- no approval/action has been created.

At that point send a screenshot to Architect before creating the fresh Task.

## HOLD

Do not deploy, migrate, rebuild the client again, start Scheduled Activity work, or start another remediation slice. Wait for Architect authorization after the UX-CAP1 human client gate.
