# Current task

HOLD. Graph Refined P3R salience attribution and noise-starvation safety is implemented at `52928587b8ff4f5586b216e8ffb989cc28a50c3d`.

Email direction comes from canonical metadata. Gmail `SENT` is outbound and `INBOX` or `UNREAD` is inbound. Yandex inbox folders are inbound and sent folders are outbound. Ambiguous or unknown direction produces no direction-sensitive hit. An inbound message attributes only the sender. An outbound message attributes known recipients. A known person on the recipient list of an inbound message is not an outbound interaction. More than one To/Cc address is group exposure, not 1:1.

The communication scan reads at most 200 messages inside the 90-day window. Each Person keeps at most 8 direct hits and 8 public hits. Newer unrelated messages do not drop a direct reciprocal contact that is still inside the scan. Ranking is the top of the People who have exact interaction, P2 attention, or a task/calendar link. It is not the oldest created People.

Teams attributes an inbound human sender only. An application sender and an outbound Teams message do not invent reciprocity. Mattermost attributes an exact author, with a DM weighted as direct and other channels as public. Telegram private and group behavior is unchanged. `claims_object_importance` remains false. No migration.

`tests/test_person_salience.py`: 7 passed. `tests/test_person_evidence_ledger.py`: 6 passed. `tests/test_person_identity.py`: 12 passed. Combined focused run: 25 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No P4, UI, proactive, Assistant, or Task Graph integration, and no live provider/LLM call. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`. `origin/production` was not moved.

Do not choose or start the next phase.
