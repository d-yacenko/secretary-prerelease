# Architecture

See `personal_secretary_llm_build_playbook.md` section 2 for the minimal architecture overview.

PostgreSQL + pgvector is the single source of truth. FastAPI exposes REST; MCP exposes the same domain services. Flutter client targets Android and Linux.
