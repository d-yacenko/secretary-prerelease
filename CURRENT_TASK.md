# Current task — Telegram Bot API M4BU1: make Stage C verifier internally self-consistent before final live run

## Executor handoff

Continue as implementation executor in the canonical repo.

Read:
- `AGENTS.md`
- `CURRENT_TASK.md`
- latest `PROJECT_STATE.md`
- `DECISIONS.md`
- `ops/production/verify_telegram_bot_stage_c.py`
- `ops/production/verify_telegram_bot_stage_c.sh`
- focused Stage C verifier tests

This is CODE/TEST ONLY. No production SSH or live verifier.

## Accepted baseline

Commit:
`3c6da496fa0d6bb5dc7d4d37b22190c473a5a0bd`

The canonical Git bootstrap changes in that commit are architect-accepted:
- full release SHA restored:
  `bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`;
- target/canonical origin validated before branch lookup;
- authoritative refs use explicit canonical URL;
- no fetch/tracking-ref mutation;
- remote ref checked before Docker/DB.

Do not regress those changes.

## Root-cause correction

The two previous live blockers:

`M4BR1_BLOCKED=local_production_ref`

were directly caused by a 39-character `RELEASE` constant missing the final `b`.

Earlier theories about stale tracking refs / symbolic origin identified real hardening opportunities, now fixed, but they were not the direct cause of those observed blockers.

Preserve this factual correction in `PROJECT_STATE.md`.

## Blocker 1 — protocol field order is inconsistent

The strict parser's `SUCCESS_FIELDS` order does not match the actual order emitted by `remote_main()`.

Current examples:
- `remote_main()` emits `ALEMBIC_0046_PASS` before `APP_HEALTH_PASS`;
- `SUCCESS_FIELDS` expects APP health before Alembic;
- `remote_main()` emits environment markers before the child route/read markers;
- `SUCCESS_FIELDS` expects route/settings markers before environment markers.

Consequences:
- a genuinely successful live verifier transcript would be rejected locally as `remote_protocol`;
- some valid late-stage failure transcripts would also be rejected because failure-prefix validation uses the same incorrect field order.

### Required fix

Create one canonical protocol order matching actual verifier execution.

Prefer the least risky approach:
- define `SUCCESS_FIELDS` in exact emission order; or
- restructure emission to match one documented order.

Do not weaken strict parsing.

The parser must still reject:
- unknown fields;
- duplicates;
- malformed lines;
- out-of-order lines;
- unsafe failure data;
- nonzero mutation/provider counters.

## Blocker 2 — runtime Bot env contract must prove absence, not merely emptiness

Stage C intentionally allows production `.env` to retain the old four Bot keys as empty legacy lines.

But Compose service environments and the actual API/worker container environments must no longer contain those Bot variables at all.

Current `_require_empty()` treats a missing key and a present empty key as equivalent everywhere.

### Required fix

Make the distinction explicit:

- production `.env`:
  four legacy Bot keys may be absent OR present with empty values;
- resolved Compose environment for `api` and `worker`:
  the four Bot keys must be ABSENT;
- actual API/worker container environment:
  the four Bot keys must be ABSENT.

Do not expose environment values.

Use clearly named helpers so this contract is obvious.

## Required end-to-end regression strategy

Do not rely only on a hand-built success fixture derived from `SUCCESS_FIELDS`.

Add tests that exercise `remote_main()` itself with mocked command/runtime/child dependencies and capture its emitted stdout.

At minimum prove:

1. full successful `remote_main()` transcript is accepted by `parse_output()`;
2. emitted key sequence exactly equals canonical success order;
3. app-health failure after Alembic is accepted as a valid sanitized failure transcript;
4. environment-stage failure after health/Alembic is accepted as valid sanitized failure;
5. read-state/child failure after environment markers is accepted as valid sanitized failure;
6. unknown/duplicate/out-of-order field remains rejected;
7. nonzero provider/write/env/recreate counter remains rejected;
8. empty legacy Bot keys in production `.env` are allowed;
9. present-even-empty Bot key in Compose API/worker env fails;
10. present-even-empty Bot key in actual API/worker container env fails;
11. absent Bot keys in Compose/container env pass;
12. full 40-character release SHA remains asserted;
13. canonical explicit-URL Git bootstrap tests from M4BT1R remain green;
14. no production/provider/write/recreate capability is introduced.

If useful, factor a small pure helper for protocol/env validation. Keep scope narrow.

## Validation

Run:
- all focused Stage C verifier tests;
- Python compile;
- bundled helper compile;
- Bash syntax;
- Ruff;
- `git diff --check`.

Before commit, self-review the complete happy-path emission order against parser order.

## Authorization

AUTHORIZED:
- verifier/test-only corrections described above;
- update `PROJECT_STATE.md`;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- live verifier;
- provider calls;
- DB/env writes;
- service restart/recreate;
- deploy/rollback/ref movement;
- schema/data cleanup;
- MTProto behavior/config changes;
- AI enablement.

## Required report

Return:
- commit SHA;
- files changed;
- canonical final success field order;
- end-to-end `remote_main -> parse_output` proof;
- Bot env absence proof;
- regression/test results;
- compile/Ruff/Bash/diff-check results;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BU1_PROTOCOL_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
