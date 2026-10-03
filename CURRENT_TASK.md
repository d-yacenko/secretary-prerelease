# Current task — HOLD

REL1 People-role design is under Architect/user refinement. The previously authorized REL1A task is paused and MUST NOT be executed in its prior form.

## Why paused

The user clarified an important product requirement:

- Person roles must not be a closed predefined dictionary;
- role vocabulary should behave more like an emergent keyword/tag vocabulary;
- existing roles should be suggested/reused during manual or agent-driven assignment;
- new roles must still be creatable when genuinely needed;
- trivial duplicates caused by case/whitespace must collapse deterministically;
- semantic near-duplicates must not be auto-merged silently;
- the model should prefer existing canonical role terms but may propose a new term when needed.

The architecture is being refined before implementation.

## Current accepted baseline

- Main before this HOLD: `fc4837dae84b1978f99c45bd93e93057c79a2d6a`
- Production backend: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Installed Linux client source: `2314bf72101fbd83d50a7b264154d73740e28db1`
- Production Alembic: `0052 / 0052`
- Production health: PASS

## Provisional design direction — NOT AUTHORIZED

Likely shape under discussion:

1. a user-scoped canonical role-term vocabulary, created incrementally;
2. Person-to-role assignments as separate durable facts;
3. optional free-text context on an assignment;
4. deterministic lexical normalization for exact duplicates only;
5. autocomplete/reuse-first UX;
6. no automatic semantic synonym merge;
7. no role-based importance/proactive change until the role model is accepted.

Do not implement this provisional design yet.

## HOLD

Do not start:

- REL1A;
- Person-role schema/migration;
- proactive/importance changes;
- screenshot/org-chart import;
- Organization work;
- Scheduled Activity work;
- deploy/migrate/client install.

Wait for a fresh Architect authorization after the role-vocabulary concept is finalized.
