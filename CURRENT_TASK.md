# Current task — PL1-B-H1: align landscape anchors with Task Graph visibility

## State

- PL1-B implementation: `1d6ed13501d1e107855cfde1f8de2b47fe33333e`.
- Production application/runtime and `origin/production`: `44407ed6e972a05809d55874acaa966cc7e141c8`.
- Production Alembic: `0051 / 0051`.
- PL1-B is not yet source-ready because one Task visibility predicate is missing.
- People Landscape UI/geography wiring and PL1-C remain unauthorized.

## Goal

Fix one semantic mismatch in the PL1-B landscape anchor query:

A Task Object whose object `state == rejected` must never appear in `landscape_task_ids`, even when it has a confirmed canonical Task→Person actor edge.

The canonical Task Graph already excludes such Tasks in `GraphWorkspaceService._visible_tasks()`. Landscape anchors must be a subset of the same Task-visible universe.

## Required change

In `PersonGraphWorkspaceService._landscape_task_anchors()`, add the existing fail-closed Task state predicate:

`task.state != REJECTED_STATE`

Use the already-imported `REJECTED_STATE` constant.

Do not otherwise change the PL1-B query, ordering, cap, completeness semantics, role allowlist, or batching.

## Regression tests

Extend focused landscape-anchor coverage to prove:

1. a confirmed canonical actor edge to a visible active non-terminal Task still anchors;
2. a confirmed canonical actor edge to an otherwise active/non-terminal Task whose Object state is `rejected` does not anchor;
3. proposed/rejected actor edges, generic relations, terminal/tombstoned Tasks and duplicate roles retain existing PL1-B behavior;
4. cap/completeness behavior remains unchanged;
5. client parsing remains unchanged.

Run:
- focused landscape-anchor backend tests;
- existing Person truth/workspace suites used for PL1-B;
- focused Flutter model test;
- Ruff;
- relevant Flutter analyze;
- `git diff --check`.

## Scope guard

Do not:

- change schema fields or client model shape;
- change `task_involvement` or `open_task_count`;
- wire anchors into PL1-A or People UI;
- add Task geography context;
- add endpoints or migrations;
- deploy or build a human-gate bundle;
- start PL1-C, social/authority ontology, Secretary Person context, or graph stabilization.

## Completion

1. Commit/push the bounded H1 implementation to `main`.
2. Record exact implementation SHA and test results in `PROJECT_STATE.md`.
3. Return `CURRENT_TASK.md` to HOLD.
4. Report implementation SHA, HOLD SHA, files changed, tests/analyze/Ruff/diff-check, and confirmation that People UI and production remain unchanged.
5. STOP.
