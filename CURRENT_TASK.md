# Current task — PC1-HG1: exact-release human-gate client bundle

## State

- Production/runtime/origin-production: `a3d546b069e7e05d68fd42906c662c3ba34caef5`.
- Alembic: `0051`.
- PC1 backend is deployed and accepted.
- A human gate attempt used a stale HG3-era client: the screenshot lacked the unconditional `Объединить с…` action that exists in exact release source.
- No product/source correction is authorized in this task. This is a build/provenance task only.

## Goal

Build a fresh Linux debug human-gate bundle from exact source release:

`a3d546b069e7e05d68fd42906c662c3ba34caef5`

so the user can validate PC1 merge/undo against the matching production backend without client-version ambiguity.

## Source discipline

1. Fetch and checkout exact release SHA `a3d546b069e7e05d68fd42906c662c3ba34caef5`.
2. Verify the checkout is clean.
3. Verify source contains:
   - `ValueKey('person-merge')`;
   - visible text `Объединить с…`;
   - merge preview/apply/undo client methods.
4. Do not modify Dart/backend/product code.
5. Do not cherry-pick later documentation commits into the build.

## Build

Build a fresh Linux debug bundle using the repository's canonical client build procedure.

Place it in a new unambiguous path containing the release short SHA, e.g.:

`/tmp/pc1-hg1-a3d546b/bundle/personal_secretary`

Do not overwrite or reuse the previous HG3/PC1 directories.

Create adjacent `BUILD_INFO.txt` containing at least:

- exact source SHA;
- build mode;
- build timestamp;
- launcher SHA-256;
- `data/flutter_assets/kernel_blob.bin` SHA-256;
- explicit line: `EXPECTED_PC1_MERGE_UI=yes`;
- production backend target SHA `a3d546b069e7e05d68fd42906c662c3ba34caef5`;
- statement that production was not modified.

## Verification

Run focused Flutter consolidation tests from the exact release checkout.

At minimum verify:
- Person details render `Объединить с…`;
- merge dialog opens;
- preview blocker disables `Объединить людей`;
- undo row is represented after merge state;
- existing rename action remains.

Run `flutter analyze` on touched/relevant files only if required by the canonical build workflow; no source changes are expected.

## Production safety

Do not:
- deploy;
- move `origin/production`;
- call merge/undo on production;
- write Person data;
- install/replace the user's existing client automatically.

This task only produces a fresh bundle for the human gate.

## Completion

1. Record exact bundle path, launcher checksum, kernel checksum, focused test result, and source SHA in `PROJECT_STATE.md`.
2. Return `CURRENT_TASK.md` to HOLD stating:
   - exact-release PC1 human-gate bundle ready;
   - production remains `a3d546b069e7e05d68fd42906c662c3ba34caef5`;
   - Alembic remains `0051`;
   - human merge/undo gate still pending.
3. Push documentation to `main`.
4. Report bundle facts and STOP.

Do not start Task↔Person, People Landscape, Person removal, Secretary Person context, social roles, graph stabilization, MCP, G3B, or S3.
