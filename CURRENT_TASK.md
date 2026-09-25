# Current task

HOLD

Flow Media F1 provider-neutral media child Objects is implemented at `59f47a51f48cd08e4aaddcffb0dd60a455ea11b0`.

A communication parent can materialize deterministic file children and one contains edge from bounded Telegram, Mattermost, and Teams descriptors. Replay stays idempotent. No bytes are downloaded and no transcription runs.

Focused checks: `tests/test_communication_media.py` 6 passed. Combined media, email-attachment, Mattermost, Teams, unified communications, Telegram AI policy, and Graph Refined run: 280 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

`tests/test_teams_a.py::test_migration_0040_revises_0039` still expects Alembic head `0046` while the repository head is `0049`. `tests/test_inbox_source_chronology.py::test_inbox_api_order_hides_attachments_and_keeps_contract` still fails because the inbox payload includes `conversation_groups`. Both predate this task.

No migration. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`.

Do not begin transcription F2, Task Refinement, or deploy.
