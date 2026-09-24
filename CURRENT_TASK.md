# Current task

HOLD. Graph Refined P1R person-evidence type safety is implemented at `92aef7e6c9fb2e5acd6afc7056b26ea67ea99d07`.

`telegram_user_id` accepts only a strictly positive user id. Zero and negative Telegram sender peers fail closed and produce no Person evidence. MTProto transport and history storage are unchanged.

Newly normalized Teams messages persist `sender_kind` as `user` or `application`. Person evidence emits a Teams user identity only when `sender_kind == "user"`. Application, missing, malformed, and unknown sender kinds produce no Person evidence. Legacy Teams objects without the discriminator are not guessed into People. Teams presentation, send, and reply behavior is unchanged.

Evidence extraction is anchored to the canonical source Object. Gmail and Yandex email objects produce email identities only. Mattermost chat objects produce Mattermost identities only. Teams chat objects produce a Teams user identity only under the sender-kind rule. Telegram MTProto chat objects produce a Telegram user identity only under the positive-user-id rule. An unsupported provider or kind produces no Person evidence. Display names remain attributes, not identity keys.

`tests/test_person_identity.py`: 12 passed, including uniqueness, cross-user isolation, detach/reassign, and `0047 <-> 0048`. `tests/test_communication_temporal_parity_a.py`: 5 passed. Combined focused run: 17 passed. Ruff and compile of touched Python passed. `git diff --check` clean.

No P2 work, fuzzy matching, auto-merge, UI, Assistant lookup, send-by-person, or live provider/LLM call. Migration `0048` was not applied in production. Production remains `296b4735f9473ea60ef22f1827ed94260603128e`, Alembic `0047 / 0047`. `origin/production` was not moved.

Do not choose or start the next phase.
