# Current task — HOLD

No implementation task is authorized.

Exact-object reply parity and semantic object visibility are complete.

Implementation SHA: `036e34db44024ffd1fa536409bbc1a75a1ffb98f`

Files changed:
- `backend/app/services/email_reply.py`
- `backend/app/services/email_external_action_service.py`
- `backend/app/tools/schemas.py`
- `backend/app/tools/assistant_contracts.py`
- `backend/app/assistant/tool_output.py`
- `backend/app/assistant/tool_runner.py`
- `backend/app/llm/openai_assistant_provider.py`
- `backend/app/connectors/google/gmail_sync.py`
- `backend/app/connectors/google/gmail_transport.py`
- `backend/app/connectors/yandex/mail_sync.py`
- `backend/tests/test_exact_object_email_reply.py`
- `backend/tests/test_google_oauth.py`
- `backend/tests/test_yandex_mail.py`

Tests: `test_exact_object_email_reply.py` passed. Existing Gmail compose tests in `test_safe_external_actions_b.py` passed. Mattermost/Telegram/Teams reply coverage in `test_teams_a_send.py` and `test_unified_communications_a.py` passed. Gmail and Yandex materialization tests confirm `source_account_email`. Ruff and compile of the touched files passed. `git diff --check` was clean.

`test_safe_external_actions_yandex_parity.py::test_yandex_mail_sent_copy_failure_keeps_smtp_success` fails on unmodified `origin/main` as well (`sent_copy_status` is `stored` rather than `unconfirmed`). It was not changed by this work.

No migration was added. No backend schema change. No live provider send.

Production remains `fe81a13c8887da73b743f5f5c9a4f8830aafa943`. Alembic baseline remains `0046 / 0046`. Telegram MTProto AI activation/quarantine is unchanged.
