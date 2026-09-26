# Current task — HOLD

Harness H2A-R is complete.

Implementation: `3db8a71efb876ed5a7ac4c47a9749bdb8d2e6148`.

MCP `create_task` and `update_task` `completion_mode` is optional and non-nullable. Omission is allowed. Explicit JSON `null` is rejected. `get_task_profile` MCP-list mismatch remains unfixed.

Do not start H2B.
Do not start Task stabilization.
Do not deploy production.
