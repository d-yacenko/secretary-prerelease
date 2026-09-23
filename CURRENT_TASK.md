# Current task — Await explicit deploy authorization for bidirectional communication feed parity

## Architect acceptance

Commit:

`d22c6cf78945c8f92934a46431b2bcc1887fd8c8`

is ACCEPTED / DEPLOY-READY / NOT DEPLOYED.

Production currently remains:

`681c0e04df5881124ab8d72a4c05e5a2c7977296`

Alembic remains:

`0046`

Production `TELEGRAM_MTPROTO_AI_ENABLED=false`.

## Accepted production evidence

A narrowly scoped BREAK-GLASS READ-ONLY inspection of a recent post-deploy self-authored canonical MTProto object completed with exit 0 and no mutation.

Accepted evidence:
- production release exact: PASS;
- global Telegram AI false: PASS;
- recent self-authored object found: PASS;
- self-authored policy: PASS;
- AI eligible: PASS;
- embedding present: PASS;
- embed job present/done: PASS;
- downstream jobs included auto-label, correlation, temporal extraction;
- downstream failed jobs: 0;
- AI trace success count: 4;
- AI trace failed count: 0;
- correlation evidence: PASS;
- AI-only object visibility: PASS;
- context visibility: PASS;
- Inbox/feed visibility on deployed release: FAIL;
- outbound feed suppression cause: CONFIRMED.

The temporal extraction job ran successfully but the verifier found no temporal evidence edge for the selected newest self-authored object. This is not a blocker for this parity release. Current TemporalSignalService creates or updates a temporal evidence edge for every accepted exact temporal anchor, so absence of such an edge means that exact selected source did not produce or retain an accepted exact temporal anchor. No temporal job/provider failure was observed.

## Accepted parity change

The accepted code removes only the legacy provider-specific outbound suppression from `RecentSourceService`.

Result:
- Telegram inbound and outbound are eligible for ordinary Inbox/feed visibility subject to existing Telegram ordinary visibility/active-scope policy;
- Teams inbound and outbound are visible;
- conversation member detail preserves both directions in chronological order;
- Mattermost behavior remains unchanged;
- Gmail/Yandex behavior remains unchanged;
- rejected/deleted/Gmail-noise/child-attachment filters remain;
- outbound visibility does not create Inbox attention/unread semantics;
- Telegram AI eligibility is unchanged.

No client-side outbound suppression was found; no Flutter production change is required for this parity fix.

## Accepted false -> true regression

The same-data regression proves in tests:

1. global false:
   - self-authored active-scope outbound is eligible;
   - inbound/foreign Telegram is not;
   - Python/ORM/raw SQL agree;
   - global-false catch-up remains zero.
2. switch to global true in test only, without metadata rewrite:
   - active-scope canonical inbound and outbound are eligible;
   - inactive scope remains blocked;
   - Python/ORM/raw SQL agree;
   - context/retrieval see both directions;
   - catch-up enqueues only missing eligible work and the next pass is zero.
3. switch back to false:
   - self-authored outbound remains eligible;
   - inbound/foreign become ineligible again;
   - object metadata is unchanged.

Therefore the false-mode self-authored exception is isolated to the false branch and does not distort the existing future global-true active-scope policy.

This is regression evidence only. Production global true has NOT been executed or authorized.

## Verification

Reported on exact accepted commit:
- focused policy/full-pipeline/bidirectional-feed/Teams/conversation suite: 74 passed;
- `py_compile`: passed;
- Ruff check: passed;
- Ruff format --check on changed/new focused files: passed;
- `git diff --check`: clean.

## Authorization state

NO deploy is currently authorized.

Do not:
- move production ref;
- deploy/restart/recreate;
- change production env;
- set Telegram AI true;
- run Telegram sync manually;
- manually enqueue jobs;
- run provider diagnostics;
- run the old E2E harness;
- perform production DB writes;
- process Telegram backlog.

STOP and wait for explicit human authorization to deploy exact commit `d22c6cf78945c8f92934a46431b2bcc1887fd8c8`.

Any future operational switch of `TELEGRAM_MTPROTO_AI_ENABLED=true` is a separate authorization and rollout decision.
