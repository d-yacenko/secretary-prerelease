# Current task — Graph Refined P1R: person-evidence type safety

Architect review of P1 implementation `3c773db48b8bc0f27a0f6896f94295bfbc5781b1` found two blocking type-safety defects in provider evidence. Fix only these defects plus the smallest provider-dispatch hardening needed to make the evidence layer safe.

Do not start P2. Do not add fuzzy matching, auto-merge, UI, Assistant lookup, send-by-person, voice/media, or Task Graph work. Do not deploy or apply migration `0048` in production.

## Defect 1 — Telegram non-user peers can become Person identities

Canonical MTProto history stores `sender_peer_id` from Telethon peer IDs. The transport explicitly allows positive or negative peer IDs:
- positive sender peer => Telegram user;
- negative sender peer may represent chat/channel identity.

Current `normalize_telegram_user_id()` accepts negative values, so a non-person chat/channel sender can be attached to a canonical Person.

Required correction:
- `telegram_user_id` Person identities must accept only strictly positive non-zero Telegram user IDs;
- zero and every negative value must fail closed;
- evidence extraction must not emit a Person identity for a negative/non-user sender peer;
- do not change MTProto transport/history storage semantics merely to satisfy this layer.

## Defect 2 — Teams application senders can become Person identities

`teams.normalize.sender_from_message()` supports both `from.user` and `from.application`, but normalized message metadata currently persists only `sender_id` / `sender_display_name`. The Person evidence extractor therefore cannot distinguish a human Teams user from an application/bot and currently treats either as `teams_user_id`.

Required correction:
- preserve a bounded deterministic sender discriminator in newly normalized Teams message metadata, e.g. `sender_kind = "user" | "application"`;
- Person evidence may emit a Teams user identity only when the normalized evidence proves `sender_kind == "user"`;
- `sender_kind == "application"`, missing, malformed, or unknown must fail closed for Person extraction;
- legacy Teams objects without the discriminator must NOT be guessed into People;
- keep normal Teams message presentation/send/reply behavior unchanged.

## Provider-dispatch hardening

Current generic evidence extraction receives only an arbitrary metadata mapping and runs email, Mattermost, Teams, and Telegram extractors over it in parallel. Before P2 this must be source/provider anchored so coincidental metadata keys cannot manufacture cross-provider Person identities.

Use the smallest clean API, for example:
- accept the canonical source Object, or
- require explicit trusted `provider` / `kind` / transport context alongside metadata.

Required semantics:
- Gmail/Yandex email source objects may produce email identities only;
- Mattermost chat objects may produce Mattermost identities only;
- Teams chat objects may produce Teams user identity only under the sender-kind rule above;
- canonical Telegram MTProto chat objects may produce Telegram user identity only under the positive-user-id rule above;
- unsupported provider/kind/transport produces no Person identity evidence;
- display names remain attributes only, never exact identity keys.

Do not trust a provider value copied from arbitrary metadata when the canonical Object already has a provider field.

## Focused proof

Extend focused tests proving at minimum:
1. Telegram positive user sender emits evidence.
2. Telegram zero/negative sender does not normalize as a user and emits no Person evidence.
3. Teams `from.user` normalization persists `sender_kind=user` and emits Person evidence.
4. Teams `from.application` persists `sender_kind=application` and emits no Person evidence.
5. Legacy/missing/unknown Teams sender kind emits no Person evidence.
6. A canonical object for one provider containing coincidental keys from another provider does not emit cross-provider identities.
7. Email/Mattermost exact evidence still works.
8. Existing P1 exact uniqueness, cross-user isolation, detach/reassign, and `0047 <-> 0048` migration tests remain green.

Run the smallest relevant backend tests including the touched Teams normalization tests, Ruff/compile for touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P2 and do not deploy.
