# Current task

HOLD.

People PP1-H1 Mattermost self-author exclusion is implemented at `07bd8bafdb2f53a6a8475fc2d792687fa373a149`.

A Mattermost DM is a promotion hit only when stored facts prove a remote author: `channel_type=D`, a same-user `MattermostAccount` for `account_id`, a matching `server_url`, and `author_user_id` different from that account's `remote_user_id`. Anything missing or inconsistent fails closed.

Repository Alembic head remains `0051`. Production/runtime remains `9c9f0b0e72ffa7cf4ba74fcee60f7f05aeb6dffa`, production Alembic `0050`.

Client source did not change. The existing Linux debug bundle remains `/tmp/secretary-pp1-W3J80y/secretary-prerelease/client/build/linux/x64/debug/bundle/personal_secretary`. Human acceptance of PP1 with the corrected backend is still pending.

Do not deploy. Do not start contextual prompts, Person knowledge, or the next People slice.
