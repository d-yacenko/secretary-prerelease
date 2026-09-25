# Current task

HOLD

Flow Media F2 is implemented at `452fe86ad55fb6f3df0faf000b340fa5fdbbddd5`.

`CommunicationMediaProcessingService` transcribes an existing voice or audio media child through the shared transcription provider, per-user OpenAI credential, daily budget guard, and `WORKLOAD_TRANSCRIPTION` audit. Telegram MTProto is the only fetch adapter. Bytes are read in memory for the message named by persisted provenance, and only when the parent message is currently AI-eligible. The transcript is one `transcript` Representation on the child. Replay of the same bytes and model does not call the provider again. A changed byte hash replaces that row. Ineligible, deleted, or rejected parents and children finish without download or a model call. Permanent validation mismatches do not retry. Budget exhaustion uses the existing worker park. Mattermost and Teams children stay metadata-only. No migration.

Checks: `tests/test_communication_media_processing.py` 8 passed; `tests/test_communication_media.py` 6 passed; `tests/test_assistant_transcribe.py` 16 passed; `tests/test_telegram_mtproto_self_authored_policy.py` 10 passed; `tests/test_phase_27b_mattermost.py` 30 passed; `tests/test_person_routes.py` 14 passed; `tests/test_person_assistant.py` 36 passed; `tests/test_person_enrichment.py` 20 passed; `tests/test_person_salience.py` 9 passed; `tests/test_person_evidence_ledger.py` 6 passed; `tests/test_person_identity.py` 12 passed; `tests/test_tool_gateway.py` 28 passed. Combined 195 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

`tests/test_phase_28b_transcription.py` still returns 422 for a `.wav` name whose bytes are not a WAV; that failure is present on the F2 task commit before this implementation. The documented Alembic-head, inbox `conversation_groups`, and Assistant `pending_action_plan` / `ai_traces_user_id_fkey` baselines remain outside this task.

Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.

Do not begin Mattermost/Teams media-download adapters, Task Refinement, or deploy.
