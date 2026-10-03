# Current task — HOLD

AH2-CLI1 human client regression is **ARCHITECT ACCEPTED**. AP1, STG1, and UX-CAP1 have now been verified on the installed exact-production Linux client. Do not start another Executor slice, deploy, migrate, or rebuild/install the client from this HOLD without fresh Architect authorization.

## Current production/client state

- Production backend: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Installed Linux client source: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Alembic: `0052 / 0052`
- Backend health: PASS
- Flutter: 3.47.5
- Dart: 3.13.4
- No backend deploy or migration occurred during AH2-CLI1

## AH2-CLI1 human acceptance

### AP1 semantic approval presentation — PASS

On fresh Task `test1`, the PER1/CTX1 flow was exercised:

1. `Жду ответ от Оли Володько по черновику`
2. Secretary suggested `Ольга Володько` without mutation.
3. User confirmed `Да, Ольга Володько.`.
4. Pending approval card showed:
   - `Изменить задачу: test1`
   - `Ожидает: Ольга Володько`

Acceptance facts:

- raw UUID is no longer the primary approval label;
- Task title is human-readable;
- waiting-on Person is human-readable;
- internal mutation approval uses the AP1 semantic presentation snapshot.

### STG1 pre-approval truth — PASS

For the same staged mutation:

- no model-authored prose claimed the update had already happened;
- the approval card remained visible;
- execution still awaited explicit approval.

### UX-CAP1 fresh capture isolation — PASS

Human sequence:

1. opened an existing object;
2. started contextual Task capture;
3. entered recognizable abandoned draft text `CTX abandoned draft`;
4. closed the contextual capture without submitting;
5. opened global `+ Задача`.

Observed fresh global capture:

- title empty;
- description empty;
- no abandoned draft text;
- no visible prior source/context;
- no leaked contextual session state;
- no action/approval created.

This confirms the stale capture-context leak is closed on the installed client.

## Remediation status

Human-accepted on the current production/backend+client combination:

- UX-CAP1 / UX-CAP1.1 capture isolation;
- AH2-AP1 semantic approval cards;
- AH2-STG1 pre-approval truth boundary;
- AH2-PER1 conservative Person name-variant flow;
- AH2-CTX1 selected-Task waiting-on routing.

Source-accepted and already deployed:

- AH2-FIN1 post-approval language continuity;
- AH2-FIN2 deterministic temporal display facts;
- AH2-SEM1 unsupported-relation boundary.

No new remediation or product slice is authorized by this HOLD.

## Next product direction — not yet authorized

The largest remaining product backlog item from the AH2 manual acceptance is first-class Scheduled Activity product integration:

- Today/Week visibility;
- distinct Scheduled Activity presentation;
- mobile-visible alert at due time;
- tap-through;
- recurrence semantics without duplicate rendering.

This is broader than the completed remediation chain and should begin only as a fresh Architect-authorized product slice.

Other residual backlog remains separate:

- selected context readability/polish;
- T1 final terminology polish;
- original P1 exact-two-Anna and R3 ambiguity edge cases remain manual-unverified;
- stale deterministic test debt should be cleaned separately, without weakening safety.

## HOLD

Do not start:

- Scheduled Activity integration;
- stale-test cleanup;
- another backend rollout;
- another client build/install;
- migrations;
- any other remediation/product slice.

Wait for fresh Architect/user authorization.
