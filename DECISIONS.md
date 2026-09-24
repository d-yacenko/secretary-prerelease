# Prerelease architectural baseline

- Client: Flutter Android/Linux.
- Backend: FastAPI.
- Persistence and vector search: PostgreSQL + pgvector.
- Background execution: PostgreSQL worker queue.
- REST and MCP share domain services.
- Mutations use the pending-action-plan and approval architecture.
- Permission classes, tool limits, and action limits are enforced centrally.
- Provider/source connectors normalize into canonical source objects.
- Temporal Signal creation and execution remain safe and bounded.
- Cost Guard invariants prevent duplicate paid work and unsafe background fan-out.
- Android canonical Gradle proof keeps minSdk at 23.
- Tasks and source objects remain distinct concepts.
- Do not introduce microservices, Redis, Celery, Kafka, Neo4j, Qdrant, or
  Kubernetes without demonstrated need and explicit authorization.

## Telegram credential and integration decisions

- `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` are installation-level platform credentials for Secretary, not per-user profile credentials.
- Per-user Telegram authorization is a separate encrypted session obtained through phone/code/2FA.
- Do not expose `api_id/api_hash` as ordinary user-scoped profile fields.
- Do not treat Bot API and MTProto as interchangeable transports.
- Under current Telegram terms, Telegram-derived data must not enter Secretary AI/ML deployment paths unless the applicable consent requirements are demonstrably satisfied.
- Bot Platform data submitted directly and voluntarily by a user may be used only with clear intended-use disclosure and explicit active revocable consent.
- Bot API retirement is now selected after production acceptance of the ordinary MTProto transport. Cross-transport deduplication is intentionally not being built. Retirement has completed its runtime/external stages: Bot ingress/link/send behavior is disabled, the webhook is deleted, Bot runtime credentials are cleared, and the BotFather bot account has been destroyed. Cross-transport deduplication is intentionally not being built. Stage C may remove dead Bot-only code/UI/tests/config while preserving historical Bot-derived objects and legacy schema; any destructive legacy-schema/data cleanup requires a separate retention decision and explicit authorization.
- MTProto automatic history/folder ingestion must not be production-deployed into assistant/retrieval/embedding/proactive processing unchanged.
- Secretary will nevertheless complete MTProto as an ordinary non-AI communication transport while Telegram's clarification is pending.
- Canonical installation capability flag is `TELEGRAM_MTPROTO_AI_ENABLED`, default `false`.
- The MTProto AI flag gates only ML/LLM eligibility; it must not hide active messages from ordinary Inbox/messenger flows or disable authentication/sync/storage/communication CRUD.
- Existing `scope_active` is a separate transport visibility concern and must not be overloaded as the AI gate.
- When MTProto AI is disabled, canonical MTProto objects must not be embedded, summarized/classified by AI, placed in LLM context, or surfaced through assistant semantic retrieval/tool paths.
- A future `false -> true` transition must use a bounded idempotent catch-up on the existing Postgres queue to embed accumulated active MTProto objects without architectural redesign.
- If Telegram ultimately rejects the private AI use case, the flag remains false and Android/Linux user-owned local surfaces may be researched separately.


## Telegram ordinary Inbox vs attention notifications

- Ordinary inbound Telegram MTProto message creation is an Inbox communication event, not an actionable attention notification.
- Canonical `message_created` MTProto objects remain normal `chat_message` source objects and must surface through the ordinary Inbox/recent-source feed.
- Do not create new unresolved `transport_event/message_created` Notifications for routine inbound MTProto messages.
- Historical deterministic `message_created` Notification rows are retained for compatibility/audit; do not destructively delete or rewrite them merely to change presentation.
- Inbox unresolved/attention presentation must exclude historical MTProto `transport_event/message_created` notifications so existing rows do not continue to clutter `Требует внимания`.
- MTProto `message_edited` and `message_deleted` transport notifications remain unchanged unless separately revised.
- This decision supersedes the earlier C2B/C3B requirement that `message_created` produce an unresolved transport notification; deterministic source-object materialization remains unchanged.


