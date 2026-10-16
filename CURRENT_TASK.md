# CURRENT_TASK

HOLD

## REL1D-HG6A — instant Person authoring and context-aware People stratification

ARCHITECT ACCEPTED.

Implementation:
`82f47d2f0e53da1069709186df051f8d543c43c5`

Executor HOLD:
`ca9b0e1a56a2bb212b7035db6213c79c89c39769`

Architect acceptance:
`496049e3da451b9cdcf390c4b3bb15fc9062a6d6`

Accepted facts:

- client-only implementation;
- overview Person opens immediately from existing presentation;
- heavy rooted truth hydrates in background;
- root-only empty sections show loading rather than false final empties before hydration;
- hydration failure preserves usable summary and offers retry;
- role/context assign/retract patches authoritative returned assignment locally without People workspace refresh;
- stale pre-mutation rooted reads cannot restore older role/context state;
- context tint derives only from active role context;
- no-context keeps default card surface;
- deterministic context family/exact keys drive subtle theme-derived color;
- same-anchor People use deterministic gravity-like local attractors and non-overlapping slots;
- packed cluster is recentered on the unchanged Task-derived base before inter-cluster collision separation;
- unanchored People remain on the global shelf with context-aware sub-clustering;
- no backend/schema/production/Task-topology/Agent-harness change.

Checks accepted:

- focused Flutter tests: 91 passed;
- `person_roles_section_test.dart` passed on the successful rerun after an earlier package-loading hang;
- Dart analyze: 0 errors, pre-existing infos only;
- `git diff --check`: clean.

Production remains:
`0031f531d1215970093bea7add44fcd2259ec71b`

Alembic remains:
`0054 / 0054`

No deploy is required for HG6A because backend did not change.

Human verification now requires a freshly rebuilt client from current `main`:

1. selecting a Person from People overview should make the summary/details usable immediately rather than showing the old blocking ~10s spinner;
2. heavy sections should hydrate progressively in the background and preserve the summary if hydration fails;
3. adding/removing role context should repaint the detail and compact overview card immediately without a full People refresh;
4. no-context cards should keep the default appearance;
5. equal/related contexts should have stable readable related tints;
6. within one Task-anchor cluster, same/related contexts should form useful compact local visual groups without changing the Task-derived world position of the cluster;
7. unanchored People must remain on the shelf.

No Executor coding/deploy task is active.

Do not start backend evidence-snapshot optimization, identity-candidate/email discovery, Agent/harness review, or another phase without fresh Architect authorization.
