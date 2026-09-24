# Current task — Graph Refined P1: canonical Person + provider identities foundation

Authorized scope: begin the selected major stage **Graph Refined: People & Identity**.

This is foundation only. Do not implement fuzzy matching, automatic merge suggestions, Assistant person lookup, send-by-person, Graph UI redesign, voice/media ingestion, or Task Graph refinement in this task.

Production must not be deployed or mutated in this task.

## Product goal

Introduce a canonical per-user real-world Person identity layer that uses the existing graph rather than a separate contact silo.

A Person is an existing graph Object with:
- `kind = "person"`;
- user-owned canonical display title;
- normal Object provenance/state rules.

Provider/account identities are typed records attached to a Person. They represent exact strong identifiers from communication sources and survive independently of source-message presentation.

Examples:
- email address;
- Mattermost remote user id and/or username in a specific server realm;
- Teams sender/user id in a specific tenant realm;
- Telegram MTProto sender/user peer id in an account/provider realm.

Do not infer that two people are the same merely from display-name similarity.

## 1. Add typed PersonIdentity persistence

Add the smallest additive schema needed after production Alembic `0047`.

Prefer a dedicated table such as `person_identities` with fields sufficient for:
- id;
- user_id;
- person_object_id -> objects.id;
- identity_type;
- provider;
- realm/account discriminator where needed;
- canonical normalized value;
- optional bounded display value / metadata;
- provenance/state/confidence;
- timestamps.

Hard invariants:
- referenced Object belongs to the same user and is `kind="person"`;
- one exact strong normalized identity cannot be actively attached to two different People for the same user/provider/type/realm;
- cross-user isolation is strict;
- rows must not contain provider secrets/tokens/session material;
- deleting/rejecting a source message must not destroy the Person identity record by cascade.

Use normal additive Alembic practice; do not alter historical migrations.

## 2. Deterministic normalization

Implement a focused normalization/service module with explicit supported identity kinds.

At minimum support:
- email: case-insensitive canonical address;
- Mattermost: exact server realm + remote user id when present; username may be stored as a separate exact alias identity scoped to that server;
- Teams: tenant + sender/user id;
- Telegram MTProto: exact provider/account realm + numeric sender/user peer id.

Normalization must be deterministic and bounded. Invalid/malformed values fail closed.

Display names are semantic attributes/aliases only and are NOT strong merge keys.

Do not call an LLM/embedding model for identity normalization.

## 3. Person service API/domain layer

Add a small domain service that can:
- create a Person Object safely;
- attach an exact provider identity to that Person;
- resolve an exact identity to zero or one Person;
- list a Person's identities;
- detach/reassign only through an explicit safe service path suitable for future user confirmation/reversal.

For this first task, a private/domain service with focused API tests is enough; no Flutter UI is required.

Do not silently merge two Person Objects when an identity conflicts. Return a deterministic conflict.

## 4. Provider evidence extractors — read-only only

Add small pure extractors that can derive strong identity candidates from already normalized communication Object metadata, without mutating existing source Objects.

Cover the metadata shapes already present in the repository:
- email sender/from/reply envelope where a canonical email exists;
- Mattermost `author_user_id`, `author_username`, `author_display_name`, server realm;
- Teams `sender_id`, `sender_display_name`, tenant id;
- Telegram MTProto `sender_peer_id` and account/provider realm.

These extractors produce evidence only. They must NOT auto-create or auto-merge People in this task.

Telegram note:
- keep the existing production AI gate untouched;
- this identity extraction is deterministic non-AI metadata handling and may be implemented provider-neutrally;
- do not hardcode or special-case the chat name `TestML`.

## 5. Focused proof

Add focused tests proving at minimum:
- Person creation uses `kind="person"` and user ownership;
- email normalization/case-folding;
- Mattermost server-scoped identity uniqueness;
- Teams tenant-scoped identity uniqueness;
- Telegram account/realm-scoped identity uniqueness;
- same exact identity cannot belong to two People of one user;
- the same external identifier may exist independently for two different Secretary users;
- display-name equality alone does not resolve/merge People;
- malformed identifiers fail closed;
- provider metadata extractors return exact strong identifiers without mutating source Objects;
- no Telegram AI flag/provider/LLM call participates in this layer;
- migration up/down works from `0047`.

Run the smallest relevant backend tests, migration tests, Ruff/compile for touched Python, and `git diff --check`.

## Completion

When complete:
- record implementation SHA and exact checks/results in `PROJECT_STATE.md`;
- return `CURRENT_TASK.md` to HOLD;
- STOP.
- Do not choose P2 yourself.
- Do not deploy.
