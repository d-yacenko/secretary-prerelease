# Current task — PL1-HG3 exact-source single-world human-gate bundle

Authorized base: `4e1defda197262d2f7ce2cf8f430e039a532669b`.
Exact source/release for the bundle: `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
Production/runtime and `origin/production`: `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`.
Production Alembic: `0052 / 0052`.

PL1-R1 rollout is accepted. This task prepares the exact-source client artifact for a human visual/semantic gate. The Executor does not perform the human acceptance.

## Goal

Build a Linux debug bundle from a clean detached checkout of the exact production release so the user can test the new single-world Tasks/People behavior against the matching production backend.

## Source/provenance requirements

1. Verify `origin/production` is exactly the source SHA above.
2. Build from a clean detached checkout of exactly `ffccca38440d2e4eb93e8513a6cb29b4d27b4010`, not from `main`.
3. Do not modify source while building.
4. Record:
   - exact source SHA;
   - build mode;
   - UTC build timestamp;
   - executable path;
   - SHA-256 of the launcher executable;
   - SHA-256 of `data/flutter_assets/kernel_blob.bin` if present;
   - a plain-text provenance file adjacent to the bundle.

## Verification before bundle

Run the focused Flutter suites that cover the release-critical single-world behavior, including at least:

- task-layout API/world tests;
- People landscape/overview/screen tests;
- People world-camera tests;
- the dense anchored-spread regression;
- relevant graph screen smoke / large-canvas fit tests.

Run `flutter analyze` on the changed PL1 Dart files and `git diff --check`.

Record exact pass counts and analyze result.

## Bundle

Produce one self-contained Linux debug bundle in a temporary, clearly named directory under `/tmp`.

Do not install it over the user’s current client.

Do not deploy anything.

Do not call Task-layout product endpoints during bundle preparation.

Do not create/edit Task, Person, or layout rows in production.

## Human-gate intent to record in the bundle notes

The artifact is for the human to verify, on real production data:

- Tasks and People occupy one world, not separately repacked maps;
- switching Tasks -> People -> Tasks does not auto-fit or jump the world/camera;
- returning to Tasks restores the same Task overview window;
- known anchored People visually sit at the expected Task regions;
- same/near-anchor People spread locally without semantic drift or overlap;
- unanchored People form one right-side non-semantic strip outside anchored/world geography;
- unrooted Person markers are compact (140x44) and do not dominate the canvas;
- Task cards are absent in People-only mode;
- manual Fit works correctly in each layer;
- rooted Person/inspector behavior remains unchanged.

Do not hard-code any real Person/Task names into product code. Human examples belong only in the acceptance conversation, not implementation.

## Important expected production behavior

The migration cutover left the layout tables empty. When the human first runs the new client, the product may legitimately create the user-scoped canonical Task layout snapshot through the normal `/graph/task-layout` contract. That is expected presentation-state behavior.

The Executor must not trigger this during bundle preparation.

## Explicitly out of scope

- No production ref movement.
- No deployment or Alembic action.
- No backend or client source changes.
- No installed-client replacement.
- No automated visual acceptance.
- No PL1 acceptance declaration.
- No combined Tasks+People view.
- No later slice.

## Completion contract

When complete:

- record source SHA, artifact path, hashes, provenance path, exact test/analyze/diff results, and confirmation of no production/client mutation in `PROJECT_STATE.md`;
- replace this file with `# Current task — HOLD` and a concise PL1-HG3 bundle summary;
- commit/push ledger changes to `main`;
- STOP.

Do not perform the human gate yourself and do not begin any later work.