## Telegram MTProto AI activation completion criteria

- Production remains `TELEGRAM_MTPROTO_AI_ENABLED=false` until the applicable Telegram permission/consent question is resolved.
- The future activation direction is `false -> true`.
- Development must be completed and locally proven while the production flag remains false, so no product-code deploy should be required merely to enable the already-built Telegram AI path later.
- Enabling the flag only removes the Telegram-specific AI quarantine. Existing user/global feature switches (for example auto-label and temporal-signal enablement) still apply normally; the Telegram flag does not override them.
- Canonical MTProto objects must use their native `peer_id/peer_title/sender_peer_id/topic_id/reply_to_message_id` metadata directly in conversation projection. Do not require destructive metadata rewrites or legacy Bot-key aliases merely to participate in conversation stacks.
- Presentation grouping is non-AI and may operate while the AI flag is false; semantic stack summarization remains AI-gated.
- Telegram MTProto `chat_message` objects must be able to initiate the same bounded task/object correlation path required by the product without unintentionally enabling correlation for unrelated chat providers as a side effect.
- The existing recurring-sync embedding catch-up is the canonical false->true backlog mechanism: bounded, idempotent, Postgres-queue based, and limited to active-scope canonical MTProto objects.
- Assistant semantic retrieval/context must continue to exclude MTProto while the flag is false and include eligible active-scope MTProto objects when true. Voice uses the same Assistant path and therefore inherits the same gate.
- A production flag change requires the running API/worker environments to be reloaded/recreated; editing a file without applying the environment to running services is not sufficient.
- After explicit external permission, production activation is only: set `TELEGRAM_MTPROTO_AI_ENABLED=true`, reload/recreate the API and worker through an authorized production operation, and let the existing recurring MTProto sync run its bounded embedding catch-up. No migration, metadata rewrite, Telegram relogin, folder reconfiguration, or further product redesign is required for that transition.


## Communication conversation visibility parity

- Canonical communication objects must preserve both inbound and outbound messages when the provider exposes them.
- Conversation history/detail is bidirectional: a user must be able to see their own sent messages together with messages received from other participants.
- This rule is provider-neutral and applies to Telegram, Teams, Mattermost, and future chat-style providers.
- Outbound visibility must not be conflated with attention semantics. Unread/attention/"requires attention" state may remain driven by inbound activity only.
- The unified Inbox/conversation presentation should not hide outbound messages merely because their direction is outbound. If a communication item is grouped into a conversation, the group/member history must include both directions and may use the latest message from either direction for preview/chronology.
- Do not create actionable Notifications merely because an outbound message exists.
- Provider-specific outbound suppression in ordinary communication presentation is a parity defect unless there is a separately documented provider limitation.
- Existing canonical source objects/history should be reused; do not duplicate or rewrite messages solely to change visibility.


## Graph Refined — People & Identity

- The next major product stage is **Graph Refined: People & Identity**.
- A real-world person is a canonical per-user graph node represented by the existing Object model with `kind="person"`; do not build a disconnected contact silo beside the graph.
- Provider/account identities are separate typed identity records attached to the canonical Person. Strong identifiers are namespaced by the provider realm (for example email, Mattermost user id/username within a server, Teams user id within a tenant, Telegram user id/peer id) and must be normalized deterministically.
- An exact strong identifier may resolve/link deterministically. Display-name or fuzzy textual similarity alone must never silently merge two people.
- Ambiguous or similarity-based matches must remain proposed/confirmable and reversible; an incorrect merge must be safely separable without rewriting source messages.
- Source communication Objects remain immutable provenance/evidence. Person resolution layers on top of them; it must not replace provider-native message/account identifiers.
- Future Assistant queries such as “what did Olga write?” should resolve a Person first and then retrieve that person's linked communication objects across providers.
- Future “send to Olga” behavior must never invent an address/username. The backend resolves only known routes for the selected Person; if the route is ambiguous it must clarify. The final provider/account/conversation/recipient is frozen in the existing pending-action-plan approval flow before any external write.
- People/identity work is provider-neutral. Email, Mattermost, Teams, Telegram MTProto, and future communication providers should feed the same identity layer through normalized provider-specific identifiers.

