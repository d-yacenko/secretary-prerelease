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
