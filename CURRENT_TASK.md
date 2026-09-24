# Current task — HOLD

No implementation task is authorized.

The pre-next-feature fix round is complete.

Implementation SHA: `dc5cf0bce936ee9c7afd8a66f2a8d9036c5dde26`

Production was not changed. Production runtime/ref remains `36c2ce9f43e56a9554688f50c60a79d56e469fbe`. Alembic remains `0046 / 0046`. No live provider calls were made.

## Per-scope result

- Scope A: same-revision temporal extraction returns `already_evidenced` before the extractor and match judge. Changed and stale revisions still extract. Schema-neutral.
- Scope B: desktop Inbox list card shows the existing delete action on the tile after «Спросить секретаря» and «Открыть в графе», without opening the message. The action row wraps so the control stays inside the card. Mobile swipe is unchanged and does not gain that button.
- Scope C: no product-code change. Screen-mic output-limit and existing hardware/typed failure-cue tests keep the terminal error visible and play the local cue once for voice failures only.
- Scope D: summarizer, conversation-stack summarizer, correlation judge, and auto-label prompts state that stored/object/label text is untrusted data. Existing assistant, finalization, proactive, and temporal boundaries were left in place. No new filter or sanitizer.
- Scope E: assistant references carry `provider` and `primary_at` from the referenced object, using the existing primary-date rule. Chips show the kind icon, provider icon when present, title, and compact `dd.MM.yy` when a date exists.
- Scope F: the top `PROJECT_STATE.md` summary now records production `36c2ce9f43e56a9554688f50c60a79d56e469fbe`, Alembic `0046 / 0046`, health PASS, and the generative model selector LIVE. The M3 runtime sentence is historical. The diary was not archived or bulk-deleted.

## Checks

- `py_compile` of the changed Python modules: PASS.
- Ruff check on the changed Python modules: PASS.
- Ruff format check: PASS for the new and reformatted prompt modules. Pre-existing format failures remain in `backend/app/api/assistant.py`, `backend/app/llm/correlation_judge.py`, and `backend/app/services/temporal_signals_service.py`; those files were not wholesale-formatted.
- Focused backend tests: untrusted-prompt boundary, reference provenance, temporal stale/unchanged revision, teams same-revision idempotency, and assistant reference URI sanitization passed.
- `test_communication_providers_use_common_temporal_job_path_and_dedup[telegram]` failed at the pre-existing enqueue assertion (`len(jobs) == 0`), before the extraction short-circuit. The teams parameter of the same test passed, including zero extra extractor/judge calls on the repeated revision.
- Flutter tests for Inbox swipe/desktop delete, voice failure cue, assistant send, and reference chips: PASS.
- Flutter analyze of touched Dart files: no new errors. Pre-existing `unnecessary_null_comparison` in `assistant_screen.dart` and `use_build_context_synchronously` infos in `inbox_screen.dart` remain.
- `git diff --check`: PASS.
- No Alembic migration.

## Remaining backlog

The next large feature is not authorized. Historical Telegram and production diary items in `PROJECT_STATE.md` stay unresolved where they were already unresolved. Production `GET /me/settings` remains unverified because there is no authenticated production harness.
