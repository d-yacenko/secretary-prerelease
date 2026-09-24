# Current task — HOLD

No implementation task is authorized.

The narrow corrective pass for the pre-next-feature fix round is complete.

Corrective implementation SHA: `a2a2e85ed5255cdf9fcf57fad15b222d89e946f6`

Parent review baseline: `82b27f9f93af489d086344fc443337d23aecd6a0`

Production was not changed. Production runtime/ref remains `36c2ce9f43e56a9554688f50c60a79d56e469fbe`. Alembic remains `0046 / 0046`. No live provider calls were made.

## Results

- Temporal early `already_evidenced` again returns `hint_id` for a temporal hint and `calendar_id` for a calendar event. Extractor and match-judge calls stay at zero on an exact active revision. `temporal_signal_result.chosen_hint_id` / `chosen_calendar_id` stay populated.
- Inbox list cards opt into wrapping. The shared `ObjectMetaActionRow` wide layout is the previous row with right-aligned labels, so Search and Today keep that alignment.
- Reference `provider` and `primary_at` are taken from the same `get_object` snapshot. A second `SessionLocal()` query is not used. A long chip title at phone width ellipsizes and keeps the kind icon, provider icon, and date.
- At `73457fec226e113f7f8ddf8768497cafa8e003f1` the Telegram parameter already failed enqueue with zero jobs. The suite now expects that quarantined Telegram does not enqueue, and Mattermost plus Teams cover the common dedup path. Telegram AI was not enabled.

## Checks

- Focused temporal tests, including same-revision audit ids, calendar anchor, stale/unchanged revision, quarantine, and Mattermost/Teams dedup: PASS (9 in the last focused selection, plus the earlier stale/unchanged trio inside the broader run before the audit-query fix; the final selection is green).
- Assistant reference provenance tests: PASS.
- Flutter Inbox swipe/desktop trash, narrow desktop containment, shared-row alignment, reference chips including the long title, and voice failure cue: PASS.
- `py_compile` and Ruff check on changed Python modules: PASS.
- Ruff format check: PASS for `object_primary_date.py`, `assistant_service.py`, and `test_assistant_reference_provenance.py`. `test_temporal_signals_a.py` and `temporal_signals_service.py` still have pre-existing format failures and were not wholesale-formatted.
- Flutter analyze of touched Dart files: no new errors. Pre-existing `unnecessary_null_comparison` in `assistant_screen.dart` and `use_build_context_synchronously` infos in `inbox_screen.dart` remain.
- `git diff --check`: PASS.
- No Alembic migration.

## Remaining

The next large feature is not authorized. This corrective pass is not deployed.
