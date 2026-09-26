# Current task — HOLD

Visual Task Map V3B fCoSE local-refinement spike is recorded. Implementation `e1ad6de211b350c97a1eff1ed3ff53da763ee3fd`.

Do not choose a final graph technology from this result.
Do not retry Graphviz, start islands/Areas, or add an edge router.

- Dependency: `fcose` 0.1.0. Lock delta is only that package. The current Graph renderer remains the default. V1 and V2 stay available. People mode stays on the current renderer. `package:fcose` is imported only by `client/lib/graph/fcose_graph_refiner.dart`.
- `GraphGeometryScene` / `GraphGeometryRefiner` / `GraphGeometryResult` is the engine-neutral contract. Routes are optional and fCoSE returns none, so the current straight edges stay.
- Preserve: `randomize: false`, `quality: proof`, `seed: 1`, `idealEdgeLength: 50`, selected Task and obstacles in `fixedNodes`. Relax is the same except `idealEdgeLength: 90`.
- Fixed-node drift was 0.00 px in every fixture and both modes. Overlap-stress overlaps went 1→0. The current flower did not stay recognizable: every movable node moved, and overlaps increased.
- Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.