## Telegram development posture while external permission is pending

- Product development should continue assuming Telegram MTProto will eventually participate in the same provider-neutral semantic features as other communication sources; do not fork Graph Refined, voice/media ingestion, task correlation, or other architecture into a Telegram-specific design merely because production AI is currently quarantined.
- Production keeps the existing `TELEGRAM_MTPROTO_AI_ENABLED=false` gate until the external permission/consent question is resolved. The gate remains the hard boundary for Telegram-derived ML/LLM transmission; ordinary Inbox, transport, storage, CRUD, deterministic metadata normalization, and other non-AI behavior remain available.
- Development and tests may build the full gated Telegram paths ahead of permission so future activation remains an environment/configuration operation rather than a redesign.
- A private self-authored Telegram test conversation such as the user's solo `TestML` chat may be used only through the already accepted self-authored canonical MTProto eligibility/safety path. Do not hardcode the chat name or create a product policy exception keyed to `TestML`; the safety property is self-authorship/ownership, not the label.
- If external permission never arrives, the global Telegram AI gate remains false and normal non-AI Telegram Inbox/communication behavior continues to work.

## Major-stage priority after Graph Refined

- After People & Identity, the next intended major stage is provider-neutral voice-note/media ingestion and transcription, especially for communication feeds and hands-free use.
- The following major stage is substantial Task Graph refinement.
- Rolling summaries for very long Assistant conversations remain backlog, not the current stage.
- Further voice/hands-free refinement should be driven by real usage after the media-ingestion stage.
- Today single-day ephemeral-object presentation is a later product enhancement.
- Label aggregation/polish is lower priority.
- Proactive detection of emerging tasks/attention needs is a long-term future stage, not current work.


## Graph Refined — interaction feedback and active identity learning

- User interaction with Assistant/voice/hands-free flows is a valid source of identity-resolution evidence, but interaction semantics must be modeled explicitly rather than treating every route choice as an identity confirmation.
- Keep separate confidence/evidence dimensions for at least:
  1. **person identity** — whether two aliases/endpoints belong to the same real-world Person;
  2. **endpoint ownership** — whether a concrete email/chat/provider endpoint belongs to that Person;
  3. **route preference** — whether the user prefers or selected a particular communication route in a given context.
- Choosing a candidate route during a send flow is positive evidence, but by default it is only weak/moderate evidence for identity/ownership and stronger evidence for route preference. It must not silently become a 100% identity merge.
- Explicit confirmation such as “yes, this Telegram account is Olga Volodko” is strong user-confirmed identity evidence. Explicit correction such as “no, this is another Olga” is strong negative evidence and should prevent the same mistaken merge proposal from recurring.
- Repeated consistent route choices may strengthen the corresponding evidence over time, while contradictory choices or corrections must reduce/override it.
- Preserve the provenance of every confidence contribution (exact provider match, profile/directory fact, graph/context match, LLM suggestion, user route choice, explicit confirmation/rejection) so the derived score is explainable and reversible.
- Prefer deriving a confidence/score from accumulated evidence records over mutating a single opaque probability in place.
- In ambiguous send flows the Assistant may present multiple known/proposed routes with confidence language and ask the user to choose. The selected route still goes through the normal pending-action-plan approval/frozen-route safety boundary before any external write.
- A route choice may optionally trigger a separate lightweight clarification/confirmation when the identity implication matters, but hands-free flows should avoid unnecessary questioning when the user only needs to send a message safely.
