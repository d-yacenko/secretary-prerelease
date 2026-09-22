# Current task — Telegram Bot API M4BR1R: fix historical-read existential check

## Status

M4BR1 verifier commit:
`ababcfacf6526fcd71ccaa752278dfe268be9a1e`

Architect review: read-only/safety boundary accepted, but NOT YET ACCEPTED FOR LIVE RUN.

Current production runtime/ref:
`bd1433921a056b8dc42bd23c6ecf0e4ce2bedf4b`

Alembic:
`0046`

## Problem

The verifier currently does:

- select an arbitrary legacy Bot-derived Telegram object with `.limit(1)`;
- call `RecentSourceService(...).get_inbox_eligible(sample.id)`;
- fail if that one arbitrary row is not Inbox-eligible.

This is not equivalent to the requirement.

Historical Bot data can legitimately include outbound, hidden, deleted, rejected, or otherwise non-Inbox rows. If one of those happens to be returned first, the verifier produces a false negative even when other preserved legacy Bot messages are correctly readable.

## Goal

Change the read-only child check from "arbitrary sample is readable" to:

> at least one preserved legacy Bot-derived object is eligible through the canonical generic Inbox read predicate.

No product/runtime behavior change.

## Required correction

Preferred implementation:

1. Keep the aggregate `LEGACY_BOT_OBJECT_COUNT` over legacy non-MTProto Telegram chat objects.
2. Build the Inbox-eligible existence check using the canonical `RecentSourceService` predicate/service semantics, not a hand-maintained approximation.
3. Do not print or return any object ID/content/title.
4. Emit only:
   `LEGACY_BOT_INBOX_READABLE=true|false`.

Acceptable approaches:
- add a small read-only service method such as an existence/count helper only if it is generic and genuinely useful; OR
- in the verifier child, inspect a bounded set of legacy candidate rows and call `get_inbox_eligible()` until one is eligible, without outputting identifiers.

If using bounded candidate iteration:
- choose a deterministic bounded limit large enough for existing historical Bot data;
- report a sanitized failure if legacy count is larger than the checked bound and no readable candidate was established, rather than falsely claiming unreadable;
- no writes/flush/commit.

Do not duplicate the full Inbox eligibility SQL manually in the verifier.

## Regression requirements

Add tests proving:
1. first legacy candidate non-eligible + later candidate eligible => `LEGACY_BOT_INBOX_READABLE=true`;
2. no eligible candidate => false/failure;
3. no IDs/content are emitted;
4. provider/write/recreate counters remain zero;
5. all prior strict protocol/read-only tests still pass.

## Preserve

Do not change:
- production release expectation;
- route/config/container checks;
- MTProto account count = 1;
- active scope = 28;
- AI=false;
- bounded health retry;
- Alembic 0046;
- strict parser;
- zero provider/write/env/recreate capabilities.

## Validation

Run:
- focused verifier tests;
- Python compile;
- bundled helper compile;
- Bash syntax;
- Ruff;
- `git diff --check`.

## Authorization

AUTHORIZED:
- local verifier/test correction only;
- update `PROJECT_STATE.md`;
- commit/push canonical `main`.

NOT AUTHORIZED:
- production SSH;
- live verifier;
- provider calls;
- DB/env writes;
- service restart/recreate;
- deploy/ref movement;
- schema/data cleanup;
- MTProto changes.

## Required report

Return:
- corrective commit SHA;
- exact existential historical-read mechanism;
- regression results;
- compile/Ruff/Bash/diff-check results;
- production SSH=0;
- provider calls=0;
- production mutation=0.

Final marker:

`TELEGRAM_BOT_M4BR1R_VERIFIER_READY`

Then STOP.

`CURRENT_TASK.md` is the source of active authorization.
