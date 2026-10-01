# Current task — HOLD

AH2-T planned Task execution interval write parity is implemented. Rollout and model verification are pending.

- Implementation: `aa3f475a3a0ee49b938364e6d53f3657711b1a9b`
- `create_task` and `update_task` write `planned_start_at` and `planned_end_at` as one pair. End must be after start. Omission leaves an existing interval unchanged. Both null on update clears it. The same pair is a no-op.
- Assistant and MCP use those field names. A malformed pair fails before approval and before a Task is created. `PATCH /tasks/{id}` uses the same pair rules.
- The interval is not a deadline, a reminder, or calendar busy time.
- Tests: 45 passed. The static contract gap is closed. Model behavior stays unverified until AH2-M.
- No Alembic migration. Production was not deployed and remains `0719e9bf5af75a8065a9916d8e27c0247a3921ec`, Alembic `0052 / 0052`.

Do not start AH2-E, AH2-M, or AH2-C.
