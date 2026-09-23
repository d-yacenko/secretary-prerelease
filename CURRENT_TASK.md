# Current task — Verify live normal Telegram pipeline and restore bidirectional communication parity

## Human report / authorization

Production release:

`681c0e04df5881124ab8d72a4c05e5a2c7977296`

is deployed successfully with Alembic `0046`.

The human has now sent one brand-new ordinary self-authored Telegram message in an already active-scope solo group.

Human UI observations:
- the new message is not visible in the Inbox/feed;
- downstream temporal/task evidence appeared;
- Telegram/message evidence is visible in graph surfaces.

The human asks Architect to verify the real normal backend pipeline and then make communication presentation semantics provider-neutral: conversation/feed detail must include both own/outbound and other/inbound messages.

The human also asks to verify now that the new false-mode self-authored exception will not distort the future `TELEGRAM_MTPROTO_AI_ENABLED=false -> true` transition.

Do not record or print Telegram group names, message bodies, account IDs, peer IDs, Telegram user IDs, or provider credentials.

## Architect code findings

The missing feed item has a concrete code explanation:

`RecentSourceService._not_outbound_chat_clause()` currently suppresses `direction=outbound` for providers `telegram` and `teams`.

This filter is part of presentation/feed eligibility, not the AI pipeline.

No corresponding outbound filter was found in the Flutter Inbox grouping/merge/screen layer.

The current AI policy has a separate true-mode branch:
- while false: Telegram is closed except proven self-authored canonical active-scope outbound;
- while true: `telegram_mtproto_scope_object_predicate()` is used, so canonical active-scope inbound and outbound are eligible independent of the false-mode self-authorship exception.

Existing tests already cover:
- true-mode active-scope inbound + outbound eligibility;
- inactive scope remaining blocked;
- false-mode catch-up = zero;
- false -> true catch-up processes eligible active-scope objects and does not duplicate the immediate catch-up pass.

This task must strengthen that regression rather than changing the true-mode policy.

---

# Part A — BREAK-GLASS READ-ONLY production verification

This is a narrowly authorized read-only production inspection.

It does NOT authorize mutation, repair, retrying the old E2E harness, manual sync, manual enqueue, provider actions, or changing the AI flag.

### Preconditions

Require:
- canonical target and pinned SSH host key from committed `ops/production/target.json`;
- public-key-only SSH;
- production checkout HEAD exact `681c0e04df5881124ab8d72a4c05e5a2c7977296`;
- authoritative `origin/production` exact same SHA;
- clean production tracked worktree;
- production `TELEGRAM_MTPROTO_AI_ENABLED=false`.

If any precondition fails: emit one sanitized blocker and STOP production inspection.

### Authorized remote mechanism

For this read-only diagnostic only, direct pinned SSH is explicitly authorized as BREAK-GLASS READ-ONLY.

Inside the already-running API container, execute only an stdin-fed `python3 -B -` diagnostic through the canonical Compose files/env.

The diagnostic MUST begin a PostgreSQL transaction and execute:

`SET TRANSACTION READ ONLY`

before application queries.

No commit.
Rollback/close on exit.

No production file writes.
No source checkout writes.
No environment changes.
No service restart/recreate.
No Telegram transport/session decrypt.
No provider/LLM calls.

### Candidate selection

Do not use or print private message text/group title.

Select recent canonical Telegram MTProto objects created/materialized after deployment, and identify the newest object satisfying the deployed self-authored policy:
- provider telegram;
- kind chat_message;
- transport mtproto;
- owned account;
- active scope;
- direction outbound;
- non-empty sender_peer_id == account.telegram_user_id.

Use a bounded recent window and report only sanitized counts/booleans. Never print object/account/peer/message IDs, body, title, usernames, or timestamps precise enough to identify private content.

### Required read-only evidence

For the newest matching object, report only safe markers such as:

- `PRODUCTION_RELEASE=PASS`
- `GLOBAL_TELEGRAM_AI_FALSE=PASS`
- `RECENT_SELF_AUTHORED_FOUND=PASS`
- `SELF_AUTHORED_POLICY=PASS`
- `AI_ELIGIBLE=PASS`
- `EMBEDDING_PRESENT=PASS|FAIL`
- `EMBED_JOB_PRESENT=PASS|FAIL`
- `EMBED_JOB_DONE=PASS|FAIL`
- `DOWNSTREAM_JOB_TYPES_PRESENT=<safe comma-separated job type names only>`
- `DOWNSTREAM_FAILED_JOBS=<count>`
- `AI_TRACE_SUCCESS_COUNT=<count>`
- `AI_TRACE_FAILED_COUNT=<count>`
- `TEMPORAL_EVIDENCE_PRESENT=PASS|FAIL`
- `CORRELATION_EVIDENCE_PRESENT=PASS|FAIL`
- `AI_ONLY_OBJECT_VISIBLE=PASS|FAIL`
- `CONTEXT_VISIBLE=PASS|FAIL`
- `INBOX_FEED_VISIBLE=PASS|FAIL`
- `OUTBOUND_FEED_SUPPRESSION_CONFIRMED=PASS|FAIL`

