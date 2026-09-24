# Current task — Corrective pass for the pre-next-feature fix round

## Review status

Implementation `82b27f9f93af489d086344fc443337d23aecd6a0` is partially accepted but NOT DEPLOY-READY.

This task is a narrow correction only. Do not reopen the whole fix round.

Production remains:
- runtime/ref: `36c2ce9f43e56a9554688f50c60a79d56e469fbe`
- Alembic: `0046 / 0046`

## Authorization

Code/test/documentation only.

No production mutation. No live paid provider calls. No Telegram provider calls.

## Correction 1 — Preserve Temporal already_evidenced outcome metadata

The new early same-revision short-circuit is correct in avoiding paid/model work, but it currently returns only:

`TemporalSignalJobOutcome(reason="already_evidenced")`

The previous same-revision path returned the chosen anchor identity via:
- `hint_id` when the active anchor is a temporal hint;
- `calendar_id` when the active anchor is a calendar event.

Preserve that existing observable/audit behavior on the new pre-model short-circuit.

Requirements:
- resolve the active same-revision anchor once;
- return `already_evidenced` with the same `hint_id/calendar_id` semantics as the former post-model branch;
- still make zero extractor calls and zero match-judge calls for an exact active same revision;
- keep changed/stale/inactive/superseded behavior unchanged;
- ensure `temporal_signal_result.chosen_hint_id/chosen_calendar_id` remains populated exactly as before on repeated active evidence.

Add focused tests for both the zero-call property and preserved anchor/audit ID.

## Correction 2 — Narrow Inbox wrapping to Inbox; restore shared wide layout semantics

The desktop list-card trash itself is accepted.

However, `ObjectMetaActionRow` is a shared component also used outside Inbox (including Search and Today). The implementation changed its wide layout globally from the prior Row/right-aligned-label behavior to Wrap.

Do not change Search/Today/global layout merely to fit the Inbox trash.

Requirements:
- restore the default/shared `ObjectMetaActionRow` wide behavior to the pre-round semantics;
- keep mobile behavior unchanged;
- make Inbox opt into wrapping locally, either with an Inbox-specific wrapper or a clearly named optional parameter whose default preserves the old shared behavior;
- desktop Inbox must still show bookmark (when applicable), Ask Secretary, Open in Graph, then Trash;
- action row may wrap inside the Inbox card at narrow desktop widths;
- trash must remain inside the card and clickable;
- Search and Today must retain their prior wide label/action alignment.

Run/add focused widget coverage for:
- Linux/macOS/Windows Inbox trash order and containment;
- Android/iOS swipe and no desktop trash;
- narrow desktop width with no overflow;
- at least the relevant Search/Today/shared-row regression proving default wide semantics were not changed.

Do not redesign the shared visual system.

## Correction 3 — Reference provenance from the same exact object snapshot

Assistant reference chips should continue to expose:
- exact object ID;
- title;
- kind;
- canonical URI;
- provider;
- canonical primary date.

Do not open a separate `SessionLocal()` / second object query solely to obtain provider/date for references.

The `get_object` result used to serialize the reference already contains the object's provider, kind, due/start/occurred/updated timestamps, and metadata.

Requirements:
- derive provider and `primary_at` from the same exact referenced-object snapshot used for the other reference fields;
- reuse/refactor the canonical `object_primary_search_datetime` logic rather than duplicating kind-specific date precedence;
- no additional database session/query is introduced by reference serialization;
- preserve user/object visibility guarantees of the existing exact `get_object` path;
- keep current citation validation/capping and click target unchanged.

Also add a Flutter chip regression for a long title at a phone/narrow width:
- no RenderFlex/overflow exception;
- chip remains compact;
- title may ellipsize if necessary;
- kind/provider icons and date remain present when available.

## Correction 4 — Make the stale Telegram temporal test reflect current quarantine

The existing Telegram parameter currently fails before extraction/enqueue under the current Telegram AI gate. This failure is pre-existing relative to `82b27f9...`, but the relevant suite should not remain red.

First prove/document that the same enqueue failure reproduces at the exact pre-round baseline `73457fec226e113f7f8ddf8768497cafa8e003f1`.

Then update test coverage to match the current architecture without changing product behavior:

- with Telegram MTProto AI quarantine disabled/off as currently configured, a Telegram object that is not AI-eligible must not enqueue a temporal extraction job;
- keep a green communication-provider common-path/dedup test using currently AI-eligible providers (for example Teams and/or Mattermost as appropriate);
- do not enable Telegram AI in production config;
- do not weaken `telegram_mtproto_ai_eligible`;
- do not make Telegram provider calls;
- do not revive retired Bot API behavior merely to satisfy the old parameterization.

The final relevant temporal test selection must be green.

## Keep accepted scopes unchanged

Do not otherwise modify:
- hands-free failure cue/state behavior;
- prompt-injection hardening semantics;
- model selection;
- approval/action-plan permissions;
- production/Google/Telegram transport settings.

## Acceptance checks

Run:
- focused Temporal tests including same-revision outcome/audit ID and stale/changed cases;
- corrected communication-provider/quarantine Temporal tests;
- Assistant reference backend tests;
- focused Inbox/Search/Today/shared-row Flutter tests;
- Assistant reference chip Flutter tests including narrow/long-title case;
- existing voice failure cue tests as a no-regression smoke;
- Python compile checks for changed Python files;
- Ruff check for changed Python files;
- Ruff format check for changed/new Python files, documenting only truly pre-existing baseline failures;
- Flutter analyze for touched files;
- `git diff --check`.

No Alembic migration is expected.

## Not authorized

- production deploy/ref movement;
- production env changes;
- live OpenAI/provider calls;
- Telegram login/sync/provider calls or AI activation;
- Google/OAuth, nginx, DNS/firewall;
- unrelated feature work or broad formatting.

## Completion

Record exact corrective implementation SHA and all focused results in `PROJECT_STATE.md`, return `CURRENT_TASK.md` to HOLD, push, and STOP.
