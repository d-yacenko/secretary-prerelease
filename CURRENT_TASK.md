# Current task — HOLD

People PP1 implementation is `d9437f6b8ece61e01865ae630dc0e9f196e87cc8`.

People overview can suggest up to 5 exact direct-contact promotion candidates from the existing 90-day / 400-row scan. Approval creates one Person, binds that exact identity, and records `user_confirmed`. Suppression is reversible and exact-identity scoped. Candidate reads do not create a Person.

Repository Alembic head is `0051` (`person_promotion_feedback`). Production/runtime and `origin/production` remain `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`. Production Alembic remains `0050`.

Linux debug bundle for later human review: `/tmp/secretary-pp1-W3J80y/secretary-prerelease/client/build/linux/x64/debug/bundle/personal_secretary`. Human acceptance is pending.

Do not deploy. Do not start contextual task prompts or Person knowledge.
