# Current task — HOLD

Harness H2A is complete.

Implementation: `108f4e9764caeebbb70367bc53f15c4e979a1e60`.

`create_task` and `update_task` accept optional `completion_mode` `finite` or `ongoing` on Assistant and MCP. Existing lifecycle and `part_of` guards still apply. `link_objects.relation_type` stays unrestricted for H2B. No schema, client, or production change.

Do not start H2B.
Do not start Task stabilization.
Do not deploy production.
