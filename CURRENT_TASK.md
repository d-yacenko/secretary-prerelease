# Current task — HOLD

SW2-A semantic overview components are Architect-reviewed and SOURCE-ACCEPTED.

Accepted implementation:
- `1b6943ba4f7cc49df1465791d812d45db6d26b52`
- executor HOLD: `b9402d014a1a30cb0485078280e0a62e395e4827`

Accepted semantics:
- unrooted Tasks overview soft-pagination unit is one connected component of the confirmed visible Task map;
- confirmed visible Task↔Task relations, including `part_of`, `depends_on`, `references`, and `related_to`, join the component;
- proposed/rejected edges, actor-role edges, label/temporal hidden edges, Task↔Flow edges, and Person edges do not join Task components;
- priority Flow evidence may appear in more than one window but does not glue Task components;
- a component larger than the soft target stays whole;
- the existing emergency complete-window ceiling remains fail-closed;
- rooted Graph and People behavior are unchanged;
- canonical Task layout remains `task-map-v2.1.1`;
- no schema/Alembic/client-source change was required.

Architect review confirmed the publication regression fixture: Direction + five confirmed `related_to` publication petals remain together while an unrelated Task moves to a later window. Proposed/rejected/hidden/Flow boundaries and the emergency ceiling are covered by focused backend tests.

Human verification is still PENDING because the installed client currently talks to the old production backend.

## Deployment boundary

Do not deploy, move `production`, restart production services, run Alembic, or begin SW2-B without a new explicit Architect/user authorization.

The next authorized action, after explicit user approval, should be a schema-neutral SW2-A backend rollout/human-gate preparation from the reviewed source. Preserve production data/volumes/.env and keep Alembic at `0052 / 0052`.

Production currently remains `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, Alembic `0052 / 0052`. STOP.
