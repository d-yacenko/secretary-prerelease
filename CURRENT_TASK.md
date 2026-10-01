# Current task — HOLD

GR1 relation repairability + attached-endpoint visibility is Architect-reviewed and SOURCE-ACCEPTED.

Accepted implementation:
- `0719e9bf5af75a8065a9916d8e27c0247a3921ec`
- executor HOLD: `70792fc7e11d69f1053a864a2fce8bf4931fb799`

Architect review confirmed:

- confirmed removable `agent` relations may be human-rejected in place through the existing relation decision API;
- the persisted edge row/provenance is preserved with `state=rejected`;
- confirmed Task↔Task removal calls the canonical Task-map participation invalidation path exactly once;
- non-Task-map relation rejection does not spuriously advance Task topology;
- user-origin physical `DELETE /relations/{edge_id}` behavior remains unchanged;
- source/system and protected edge types remain unavailable to the generic remove action;
- active proposed and confirmed user/agent Task↔non-Task endpoints for `references`, `related_to`, and `depends_on` are admitted with the Task in overview;
- proposed non-Task endpoints do not join Task semantic components and do not influence canonical Task centers;
- the emergency complete-window ceiling remains fail-closed;
- rooted Task workspace gives direct proposed evidence priority over unrelated ordinary neighbors while preserving bounded/truncated semantics;
- exceptional off-context inventory rows remain navigable and are labeled `вне текущей области`;
- canonical Task layout remains `task-map-v2.2`;
- no schema/Alembic change occurred.

Focused regressions cover:
- agent proposed confirm/reject unchanged;
- confirmed agent `related_to`, directed secondary relation, and `part_of` rejection;
- invalid transitions/origins/protected types/wrong-user boundaries;
- exact topology revision behavior;
- proposed `Program_DYSC.pdf`-style endpoint visible on canvas automatically;
- proposed endpoint duplication across independent Task windows without component gluing;
- soft-window completeness and emergency ceiling;
- client removal paths for agent vs user edges;
- protected/source controls and exceptional off-context navigation.

Recorded checks:
- backend focused suite: 69 passed;
- Flutter focused/regression suite: 130 passed;
- Graph screen analysis: 0 errors, 7 infos;
- `git diff --check`: clean.

Human-check bundle, not installed:
- executable: `/home/d.yacenko/tmp/gr1-0719e9b-artifact/bundle/personal_secretary`
- BUILD_INFO adjacent to artifact;
- build UTC: `2026-10-01T07:08:52Z`
- launcher SHA-256: `59a0f64541ce6aed669cb04a337f9cb9e49f920478e7aae8bdd7bde69692594e`
- kernel SHA-256: `0a92a80a749bcc15b75b40def38172f10e567df25b8bc3146e357b3c6ccd8b6f`

The artifact is workstation-local, so Architect review verified the recorded provenance against the exact implementation SHA but did not independently re-hash the local bytes through GitHub.

## Human/deployment gate

GR1 is NOT human-accepted yet.

Production remains:
- `1b6943ba4f7cc49df1465791d812d45db6d26b52`
- Alembic `0052 / 0052`

The old production backend does not support confirmed-agent rejection or proposed attached-endpoint overview admission, so an end-to-end human check requires a separately authorized schema-neutral backend rollout of the reviewed implementation. The GR1 debug client must also be run/installed manually as a separate human action; do not install it automatically.

Do not move `production`, deploy backend, run Alembic, install/replace the client, or begin another Graph-cleanup slice without explicit authorization. STOP.
