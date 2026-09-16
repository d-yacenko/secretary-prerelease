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
