# CURRENT_TASK

HOLD

## REL1D-HG2 — historical repair deferred; forward-path Person Refining acceptance unpaused

Architect decision: historical inbox repair/backfill is no longer on the active delivery path.

The previously authorized source-only task:

`REL1D-HG2D5 — Mattermost one-batch repair canary harness`

is CANCELLED before implementation.

Reason:

- production backend already runs the accepted HG2 forward-path release:
  `f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`;
- fresh/current messages now carry human display names where provider evidence supports a person;
- automated/service sources remain non-personal;
- the product is entering use now and does not require broad legacy inbox recovery;
- completing historical repair would still require separate provider-specific production mutation harnesses/canaries and is not justified by launch value.

Existing repair primitives and census tooling remain in the repository as dormant maintenance capability. Do not delete or execute them.

## Current product state

Production/backend:

`f766cf9e9ed7aa3a56896e61cf370a9a25e6a0c6`

Alembic:

`0054 / 0054`

Installed client remains unchanged from the previously recorded installed SHA.

The forward identity path is deployed. `role_import_participants` consumes stored communication participants only when a human display name and exact attachable identity are present, and filters exact self identities.

## Next action

No Executor coding task is active.

Human acceptance is now UNPAUSED.

The next step is a practical end-to-end Person Refining / role-import acceptance pass using only current/recent communication data.

Acceptance should verify at minimum:

1. recent human correspondents appear by human names rather than technical ids;
2. automated/service/organizational sources do not become Person candidates solely because they sent a message;
3. Person Refining / role-import grounding can use the fresh communication identities for known people;
4. exact self identity is excluded;
5. approving one or more grounded rows creates/reuses the intended Person + role/context without unrelated people;
6. no legacy-history repair is required for this acceptance.

After the human acceptance result, Architect will decide the next product task.

Do NOT:
- run historical repair/backfill;
- execute Mattermost D5 canary work;
- call providers for repair;
- run sync/reconcile solely to enrich old rows;
- mutate production data for legacy enrichment;
- start a new coding phase without fresh Architect authorization.

Every Executor final report, if an Executor is invoked despite HOLD, must stop without implementation and end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
