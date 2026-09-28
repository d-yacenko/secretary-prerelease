# Current task — PP1-R1: production rollout

PP1-D1 is accepted. Execute the live PP1 migration-bearing rollout using the accepted repository deployment contract.

Exact authorized values:
- release: `07bd8bafdb2f53a6a8475fc2d792687fa373a149`
- rollback/base: `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`
- Alembic: `0050 -> 0051`
- accepted harness implementation: `b74a7d06c7401448c49ce5178bd1df428498ef87`

Before mutation, follow `AGENTS.md`, `docs/executor_bootstrap.md`, and `docs/deploy.md`; verify canonical refs, fast-forward ancestry, accepted harness integrity, and production bootstrap. If preflight does not match exactly, STOP without changing production.

Promote `production` only by non-force fast-forward from the authorized base to the exact release, then run only `ops/production/migrate_person_promotion_0051.py` with the exact authorized values above. Do not use the schema-neutral deploy harness and do not perform ad-hoc recovery.

Success requires exact release runtime, health PASS, Alembic `0051`, unchanged DB container/volume/`.env`, and recreation only of api/worker. Do not create test data, exercise Person promotion actions, call providers/models, or replace the client.

On failure, follow only the accepted harness rollback/break-glass result and STOP.

After completion, record exact rollout facts in `PROJECT_STATE.md`, return this file to HOLD, push documentation to `main`, report exact refs/revision/result, and STOP. Do not begin the next product slice.
