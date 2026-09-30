# Current task — HOLD

PL1-G3 is implemented at `f7401ec35e7d3cc746c9a9751da406c90660f893` and awaits architect review.

The unrooted Tasks overview consumes one canonical Task-center snapshot (`task-map-v1`). A usable matching snapshot is used directly. Otherwise the client computes centers once from the complete topology endpoint, PUTs that snapshot, and retries a stale revision at most once. A second failure falls back to the existing non-persisted window layout and does not persist it. People rendering, rooted Task view, shared camera behavior, production, and PL1-G4 were not changed.

Production/runtime remains `666683134797948871266e84fd105f0ca0c43476`. Production Alembic remains `0051 / 0051`. Repository Alembic head remains `0052`.

No further implementation is authorized until this file leaves HOLD.
