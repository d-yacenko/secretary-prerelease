# CURRENT_TASK

HOLD

## REL1D-HG6D — single-flight Person hydration and visible role API failures

ARCHITECT ACCEPTED.

Implementation:
`3ab15474e7bfd6c5e427b713d8c49092b08b684b`

Executor HOLD:
`c6784639f561885a319cc9fce49b61b4eb4879cc`

Architect acceptance:
`1ab4c94097eb9ffa5af021c31cb74df46893b263`

Accepted behavior:

- background rooted Person hydration allows at most one active rooted People GET plus one replaceable latest pending target;
- rapid A→B→C traversal skips intermediate rooted requests and keeps C's overview summary immediately usable;
- stale success/failure cannot install into the newer selected Person;
- retry uses the same coordinator;
- pending target may be satisfied by existing controller-rooted truth without duplicate fetch;
- rename/presentation, role, and Task-actor generations are captured at actual HTTP dispatch and remain independent;
- role-term search failure shows sanitized API detail and enables typed-role fallback only after failure;
- pending role search does not expose fallback prematurely;
- assign/retract failures preserve existing role state and show sanitized API detail;
- successful role mutation still patches locally without People workspace refresh.

Checks accepted:

- focused Flutter tests: 103 passed;
- Dart analyze on touched Dart: 0 errors, pre-existing infos only;
- `git diff --check`: clean.

Production remains:
`0031f531d1215970093bea7add44fcd2259ec71b`

Alembic remains:
`0054 / 0054`

No deploy is required because HG6D is client-only.

Human verification now requires a freshly rebuilt client from current `main`:

1. rapidly open several different People in succession;
2. continue assigning and retracting roles while moving through the list;
3. verify role suggestions continue to load and mutations continue to succeed;
4. verify no return of the prior pattern where suggestions disappear after several People;
5. if a role request fails, verify the concrete sanitized API message is visible and the current role state is preserved;
6. verify the selected Person summary remains immediate while heavy detail hydrates in the background.

No Executor coding/deploy task is active.

Do not tune backend pool, optimize rooted evidence scans, start identity-candidate/email work, Agent/harness review, or another phase without fresh Architect authorization.
