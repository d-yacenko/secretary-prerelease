# CURRENT_TASK

HOLD

## REL1D-HG6B — global context palette and compact local gravity packing

ARCHITECT ACCEPTED.

Implementation:
`814aac2f5ce6190ea33de0a77b788be7cb6d9180`

Executor HOLD:
`37a5c1007a54424532e34f32d9d58a2d3833d7ae`

Architect acceptance:
`f195323072ee3f963f65783e681e18483ce08737`

Accepted facts:

- client-only implementation;
- same normalized exact role context maps to one global deterministic visual identity;
- color does not depend on Person id, Task-anchor cluster, semantic window, shelf position, input order, or current population;
- no-context cards keep the default surface;
- related contexts share one family/base-hue neighborhood;
- exact contexts within a family receive deterministic hue/saturation/lightness variation;
- SRE Arenadata and Training Center Arenadata remain one family but meet the explicit minimum rendered-color separation in light and dark themes;
- no persisted color/family state, embeddings, model calls, backend, or schema changes;
- same-anchor mixed-context People pack into a dense deterministic local lattice grouped by family/exact context;
- the packed cluster is recentered on the unchanged Task-derived base before existing inter-cluster collision separation;
- a 13-Person regression fixture fits the required 4x4 compact envelope, has no overlaps, preserves centroid, and is order-independent;
- HG5 topology and HG6A progressive Person authoring/role mutation behavior remain unchanged.

Checks accepted:

- focused Flutter tests: 93 passed;
- Dart analyze on touched Dart: no issues;
- `git diff --check`: clean.

Production remains:
`0031f531d1215970093bea7add44fcd2259ec71b`

Alembic remains:
`0054 / 0054`

No deploy is required because HG6B is client-only.

Human verification now requires a freshly rebuilt client from current `main`:

1. a same-anchor group should read as one dense pack rather than the sparse HG6A cloud;
2. SRE Arenadata and Training Center Arenadata should look related but visibly different in color;
3. the same exact context seen in another Task cluster should keep exactly the same visual color;
4. no-context cards should remain neutral;
5. global Task-derived cluster placement must remain unchanged;
6. if the dense lattice now feels too rigid/tabular, record that as a separate visual UX finding rather than changing topology ad hoc.

No Executor coding/deploy task is active.

Do not start backend evidence-snapshot optimization, identity-candidate/email discovery, Agent/harness review, embeddings, or another phase without fresh Architect authorization.
