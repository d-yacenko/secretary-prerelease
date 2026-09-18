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
- Therefore Bot API retirement is deferred until the compliant canonical Telegram UX/data boundary is selected and proven.
- MTProto automatic history/folder ingestion must not be production-deployed into assistant/retrieval/embedding/proactive processing unchanged.
- Secretary will nevertheless complete MTProto as an ordinary non-AI communication transport while Telegram's clarification is pending.
- Canonical installation capability flag is `TELEGRAM_MTPROTO_AI_ENABLED`, default `false`.
- The MTProto AI flag gates only ML/LLM eligibility; it must not hide active messages from ordinary Inbox/messenger flows or disable authentication/sync/storage/communication CRUD.
- Existing `scope_active` is a separate transport visibility concern and must not be overloaded as the AI gate.
- When MTProto AI is disabled, canonical MTProto objects must not be embedded, summarized/classified by AI, placed in LLM context, or surfaced through assistant semantic retrieval/tool paths.
- A future `false -> true` transition must use a bounded idempotent catch-up on the existing Postgres queue to embed accumulated active MTProto objects without architectural redesign.
- If Telegram ultimately rejects the private AI use case, the flag remains false and Android/Linux user-owned local surfaces may be researched separately.
