# Current task — HOLD

People R4 is implemented at `01f978a6b5a7932bbf4551ede5681cd2083c3813`.

Rooted Person detail reviews source-derived identity candidates separately from known contacts. Discovery reuses `find_identity_candidates` and the existing extractors. Confirmation, rejection, and retraction stay on `POST /graph/people/{person_id}/identity-correction`. No second resolver, migration, auto-attach, merge, provider lookup, enrichment plan, social ontology, proactive change, MCP change, or production deploy.

Production backend/runtime and `origin/production` remain `1b851f91bd37d0e79531ef740b02febb3c3af69d`. Alembic remains `0050`.

Linux debug bundle for later human visual review:

`/tmp/secretary-r4-FjxjHf/secretary-prerelease/client/build/linux/x64/debug/bundle/personal_secretary`

Do not deploy. Do not start durable relationship or context ontology, G3B, S3, MCP, or another People slice.
