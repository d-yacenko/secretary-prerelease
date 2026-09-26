# Current task — HOLD

Task Map V8E1R deleted-root test contract is reconciled at `bd2ec37b5ff458f014df3e95cb993c9e31c24960`.

A legacy `status="deleted"` root and a Task deleted through `soft_delete_task` both return 404 from the rooted Graph workspace. A non-deleted `done` root still returns 200. Production workspace code did not change.

Do not start V8E2.
Do not repair relation rows.
Do not deploy production.
