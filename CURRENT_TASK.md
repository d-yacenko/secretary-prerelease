# CURRENT_TASK

ACTIVE

## REL1D-HG2B3 — Telegram MTProto inbound sender identity metadata

REL1D-HG2B2 is ARCHITECT SOURCE-ACCEPTED.

Production/backend/client remain:

`bc69c6fa5c0735db9509d12dd5f77e6285e45901`

Alembic remains:

`0054 / 0054`

Human REL1D acceptance remains paused.

D3 proved a current Telegram MTProto source-contract defect:

- 632 MTProto rows in the 90-day audit;
- 469 inbound rows had a stable `sender_peer_id`;
- those rows had no `sender_display_name`;
- therefore current role-import participant parsing could not emit an inbound Telegram identity.

Source inspection shows why:

- `TelegramMtprotoHistoryEntry` currently carries `sender_peer_id` but no sender display/discriminator;
- `_history_entry_from_message(...)` does not preserve the cached Telethon sender entity's human profile data;
- `_normalize_entry(...)` therefore cannot store human sender metadata.

This task is ONLY the Telegram MTProto inbound sender metadata corrective.

Do not perform production sync/backfill/reconcile.
Do not add Telegram Business support in this task.
Do not deploy/install anything.

## Architectural safety rule

A positive Telegram user id is not enough by itself to prove "human Person":

- Telegram bots also have positive user ids;
- channel/chat senders are not Person identities.

Therefore new inbound strong evidence must require an explicit stored sender discriminator.

Do not infer human-ness from:

- positive id alone;
- peer title;
- username;
- message text;
- chat title;
- account title.

## No N+1 provider lookup rule

Do not add:

- `await message.get_sender()`;
- `client.get_entity(...)`;
- one provider/profile request per message;
- any new provider call solely for role-import identity enrichment.

Use only sender entity/profile information already attached/cached on the Telethon message returned by the existing history/message fetch.

If no cached sender entity is available, fail closed and leave sender display/discriminator absent.

## Required bootstrap

Use only:

`https://github.com/d-yacenko/secretary-prerelease.git`

Read fresh:

- `AGENTS.md`
- `CURRENT_TASK.md`
- `PROJECT_STATE.md`
- `backend/app/connectors/telegram/mtproto_transport.py`
- `backend/app/services/telegram_mtproto_history_service.py`
- `backend/app/connectors/telegram/materialize.py`
- `backend/app/domain/role_import_participants.py`
- `backend/tests/test_telegram_mtproto_a3.py`
- `backend/tests/test_telegram_mtproto_full_pipeline.py`
- `backend/tests/test_rel1d_role_import_participants.py`
- HG2A scan-window tests.

Verify fresh `origin/main:CURRENT_TASK.md` is this ACTIVE task.

Use current `main` as source base.

Do not move `production`.

## Transport/history entry contract

Extend `TelegramMtprotoHistoryEntry` with:

- `sender_display_name: str | None`
- `sender_kind: str | None`

Use only a small closed sender-kind vocabulary:

- `user`
- `bot`
- `channel`
- `chat`

Unknown/unavailable sender entity => `None`.

Do not add schema/migration.

### Cached sender classification

Add a small pure helper around the already-attached Telethon sender entity.

Required behavior:

- `types.User` with `bot=False` => `sender_kind="user"`;
- `types.User` with `bot=True` => `sender_kind="bot"`;
- `types.Channel` => `sender_kind="channel"`;
- `types.Chat` => `sender_kind="chat"`;
- anything else / missing => no kind.

For a real `types.User`, derive display only from provider user-name fields:

- trim/collapse Unicode whitespace;
- first + last when both exist;
- first only when only first exists;
- last only when only last exists;
- no username fallback;
- no phone fallback;
- no transliteration/fuzzy logic.

It is acceptable to use a small dedicated helper or Telethon's cached display utility only if tests prove it does not fall back to username for this contract.

For bot/channel/chat senders, a presentation display may be carried internally if useful for tests, but it must never qualify as a Person participant.

## Existing history fetch

`fetch_history(...)` must populate the extended `TelegramMtprotoHistoryEntry` from each already-returned Telethon message without extra provider calls.

Preserve:

- existing page bounds;
- chronological/cursor behavior;
- media behavior;
- authorization/error mapping.

## Existing single-message fetch / reconcile readiness

`fetch_message(...)` must return the new sender display/kind fields from the same canonical entry conversion.

The reconcile path in `TelegramMtprotoHistoryService.reconcile_recent_messages(...)` must preserve those fields when reconstructing a `TelegramMtprotoHistoryEntry`.

This is required so a later controlled reconcile/refresh can repair legacy rows without a separate parsing path.

Do not run such reconcile in production now.

## Stored MTProto metadata

`_normalize_entry(...)` must store:

- existing `sender_peer_id`;
- new `sender_display_name` when available;
- new `sender_kind` when available.

