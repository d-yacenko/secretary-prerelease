# Current task

HOLD.

People PP1-D1 exact 0050 -> 0051 migration harness is implemented at `b74a7d06c7401448c49ce5178bd1df428498ef87`.

The harness accepts only release `07bd8bafdb2f53a6a8475fc2d792687fa373a149` and rollback `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`, revision pair `0050 -> 0051`, and the single added migration `0051_person_promotion_feedback.py`. Normal `ops/production/deploy.py` remains forbidden for this release.

No live production deployment was performed. Production/runtime and `origin/production` remain `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`, production Alembic `0050`. Repository Alembic head remains `0051`.

Do not deploy. Do not move `production`. Do not start the live migration-bearing rollout, contextual prompts, Person knowledge, or the next People slice.