Do not print `Job.last_error`, trace payloads, raw model/provider errors, message content, IDs, labels, task names, temporal text, or edge endpoints.

If a downstream feature is disabled by user settings or legitimately produces zero artifacts, report that as a sanitized state, not a fabricated failure.

The goal is to distinguish:
- actual pipeline processing;
- feature-disabled/no-op;
- pending/running;
- failed;
without exposing content.

After Part A, disconnect and perform no further production actions.

---

# Part B — Provider-neutral bidirectional conversation/feed presentation

Code/test-only after the read-only inspection.

## Required semantic change

Conversation/feed presentation must show communication history bidirectionally.

For chat/message providers, own/outbound messages and other/inbound messages are both part of conversation detail/history.

At minimum:
- Telegram: inbound + outbound visible;
- Teams: inbound + outbound visible;
- Mattermost: preserve existing visible behavior;
- Gmail/Yandex mail behavior must not regress.

Remove the provider-specific outbound suppression from the Inbox/feed path.

The current `RecentSourceService._not_outbound_chat_clause()` must no longer exclude Telegram/Teams outbound chat messages from normal feed eligibility.

Do not weaken:
- rejected/deleted filtering;
- Gmail feed eligibility;
- attachment filtering;
- Telegram ordinary visibility / active-scope policy.

Do not change Telegram AI eligibility in this parity change.

## Conversation stack/detail parity

Ensure bidirectional members survive:
- Inbox feed selection;
- conversation projection;
- grouping/stack construction;
- conversation member reconstruction/detail.

A Telegram or Teams conversation containing both inbound and outbound messages must present both in chronological detail.

Do not add direction-based client-side filtering.

## Attention/unread separation

Feed visibility is NOT attention semantics.

Do not make outbound messages create unread/attention merely because they are now visible in conversation history.

Preserve existing notification/attention behavior.

Add tests proving that bidirectional feed visibility does not create new outbound attention semantics.

---

# Part C — Strengthen false -> true Telegram regression

Code/test-only. Do NOT toggle production.

Add an explicit same-data transition regression around the final deployed policy:

1. Start with global false.
2. Create active-scope canonical Telegram:
   - self-authored outbound;
   - inbound from another sender;
   - optionally a second outbound/foreign negative.
3. Under false:
   - self-authored outbound is eligible;
   - inbound/foreign is not;
   - Python/ORM/raw-SQL agree;
   - normal newly-materialized self-authored path may enqueue;
   - recurring catch-up remains zero.
4. Toggle setting to true in the test only, without rewriting object metadata.
5. Under true:
   - both active-scope inbound and outbound canonical MTProto are eligible;
   - inactive-scope remains false;
   - Python/ORM/raw-SQL agree;
   - context/retrieval surfaces can see both directions;
   - catch-up enqueues only still-missing eligible work and remains idempotent on the next pass.
6. Toggle back to false in test:
   - self-authored outbound remains eligible;
   - inbound becomes hidden again;
   - no metadata corruption or policy state is persisted by the toggle itself.

This must prove that the false-mode self-authored exception is only a false-mode branch and does not distort future true-mode behavior.

Do not change the intended global-true policy unless a genuine regression is discovered and reported to Architect.

---

# Required tests/checks

Add/update focused tests for:
- RecentSourceService outbound Telegram visible;
- RecentSourceService outbound Teams visible;
- inbound Telegram/Teams still visible;
- Mattermost regression;
- bidirectional conversation stack/detail membership and order;
- no outbound attention regression;
- Telegram false -> true -> false policy transition;
- Python/ORM/raw-SQL parity across the transition;
- catch-up false=0, true bounded/idempotent;
- current self-authored false-mode policy regressions.

Run at least:
- `tests/test_telegram_mtproto_self_authored_policy.py`;
- `tests/test_telegram_mtproto_full_pipeline.py`;
- relevant RecentSource/Inbox/conversation tests;
- relevant Teams/Mattermost tests;
- relevant client Inbox tests if backend contract changes require fixture updates;
- `py_compile`;
- Ruff check;
- Ruff format --check;
- `git diff --check`.

If Flutter/client files are changed, run relevant `flutter test` / analyzer checks required by repository conventions.

## Hard stop / production boundary

No deploy.
No production ref movement.
No production env change.
Do not set production Telegram AI true.
No manual Telegram sync.
No manual job enqueue.
No historical catch-up.
No old E2E harness.
No provider/LLM call.
No Telegram transport/session decrypt.
No production DB write.
No service restart/recreate.

The only production action authorized is Part A's narrowly scoped read-only transaction.

When complete:
- update `PROJECT_STATE.md` with sanitized factual evidence only;
- commit and push code/test changes;
- report commit SHA, Part A safe markers, and all checks;
- STOP.

Any deployment of parity changes requires a fresh explicit human authorization after Architect review.