Keep all existing metadata/provenance unchanged.

Do not synthesize inbound `sender_display_name` from `selection.title`.

That would be unsafe in group/supergroup scope and can confuse bots/other senders.

## Role-import parser contract

Change only the MTProto inbound branch in `participant_identities(...)`.

For inbound MTProto rows, require:

- `transport == "mtproto"`;
- exact account realm;
- `sender_kind == "user"`;
- valid positive `sender_peer_id`;
- non-empty `sender_display_name`.

Then use the existing `normalize_telegram_user_id(...)`.

Inbound rows with:

- missing kind;
- `bot`;
- `channel`;
- `chat`;
- unknown kind;
- missing display;

must fail closed.

Do not interpret legacy missing `sender_kind` as a user.

## Outbound behavior

Keep current outbound-private participant semantics unchanged in this task:

- private peer id + peer title/display remains the existing outbound participant path;
- do not redesign bot handling for outbound private dialogs here.

If a directly affected test reveals an independent unsafe outbound contract, STOP and return HOLD rather than broadening scope.

## Existing-row refresh readiness

No production Telegram sync/reconcile/backfill is authorized.

Prove in tests that reprocessing/fetching the same existing MTProto message under the corrected source contract:

- keeps the same external Object identity;
- updates metadata rather than duplicating the Object;
- adds sender display + `sender_kind=user`;
- makes the inbound row participant-ready;
- bot/channel sender remains non-qualifying.

Do not alter materializer identity/upsert rules.

## Required tests

Add/extend focused tests proving at minimum:

1. cached Telethon human User => `sender_kind=user` + collapsed display;
2. first+last display is preserved;
3. first-only and last-only provider names remain valid provider display;
4. username-only user does not synthesize `sender_display_name`;
5. bot User => `sender_kind=bot` and does not qualify as Person;
6. Channel => `sender_kind=channel`, non-qualifying;
7. Chat => `sender_kind=chat`, non-qualifying;
8. missing cached sender => no display/kind and no extra provider lookup;
9. `fetch_history` carries sender fields with no additional calls;
10. `fetch_message` carries the same fields;
11. reconcile reconstruction preserves the same fields;
12. normalized Object stores sender display/kind;
13. inbound current parser emits identity only for `sender_kind=user`;
14. legacy inbound row with display/id but missing kind remains non-qualifying;
15. bot/channel/chat rows remain non-qualifying even with positive-looking ids/display;
16. exact self Telegram user id filtering still removes the user's own identity;
17. outbound-private parser behavior is unchanged;
18. reprocessing same external message enriches one existing Object, no duplicate;
19. HG2A expanded scan tests remain green;
20. no live/provider/model call occurs outside fake/local test transports.

Run at minimum:

- `backend/tests/test_telegram_mtproto_a3.py`
- directly affected MTProto transport/full-pipeline tests;
- directly affected reconcile tests;
- `backend/tests/test_rel1d_role_import_participants.py`
- `backend/tests/test_rel1d_hg2a_scan_window.py`
- Ruff on touched Python;
- `git diff --check`.

## Explicit non-goals

Do not:

- call live Telegram;
- sync/backfill/reconcile production;
- add per-message sender lookups;
- infer display from username;
- infer display from selection/chat title;
- treat missing sender kind as user;
- add Telegram Business participant parsing;
- change outbound-private semantics;
- change self-identity realm;
- change generic Person promotion;
- change HG1.5 mention fallback;
- change HG2A 10,000 ceiling;
- fix Teams legacy rows;
- fix Mattermost/mail further;
- add schema/migrations;
- change dependencies;
- deploy backend;
- build/install client;
- mutate production product data;
- start another slice.

## Completion protocol

On success:

1. append a compact factual `REL1D-HG2B3` entry to `PROJECT_STATE.md` including:
   - implementation SHA;
   - changed files;
   - exact sender-kind vocabulary;
   - exact cached-provider display derivation;
   - explicit no N+1 sender/profile lookup;
   - inbound parser gate;
   - refresh-readiness behavior;
   - exact focused test totals;
   - Ruff/diff-check result;
   - explicit no sync/reconcile/backfill/deploy/install/migration/provider/model/product-data action.

2. replace `CURRENT_TASK.md` with HOLD stating:
   - HG2B3 implementation SHA;
   - source ready for Architect review;
   - production/backend/client remain `bc69c6fa5c0735db9509d12dd5f77e6285e45901`;
   - Alembic remains `0054 / 0054`;
   - human REL1D acceptance remains paused;
   - no Telegram refresh, rollout, Telegram Business task, or next connector task without fresh Architect authorization.

3. commit + push to `main`.

4. STOP.

On blocker:

- record exact bounded blocker;
- return HOLD;
- do not add provider lookups or unsafe inference merely to obtain a display name;
- STOP.

Every Executor final report must end with exactly one final line:

`REPORT_TIME_MSK=HH:MM`
